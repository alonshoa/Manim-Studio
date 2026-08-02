from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml

from manim_studio.catalog import entry_target, load_catalog_entries


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]

ARTIFACT_SUFFIXES = {
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".m4v",
    ".mov",
    ".mp4",
    ".png",
    ".pptx",
    ".svg",
    ".webm",
}


@dataclass(frozen=True)
class ProjectVerificationStageResult:
    name: str
    ok: bool
    command: tuple[str, ...] | None
    detail: str


@dataclass(frozen=True)
class ProjectVerificationResult:
    project_root: Path
    target: str
    image_tag: str
    success: bool
    completed_stages: tuple[ProjectVerificationStageResult, ...]
    failed_stage: ProjectVerificationStageResult | None
    message: str
    artifact: Path | None = None


def verify_project(
    path: Path | str,
    render: bool = False,
    runner: CommandRunner = subprocess.run,
    which: Which = shutil.which,
) -> ProjectVerificationResult:
    project_root = Path(path).expanduser().resolve()
    metadata = _load_metadata(project_root)
    target = metadata.get("target", "")
    image_tag = metadata.get("image_tag", "")

    completed: list[ProjectVerificationStageResult] = []

    docker_path = which("docker")
    if docker_path is None:
        return _failed(
            project_root,
            target,
            image_tag,
            completed,
            ProjectVerificationStageResult(
                "Docker CLI",
                False,
                None,
                "Docker was not found on PATH.",
            ),
            "Install Docker or make it available on PATH, then rerun verification.",
        )

    completed.append(
        ProjectVerificationStageResult(
            "Docker CLI",
            True,
            None,
            f"Docker executable found: {docker_path}",
        )
    )

    if "error" in metadata:
        return _failed(
            project_root,
            target,
            image_tag,
            completed,
            ProjectVerificationStageResult(
                "Project metadata",
                False,
                None,
                str(metadata["error"]),
            ),
            str(metadata["error"]),
        )

    stages: list[tuple[str, list[str]]] = [
        ("Docker responsive", ["docker", "info"]),
        ("Runtime image", ["docker", "image", "inspect", image_tag]),
        (
            "Studio doctor",
            ["docker", "compose", "run", "--rm", "studio", "studio", "doctor", "--catalog"],
        ),
        ("Studio list", ["docker", "compose", "run", "--rm", "studio", "studio", "list"]),
        (
            "Starter target validation",
            ["docker", "compose", "run", "--rm", "studio", "studio", "validate", target],
        ),
    ]
    if render:
        stages.append(
            (
                "Draft render",
                [
                    "docker",
                    "compose",
                    "run",
                    "--rm",
                    "studio",
                    "studio",
                    "render",
                    target,
                    "--profile",
                    "draft",
                ],
            )
        )

    for name, command in stages:
        result = _run_stage(name, command, project_root, runner)
        if not result.ok:
            message = _failure_message(name, image_tag, result)
            return _failed(project_root, target, image_tag, completed, result, message)
        completed.append(result)

    artifact = None
    if render:
        artifact = _find_latest_artifact(project_root)
        if artifact is None:
            return _failed(
                project_root,
                target,
                image_tag,
                completed,
                ProjectVerificationStageResult(
                    "Render artifact",
                    False,
                    None,
                    "No host-visible render artifact was found under builds/.",
                ),
                "Draft render completed, but no host-visible artifact was found under builds/.",
            )
        completed.append(
            ProjectVerificationStageResult(
                "Render artifact",
                True,
                None,
                str(artifact),
            )
        )

    return ProjectVerificationResult(
        project_root=project_root,
        target=target,
        image_tag=image_tag,
        success=True,
        completed_stages=tuple(completed),
        failed_stage=None,
        message="Project verification passed.",
        artifact=artifact,
    )


def _load_metadata(project_root: Path) -> dict[str, str]:
    image_tag = ""
    target = ""

    compose_path = project_root / "compose.yml"
    if not compose_path.exists():
        return {"target": target, "image_tag": image_tag, "error": f"Compose file not found: {compose_path}"}

    try:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {"target": target, "image_tag": image_tag, "error": f"Compose file could not be read: {exc}"}

    try:
        image_tag = str(compose["services"]["studio"]["image"]).strip()
    except (KeyError, TypeError):
        return {"target": target, "image_tag": image_tag, "error": "compose.yml must define services.studio.image."}

    catalog = load_catalog_entries(project_root)
    if not catalog.ok:
        return {
            "target": target,
            "image_tag": image_tag,
            "error": "Catalog could not be loaded: " + "; ".join(catalog.errors),
        }
    if not catalog.entries:
        return {"target": target, "image_tag": image_tag, "error": "Catalog has no registered scenes."}

    target = entry_target(catalog.entries[0])
    return {"target": target, "image_tag": image_tag}


def _run_stage(
    name: str,
    command: Sequence[str],
    cwd: Path,
    runner: CommandRunner,
) -> ProjectVerificationStageResult:
    try:
        completed = runner(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return ProjectVerificationStageResult(name, False, tuple(command), str(exc))

    detail = _summarize_output(completed)
    return ProjectVerificationStageResult(
        name,
        completed.returncode == 0,
        tuple(command),
        detail,
    )


def _summarize_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stdout or completed.stderr or "").strip()
    if not output:
        output = f"exit code {completed.returncode}"
    return output.splitlines()[0]


def _failure_message(
    name: str,
    image_tag: str,
    result: ProjectVerificationStageResult,
) -> str:
    if name == "Runtime image":
        return (
            f"Docker image `{image_tag}` was not found. "
            "Build or install the image, then rerun verification."
        )
    command = " ".join(result.command or ())
    if command:
        return f"Verification failed at {name}: {command}"
    return f"Verification failed at {name}: {result.detail}"


def _failed(
    project_root: Path,
    target: str,
    image_tag: str,
    completed: list[ProjectVerificationStageResult],
    failed_stage: ProjectVerificationStageResult,
    message: str,
) -> ProjectVerificationResult:
    return ProjectVerificationResult(
        project_root=project_root,
        target=target,
        image_tag=image_tag,
        success=False,
        completed_stages=tuple(completed),
        failed_stage=failed_stage,
        message=message,
    )


def _find_latest_artifact(project_root: Path) -> Path | None:
    builds_root = project_root / "builds"
    if not builds_root.exists():
        return None

    artifacts = [
        path
        for path in builds_root.rglob("*")
        if path.is_file() and path.suffix.lower() in ARTIFACT_SUFFIXES
    ]
    if not artifacts:
        return None
    return max(artifacts, key=lambda path: path.stat().st_mtime).resolve()
