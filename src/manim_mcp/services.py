from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from manim_studio.beats import beat_by_id, beats_to_json, discover_entry_beats
from manim_studio.builds import build_deck as run_build_deck
from manim_studio.builds import inspect_build, render_scene as run_render_scene
from manim_studio.catalog import (
    CatalogEntry,
    find_scene_entry,
    list_deck_entries,
    list_decks as catalog_deck_ids,
    load_catalog_entries,
    parse_scene_target,
)
from manim_studio.profiles import get_profile, profile_names
from manim_studio.validation import validate_scene_preflight

from manim_mcp.schemas import failure, success


DEFAULT_CATALOG_PATH = "catalog/scenes.yaml"
DEFAULT_BUILDS_ROOT = "builds"


@dataclass(frozen=True)
class StudioContext:
    repo_root: Path
    catalog_path: Path | str = DEFAULT_CATALOG_PATH
    builds_root: Path | str = DEFAULT_BUILDS_ROOT
    runner: Any = subprocess.run
    check_executables: bool = True


def default_context() -> StudioContext:
    root = Path(os.environ.get("MANIM_STUDIO_REPO_ROOT", Path.cwd())).resolve()
    catalog_path = os.environ.get("MANIM_STUDIO_CATALOG", DEFAULT_CATALOG_PATH)
    builds_root = os.environ.get("MANIM_STUDIO_BUILDS_ROOT", DEFAULT_BUILDS_ROOT)
    return StudioContext(root, catalog_path=catalog_path, builds_root=builds_root)


def list_decks(context: StudioContext | None = None) -> dict[str, Any]:
    ctx = context or default_context()
    result = _load_entries(ctx)
    if not result["ok"]:
        return result

    entries: tuple[CatalogEntry, ...] = result["entries"]
    decks = []
    for deck_id in catalog_deck_ids(entries):
        scenes = list_deck_entries(entries, deck_id)
        decks.append(
            {
                "deck_id": deck_id,
                "scenes": [_entry_summary(entry) for entry in scenes],
            }
        )
    return success(
        {
            "repo_root": ctx.repo_root,
            "catalog_path": _resolved_catalog_path(ctx),
            "decks": decks,
        }
    )


def get_scene_context(target: str, context: StudioContext | None = None) -> dict[str, Any]:
    ctx = context or default_context()
    entry_result = _select_scene(ctx, target)
    if not entry_result["ok"]:
        return entry_result

    entry: CatalogEntry = entry_result["entry"]
    beats_result = discover_entry_beats(ctx.repo_root, entry)
    beats = beats_to_json(beats_result.beats) if beats_result.ok else []

    source_result = _read_registered_source(ctx.repo_root, entry)
    if not source_result["ok"]:
        return source_result

    return success(
        {
            "target": target,
            "entry": asdict(entry),
            "beats": beats,
            "beat_errors": list(beats_result.errors),
            "source": source_result["source"],
        }
    )


def validate_scene(
    target: str,
    profile: str = "draft",
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    entry_result = _select_scene(ctx, target)
    if not entry_result["ok"]:
        return entry_result

    profile_result = _profile(profile)
    if not profile_result["ok"]:
        return profile_result

    preflight = validate_scene_preflight(
        ctx.repo_root,
        entry_result["entry"],
        profile_result["profile"],
        check_executables=ctx.check_executables,
    )
    data = {"target": target, "profile": profile, "preflight": preflight.to_json()}
    if not preflight.ok:
        return failure(
            "validation_failed",
            f"scene validation failed for {target}",
            status="failed",
            data=data,
            detail=preflight.to_json()["issues"],
        )
    return success(data)


def render_scene(
    target: str,
    profile: str = "draft",
    force: bool = False,
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    entry_result = _select_scene(ctx, target)
    if not entry_result["ok"]:
        return entry_result

    profile_result = _profile(profile)
    if not profile_result["ok"]:
        return profile_result

    build = run_render_scene(
        ctx.repo_root,
        entry_result["entry"],
        profile_result["profile"],
        builds_root=ctx.builds_root,
        runner=ctx.runner,
        force=force,
    )
    return _build_response(ctx, build.build_id)


def render_beat(
    target: str,
    beat_id: str,
    profile: str = "draft",
    force: bool = False,
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    entry_result = _select_scene(ctx, target)
    if not entry_result["ok"]:
        return entry_result
    if not _safe_identifier(beat_id):
        return failure("beat_not_found", f"invalid beat id: {beat_id!r}")

    beat_result = discover_entry_beats(ctx.repo_root, entry_result["entry"])
    if not beat_result.ok:
        return failure(
            "validation_failed",
            f"beat discovery failed for {target}",
            status="failed",
            detail=beat_result.errors,
        )
    if beat_by_id(beat_result.beats, beat_id) is None:
        return failure(
            "beat_not_found",
            f"beat not found: {beat_id}",
            data={"available_beats": beats_to_json(beat_result.beats)},
        )

    profile_result = _profile(profile)
    if not profile_result["ok"]:
        return profile_result

    build = run_render_scene(
        ctx.repo_root,
        entry_result["entry"],
        profile_result["profile"],
        builds_root=ctx.builds_root,
        runner=ctx.runner,
        beat_id=beat_id,
        beats=beats_to_json(beat_result.beats),
        force=force,
    )
    return _build_response(ctx, build.build_id)


def build_deck(
    deck_id: str,
    profile: str = "review",
    force: bool = False,
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    if not _safe_identifier(deck_id):
        return failure("invalid_target", "deck id must be a registered identifier")

    entries_result = _load_entries(ctx)
    if not entries_result["ok"]:
        return entries_result

    entries = list_deck_entries(entries_result["entries"], deck_id)
    if not entries:
        return failure("target_not_found", f"deck not found: {deck_id}")

    profile_result = _profile(profile)
    if not profile_result["ok"]:
        return profile_result

    build = run_build_deck(
        ctx.repo_root,
        deck_id,
        entries,
        profile_result["profile"],
        builds_root=ctx.builds_root,
        runner=ctx.runner,
        force=force,
    )
    return _build_response(ctx, build.build_id)


def get_build_manifest(
    build_id: str,
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    inspection_result = _inspect(ctx, build_id)
    if not inspection_result["ok"]:
        return inspection_result
    return success(
        {
            "build_id": build_id,
            "build_dir": inspection_result["inspection"]["build_dir"],
            "manifest": inspection_result["inspection"]["result"],
        }
    )


def get_artifacts(build_id: str, context: StudioContext | None = None) -> dict[str, Any]:
    ctx = context or default_context()
    inspection_result = _inspect(ctx, build_id)
    if not inspection_result["ok"]:
        return inspection_result
    inspection = inspection_result["inspection"]
    return success(
        {
            "build_id": build_id,
            "build_dir": inspection["build_dir"],
            "artifacts": inspection["artifacts"],
        }
    )


def get_build_log(
    build_id: str,
    stream: Literal["stdout", "stderr"] = "stdout",
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    if stream not in {"stdout", "stderr"}:
        return failure("invalid_target", "stream must be 'stdout' or 'stderr'")

    inspection_result = _inspect(ctx, build_id)
    if not inspection_result["ok"]:
        return inspection_result

    inspection = inspection_result["inspection"]
    result = inspection["result"]
    key = f"{stream}_log"
    log_name = result.get(key)
    if not isinstance(log_name, str) or not log_name:
        return failure("unsupported", f"build has no {stream} log: {build_id}")

    log_path = (inspection["build_dir"] / log_name).resolve()
    try:
        log_path.relative_to(inspection["build_dir"].resolve())
    except ValueError:
        return failure("internal_error", f"{stream} log path escapes build directory")

    try:
        text = log_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return failure("build_not_found", f"{stream} log not found for build: {build_id}")
    except OSError as exc:
        return failure(
            "internal_error",
            f"{stream} log could not be read",
            detail=str(exc),
        )

    return success(
        {
            "build_id": build_id,
            "stream": stream,
            "path": log_path,
            "text": text,
        }
    )


def export_deck(
    deck_id: str,
    format: str,
    context: StudioContext | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    if not _safe_identifier(deck_id):
        return failure("invalid_target", "deck id must be a registered identifier")

    entries_result = _load_entries(ctx)
    if not entries_result["ok"]:
        return entries_result
    if not list_deck_entries(entries_result["entries"], deck_id):
        return failure("target_not_found", f"deck not found: {deck_id}")

    return failure(
        "unsupported",
        "deck export is not implemented yet",
        data={"deck_id": deck_id, "format": format},
    )


def conventions_resource(context: StudioContext | None = None) -> dict[str, Any]:
    ctx = context or default_context()
    path = (ctx.repo_root / "docs" / "conventions.md").resolve()
    try:
        path.relative_to(ctx.repo_root)
    except ValueError:
        return failure("internal_error", "conventions path escapes repository")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return failure(
            "internal_error",
            "project conventions could not be read",
            detail=str(exc),
        )
    return success({"path": path, "text": text})


def catalog_resource(context: StudioContext | None = None) -> dict[str, Any]:
    return list_decks(context)


def response_to_json_text(response: dict[str, Any]) -> str:
    return json.dumps(response, indent=2, sort_keys=True)


def _build_response(ctx: StudioContext, build_id: str) -> dict[str, Any]:
    inspection_result = _inspect(ctx, build_id)
    if not inspection_result["ok"]:
        return inspection_result

    inspection = inspection_result["inspection"]
    result = inspection["result"]
    failure_class = result.get("failure_class")
    data = {
        "build_id": build_id,
        "build_dir": inspection["build_dir"],
        "manifest": result,
        "artifacts": inspection["artifacts"],
        "beats": inspection["beats"],
    }
    if result.get("status") != "success":
        code = (
            "validation_failed"
            if failure_class == "validation_failed"
            else "render_failed"
        )
        return failure(
            code,
            f"build {result.get('status', 'failed')}: {build_id}",
            status=str(result.get("status", "failed")),
            data=data,
            detail={"failure_class": failure_class},
        )
    return success(data, status=str(result.get("status", "success")))


def _inspect(ctx: StudioContext, build_id: str) -> dict[str, Any]:
    if not _safe_identifier(build_id):
        return failure("build_not_found", "build id must be a local build identifier")
    try:
        inspection = inspect_build(ctx.repo_root, build_id, builds_root=ctx.builds_root)
    except FileNotFoundError as exc:
        return failure("build_not_found", str(exc))
    except OSError as exc:
        return failure("internal_error", "build could not be inspected", detail=str(exc))
    return {"ok": True, "inspection": inspection}


def _select_scene(ctx: StudioContext, target: str) -> dict[str, Any]:
    if not _safe_target(target):
        return failure("invalid_target", "scene target must use '<deck_id>/<scene_id>' syntax")

    try:
        deck_id, scene_id = parse_scene_target(target)
    except ValueError as exc:
        return failure("invalid_target", str(exc))

    entries_result = _load_entries(ctx)
    if not entries_result["ok"]:
        return entries_result

    entry = find_scene_entry(entries_result["entries"], deck_id, scene_id)
    if entry is None:
        return failure("target_not_found", f"scene not found: {target}")
    return {"ok": True, "entry": entry}


def _load_entries(ctx: StudioContext) -> dict[str, Any]:
    result = load_catalog_entries(repo_root=ctx.repo_root, catalog_path=ctx.catalog_path)
    if not result.ok:
        return failure(
            "catalog_invalid",
            "catalog could not be loaded",
            status="failed",
            detail=result.errors,
        )
    return {"ok": True, "entries": result.entries}


def _profile(name: str) -> dict[str, Any]:
    try:
        return {"ok": True, "profile": get_profile(name)}
    except ValueError as exc:
        return failure(
            "invalid_target",
            str(exc),
            detail={"profiles": profile_names()},
        )


def _read_registered_source(repo_root: Path, entry: CatalogEntry) -> dict[str, Any]:
    source_path = (repo_root / entry.source_path).resolve()
    try:
        source_path.relative_to(repo_root)
    except ValueError:
        return failure("invalid_target", "registered source path escapes repository")
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return failure(
            "internal_error",
            "registered source could not be read",
            detail=str(exc),
        )
    return {
        "ok": True,
        "source": {
            "path": entry.source_path,
            "text": text,
        },
    }


def _entry_summary(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "target": f"{entry.deck_id}/{entry.scene_id}",
        "scene_id": entry.scene_id,
        "renderer": entry.renderer,
        "source_path": entry.source_path,
        "class_name": entry.class_name,
        "description": entry.description,
    }


def _resolved_catalog_path(ctx: StudioContext) -> Path:
    path = Path(ctx.catalog_path)
    if not path.is_absolute():
        path = ctx.repo_root / path
    return path.resolve()


def _safe_target(target: str) -> bool:
    if not isinstance(target, str):
        return False
    try:
        deck_id, scene_id = parse_scene_target(target)
    except ValueError:
        return False
    return _safe_identifier(deck_id) and _safe_identifier(scene_id)


def _safe_identifier(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if not value or value.strip() != value:
        return False
    path = Path(value)
    if path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    return "/" not in value and "\\" not in value
