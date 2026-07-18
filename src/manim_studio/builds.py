from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from manim_studio.catalog import CatalogEntry, entry_target
from manim_studio.profiles import RenderProfile, get_profile
from manim_studio.validation import PreflightResult, validate_scene_preflight


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ArtifactGenerator = Callable[[Path, Path], tuple[bool, str]]
ARTIFACT_SUFFIXES = {
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".m4v",
    ".mov",
    ".mp4",
    ".png",
    ".srt",
    ".svg",
    ".vtt",
    ".webm",
}
METADATA_FILENAMES = {
    "artifacts.json",
    "beats.json",
    "catalog_entry.json",
    "command.json",
    "environment.json",
    "manifest.json",
    "profile.json",
    "result.json",
}
EXPENSIVE_PROFILES = {"review", "final"}


@dataclass(frozen=True)
class BuildResult:
    build_id: str
    build_dir: Path
    target: str
    profile: str
    status: str
    returncode: int


def create_build_id(kind: str, target: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    slug = _slugify(target.replace("/", "-"))
    return f"{timestamp}-{kind}-{slug}-{uuid4().hex[:8]}"


def command_for_entry(
    entry: CatalogEntry,
    profile: RenderProfile,
    media_dir: Path,
    save_sections: bool = False,
) -> list[str]:
    profile_args = list(profile.command_args())
    section_args = ["--save_sections"] if save_sections else []
    media_args = ["--media_dir", str(media_dir)]
    if entry.renderer == "manim":
        return [
            "manim",
            *profile_args,
            *section_args,
            *media_args,
            entry.source_path,
            entry.class_name,
        ]
    if entry.renderer == "manim-slides":
        return [
            "manim-slides",
            "render",
            *profile_args,
            *section_args,
            *media_args,
            entry.source_path,
            entry.class_name,
        ]
    raise ValueError(f"unsupported renderer: {entry.renderer}")


def render_scene(
    repo_root: Path | str,
    entry: CatalogEntry,
    profile: RenderProfile,
    builds_root: Path | str = "builds",
    runner: CommandRunner = subprocess.run,
    beat_id: str | None = None,
    beats: Sequence[object] | None = None,
    force: bool = False,
    artifact_generator: ArtifactGenerator | None = None,
) -> BuildResult:
    root = Path(repo_root).resolve()
    root_builds = _resolve_builds_root(root, builds_root)
    build_id = create_build_id("scene", entry_target(entry))
    build_dir = root_builds / build_id
    media_dir = build_dir / "media"
    smoke_media_dir = build_dir / "smoke" / "media"
    build_dir.mkdir(parents=True, exist_ok=False)
    media_dir.mkdir()

    command = command_for_entry(
        entry,
        profile,
        media_dir,
        save_sections=beat_id is not None,
    )
    _write_json(build_dir / "command.json", _command_metadata(command, root, media_dir))
    _write_json(build_dir / "environment.json", _environment_metadata(root))
    _write_json(build_dir / "catalog_entry.json", asdict(entry))
    _write_json(build_dir / "profile.json", asdict(profile))
    if beats is not None:
        _write_json(build_dir / "beats.json", {"beats": _serialize_beats(beats)})

    started_at = _utc_now()
    preflight = validate_scene_preflight(
        root,
        entry,
        profile,
        check_executables=runner is subprocess.run,
    )
    if not preflight.ok and not force:
        return _finalize_scene_build(
            build_id=build_id,
            build_dir=build_dir,
            repo_root=root,
            target=entry_target(entry),
            profile=profile,
            status="failed",
            failure_class="validation_failed",
            returncode=1,
            started_at=started_at,
            finished_at=_utc_now(),
            preflight=preflight,
            force=force,
            command=command,
            smoke=None,
            beat_id=beat_id,
            beats=beats,
            stdout="",
            stderr="",
            review_error=None,
        )

    smoke = None
    if profile.name in EXPENSIVE_PROFILES:
        smoke_media_dir.mkdir(parents=True)
        smoke_profile = get_profile("draft")
        smoke_command = command_for_entry(
            entry,
            smoke_profile,
            smoke_media_dir,
            save_sections=beat_id is not None,
        )
        smoke = _run_logged_command(
            runner,
            smoke_command,
            root,
            build_dir / "smoke_stdout.log",
            build_dir / "smoke_stderr.log",
            beat_id,
        )
        if smoke["returncode"] != 0:
            return _finalize_scene_build(
                build_id=build_id,
                build_dir=build_dir,
                repo_root=root,
                target=entry_target(entry),
                profile=profile,
                status="failed",
                failure_class="smoke_render_failed",
                returncode=int(smoke["returncode"]),
                started_at=started_at,
                finished_at=_utc_now(),
                preflight=preflight,
                force=force,
                command=command,
                smoke=smoke,
                beat_id=beat_id,
                beats=beats,
                stdout="",
                stderr="",
                review_error=None,
            )

    main = _run_logged_command(
        runner,
        command,
        root,
        build_dir / "stdout.log",
        build_dir / "stderr.log",
        beat_id,
    )
    returncode = int(main["returncode"])
    stdout = str(main["stdout"])
    stderr = str(main["stderr"])

    review_error = None
    failure_class = "success" if returncode == 0 else "render_failed"
    status = "success" if returncode == 0 else "failed"
    if returncode == 0 and profile.name == "review":
        artifact_ok, review_error = _generate_review_artifacts(
            build_dir,
            artifact_generator,
            enabled=runner is subprocess.run or artifact_generator is not None,
        )
        if not artifact_ok:
            status = "failed"
            failure_class = "review_artifact_failed"
            returncode = 1

    return _finalize_scene_build(
        build_id=build_id,
        build_dir=build_dir,
        repo_root=root,
        target=entry_target(entry),
        profile=profile,
        status=status,
        returncode=returncode,
        failure_class=failure_class,
        started_at=started_at,
        finished_at=_utc_now(),
        preflight=preflight,
        force=force,
        command=command,
        smoke=smoke,
        beat_id=beat_id,
        beats=beats,
        stdout=stdout,
        stderr=stderr,
        review_error=review_error,
    )


def build_deck(
    repo_root: Path | str,
    deck_id: str,
    entries: Sequence[CatalogEntry],
    profile: RenderProfile,
    builds_root: Path | str = "builds",
    runner: CommandRunner = subprocess.run,
    force: bool = False,
    artifact_generator: ArtifactGenerator | None = None,
) -> BuildResult:
    root = Path(repo_root).resolve()
    root_builds = _resolve_builds_root(root, builds_root)
    build_id = create_build_id("deck", deck_id)
    build_dir = root_builds / build_id
    build_dir.mkdir(parents=True, exist_ok=False)

    started_at = _utc_now()
    scene_results = [
        render_scene(
            root,
            entry,
            profile,
            builds_root=root_builds,
            runner=runner,
            force=force,
            artifact_generator=artifact_generator,
        )
        for entry in entries
    ]
    finished_at = _utc_now()
    status = "success" if all(result.returncode == 0 for result in scene_results) else "failed"
    returncode = 0 if status == "success" else 1
    failure_class = "success"
    if status != "success":
        failure_class = next(
            (
                _result_failure_class(result)
                for result in scene_results
                if result.returncode != 0
            ),
            "render_failed",
        )
    summary = {
        "build_id": build_id,
        "kind": "deck",
        "target": deck_id,
        "profile": profile.name,
        "status": status,
        "failure_class": failure_class,
        "returncode": returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "override": {"force": force},
        "scene_builds": [
            {
                "build_id": result.build_id,
                "target": result.target,
                "status": result.status,
                "failure_class": _result_failure_class(result),
                "returncode": result.returncode,
                "path": _relative_to(result.build_dir, root_builds),
            }
            for result in scene_results
        ],
    }
    _write_json(build_dir / "profile.json", asdict(profile))
    _write_json(build_dir / "environment.json", _environment_metadata(root))
    _write_json(build_dir / "result.json", summary)
    _write_json(build_dir / "manifest.json", {**summary, "artifacts": []})
    _write_json(build_dir / "artifacts.json", {"artifacts": []})
    return BuildResult(
        build_id=build_id,
        build_dir=build_dir,
        target=deck_id,
        profile=profile.name,
        status=status,
        returncode=returncode,
    )


def inspect_build(
    repo_root: Path | str,
    build_id: str,
    builds_root: Path | str = "builds",
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    root_builds = _resolve_builds_root(root, builds_root)
    build_dir = root_builds / build_id
    if not build_dir.exists():
        raise FileNotFoundError(f"build not found: {build_id}")
    manifest_path = build_dir / "manifest.json"
    result_path = manifest_path if manifest_path.exists() else build_dir / "result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"build is missing result.json: {build_id}")
    with result_path.open("r", encoding="utf-8") as handle:
        result = json.load(handle)
    artifacts_path = build_dir / "artifacts.json"
    artifacts: dict[str, object] = {"artifacts": []}
    if artifacts_path.exists():
        with artifacts_path.open("r", encoding="utf-8") as handle:
            artifacts = json.load(handle)
    beats_path = build_dir / "beats.json"
    beats: dict[str, object] = {"beats": []}
    if beats_path.exists():
        with beats_path.open("r", encoding="utf-8") as handle:
            beats = json.load(handle)
    return {
        "build_id": build_id,
        "build_dir": build_dir,
        "result": result,
        "artifacts": artifacts.get("artifacts", []),
        "beats": beats.get("beats", []),
    }


def _resolve_builds_root(repo_root: Path, builds_root: Path | str) -> Path:
    path = Path(builds_root)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _finalize_scene_build(
    build_id: str,
    build_dir: Path,
    repo_root: Path,
    target: str,
    profile: RenderProfile,
    status: str,
    failure_class: str,
    returncode: int,
    started_at: str,
    finished_at: str,
    preflight: PreflightResult,
    force: bool,
    command: Sequence[str],
    smoke: dict[str, object] | None,
    beat_id: str | None,
    beats: Sequence[object] | None,
    stdout: str,
    stderr: str,
    review_error: str | None,
) -> BuildResult:
    stdout_path = build_dir / "stdout.log"
    stderr_path = build_dir / "stderr.log"
    if not stdout_path.exists():
        stdout_path.write_text(stdout, encoding="utf-8")
    if not stderr_path.exists():
        stderr_path.write_text(stderr, encoding="utf-8")

    artifacts = _collect_artifacts(build_dir)
    result = {
        "build_id": build_id,
        "kind": "scene",
        "target": target,
        "profile": profile.name,
        "status": status,
        "failure_class": failure_class,
        "returncode": returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_log": "stdout.log",
        "stderr_log": "stderr.log",
    }
    if beat_id is not None:
        result["requested_beat"] = beat_id

    manifest = {
        **result,
        "override": {"force": force},
        "preflight": preflight.to_json(),
        "command": _command_metadata(command, repo_root, build_dir / "media"),
        "smoke": smoke,
        "review_artifact_error": review_error,
        "artifacts": artifacts,
        "beats": _serialize_beats(beats) if beats is not None else [],
    }
    _write_json(build_dir / "artifacts.json", {"artifacts": artifacts})
    _write_json(build_dir / "result.json", result)
    _write_json(build_dir / "manifest.json", manifest)

    return BuildResult(
        build_id=build_id,
        build_dir=build_dir,
        target=target,
        profile=profile.name,
        status=status,
        returncode=returncode,
    )


def _run_logged_command(
    runner: CommandRunner,
    command: Sequence[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    beat_id: str | None,
) -> dict[str, object]:
    stdout = ""
    stderr = ""
    env = None
    if beat_id is not None:
        env = os.environ.copy()
        env["MANIM_STUDIO_BEAT"] = beat_id
    try:
        completed = runner(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        returncode = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except OSError as exc:
        returncode = 127
        stderr = str(exc)

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "command": list(command),
        "returncode": returncode,
        "stdout_log": stdout_path.name,
        "stderr_log": stderr_path.name,
        "stdout": stdout,
        "stderr": stderr,
    }


def _generate_review_artifacts(
    build_dir: Path,
    artifact_generator: ArtifactGenerator | None,
    enabled: bool,
) -> tuple[bool, str | None]:
    if not enabled:
        return True, None

    review_dir = build_dir / "review"
    frames_dir = review_dir / "frames"
    review_dir.mkdir(exist_ok=True)
    frames_dir.mkdir(exist_ok=True)

    if artifact_generator is not None:
        return artifact_generator(build_dir, review_dir)

    videos = [
        build_dir / artifact["path"]
        for artifact in _collect_artifacts(build_dir)
        if artifact["kind"] == "video"
    ]
    if not videos:
        return False, "no rendered video artifact found for review frame extraction"

    frame_pattern = frames_dir / "frame_%03d.png"
    frame_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(videos[0]),
        "-vf",
        "fps=1/5",
        "-frames:v",
        "6",
        str(frame_pattern),
    ]
    frame_result = subprocess.run(
        frame_command,
        check=False,
        capture_output=True,
        text=True,
    )
    if frame_result.returncode != 0:
        return False, (frame_result.stderr or frame_result.stdout or "ffmpeg frame extraction failed").strip()

    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        return False, "ffmpeg did not produce review frames"

    contact_command = [
        "ffmpeg",
        "-y",
        "-framerate",
        "1",
        "-i",
        str(frame_pattern),
        "-frames:v",
        "1",
        "-vf",
        "tile=3x2",
        str(review_dir / "contact_sheet.png"),
    ]
    contact_result = subprocess.run(
        contact_command,
        check=False,
        capture_output=True,
        text=True,
    )
    if contact_result.returncode != 0:
        return False, (contact_result.stderr or contact_result.stdout or "ffmpeg contact sheet failed").strip()
    return True, None


def _result_failure_class(result: BuildResult) -> str:
    manifest_path = result.build_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "render_failed" if result.returncode else "success"
        failure_class = manifest.get("failure_class")
        if isinstance(failure_class, str) and failure_class:
            return failure_class
    return "success" if result.returncode == 0 else "render_failed"


def _command_metadata(command: Sequence[str], repo_root: Path, media_dir: Path) -> dict[str, object]:
    return {
        "argv": list(command),
        "cwd": str(repo_root),
        "media_dir": str(media_dir),
        "executable": shutil.which(command[0]),
    }


def _environment_metadata(repo_root: Path) -> dict[str, str]:
    return {
        "created_at": _utc_now(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "repo_root": str(repo_root),
    }


def _collect_artifacts(build_dir: Path) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in METADATA_FILENAMES or path.name.endswith(".log"):
            continue
        if path.suffix.lower() not in ARTIFACT_SUFFIXES:
            continue
        artifacts.append(
            {
                "path": _relative_to(path, build_dir),
                "kind": _artifact_kind(path),
            }
        )
    return artifacts


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name == "contact_sheet.png":
        return "contact-sheet"
    if path.parent.name == "frames" and path.parent.parent.name == "review":
        return "review-frame"
    if suffix in {".mp4", ".m4v", ".mov", ".webm"}:
        return "video"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg"}:
        return "image"
    if suffix == ".html":
        return "html"
    if suffix in {".srt", ".vtt"}:
        return "captions"
    return "data"


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _serialize_beats(beats: Sequence[object]) -> list[object]:
    serialized: list[object] = []
    for beat in beats:
        if is_dataclass(beat) and not isinstance(beat, type):
            serialized.append(asdict(beat))
        else:
            serialized.append(beat)
    return serialized


def _relative_to(path: Path, parent: Path) -> str:
    return path.resolve().relative_to(parent.resolve()).as_posix()


def _slugify(value: str) -> str:
    lowered = value.lower()
    chars = [char if char.isalnum() else "-" for char in lowered]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "build"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
