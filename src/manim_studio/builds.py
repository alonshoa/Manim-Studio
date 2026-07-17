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
from manim_studio.profiles import RenderProfile


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
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
    "profile.json",
    "result.json",
}


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
) -> BuildResult:
    root = Path(repo_root).resolve()
    root_builds = _resolve_builds_root(root, builds_root)
    build_id = create_build_id("scene", entry_target(entry))
    build_dir = root_builds / build_id
    media_dir = build_dir / "media"
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

    stdout = ""
    stderr = ""
    started_at = _utc_now()
    env = None
    if beat_id is not None:
        env = os.environ.copy()
        env["MANIM_STUDIO_BEAT"] = beat_id
    try:
        completed = runner(
            command,
            cwd=root,
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

    finished_at = _utc_now()
    (build_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (build_dir / "stderr.log").write_text(stderr, encoding="utf-8")

    artifacts = _collect_artifacts(build_dir)
    status = "success" if returncode == 0 else "failed"
    result = {
        "build_id": build_id,
        "kind": "scene",
        "target": entry_target(entry),
        "profile": profile.name,
        "status": status,
        "returncode": returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_log": "stdout.log",
        "stderr_log": "stderr.log",
    }
    if beat_id is not None:
        result["requested_beat"] = beat_id
    _write_json(build_dir / "artifacts.json", {"artifacts": artifacts})
    _write_json(build_dir / "result.json", result)

    return BuildResult(
        build_id=build_id,
        build_dir=build_dir,
        target=entry_target(entry),
        profile=profile.name,
        status=status,
        returncode=returncode,
    )


def build_deck(
    repo_root: Path | str,
    deck_id: str,
    entries: Sequence[CatalogEntry],
    profile: RenderProfile,
    builds_root: Path | str = "builds",
    runner: CommandRunner = subprocess.run,
) -> BuildResult:
    root = Path(repo_root).resolve()
    root_builds = _resolve_builds_root(root, builds_root)
    build_id = create_build_id("deck", deck_id)
    build_dir = root_builds / build_id
    build_dir.mkdir(parents=True, exist_ok=False)

    started_at = _utc_now()
    scene_results = [
        render_scene(root, entry, profile, builds_root=root_builds, runner=runner)
        for entry in entries
    ]
    finished_at = _utc_now()
    status = "success" if all(result.returncode == 0 for result in scene_results) else "failed"
    returncode = 0 if status == "success" else 1
    summary = {
        "build_id": build_id,
        "kind": "deck",
        "target": deck_id,
        "profile": profile.name,
        "status": status,
        "returncode": returncode,
        "started_at": started_at,
        "finished_at": finished_at,
        "scene_builds": [
            {
                "build_id": result.build_id,
                "target": result.target,
                "status": result.status,
                "returncode": result.returncode,
                "path": _relative_to(result.build_dir, root_builds),
            }
            for result in scene_results
        ],
    }
    _write_json(build_dir / "profile.json", asdict(profile))
    _write_json(build_dir / "environment.json", _environment_metadata(root))
    _write_json(build_dir / "result.json", summary)
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
    result_path = build_dir / "result.json"
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
