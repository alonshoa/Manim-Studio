from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manim_studio.beats import beat_by_id, beats_to_json, discover_entry_beats
from manim_studio.builds import BuildResult, render_scene
from manim_studio.catalog import find_scene_entry, load_catalog_entries, parse_scene_target
from manim_studio.profiles import get_profile


@dataclass(frozen=True)
class RenderRequest:
    """A renderer-neutral request for one registered Studio scene."""

    repo_root: Path
    target: str
    profile: str
    catalog_path: Path | str | None = "catalog/scenes.yaml"
    builds_root: Path | str = "builds"
    beat_id: str | None = None
    force: bool = False


@dataclass(frozen=True)
class RenderResult:
    """The resolved request together with the isolated build result."""

    request: RenderRequest
    build: BuildResult


@dataclass(frozen=True)
class RenderRequestError(Exception):
    code: str
    message: str
    detail: Any = None

    def __str__(self) -> str:
        return self.message


def execute_render(
    request: RenderRequest,
    *,
    runner=None,
) -> RenderResult:
    """Resolve and execute one scene render for CLI, MCP, and future preview flows."""

    root = Path(request.repo_root).resolve()
    try:
        deck_id, scene_id = parse_scene_target(request.target)
    except ValueError as exc:
        raise RenderRequestError("invalid_target", str(exc)) from exc

    try:
        profile = get_profile(request.profile)
    except ValueError as exc:
        raise RenderRequestError("invalid_profile", str(exc)) from exc

    catalog = load_catalog_entries(repo_root=root, catalog_path=request.catalog_path)
    if not catalog.ok:
        raise RenderRequestError(
            "catalog_invalid",
            "catalog validation failed",
            tuple(catalog.errors),
        )

    entry = find_scene_entry(catalog.entries, deck_id, scene_id)
    if entry is None:
        raise RenderRequestError(
            "target_not_found",
            f"target not found: {request.target}",
        )

    serialized_beats = None
    if request.beat_id is not None:
        beat_result = discover_entry_beats(root, entry)
        if not beat_result.ok:
            raise RenderRequestError(
                "validation_failed",
                f"beat discovery failed for {request.target}",
                tuple(beat_result.errors),
            )
        if not beat_result.beats:
            raise RenderRequestError(
                "beat_not_found",
                f"no beats found for target: {request.target}",
                {"available_beats": []},
            )
        if beat_by_id(beat_result.beats, request.beat_id) is None:
            available = beats_to_json(beat_result.beats)
            raise RenderRequestError(
                "beat_not_found",
                f"beat not found: {request.beat_id}",
                {"available_beats": available},
            )
        serialized_beats = beats_to_json(beat_result.beats)

    kwargs = {}
    if runner is not None:
        kwargs["runner"] = runner
    build = render_scene(
        root,
        entry,
        profile,
        builds_root=request.builds_root,
        beat_id=request.beat_id,
        beats=serialized_beats,
        force=request.force,
        **kwargs,
    )
    return RenderResult(request=request, build=build)
