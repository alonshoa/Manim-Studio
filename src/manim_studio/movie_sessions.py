from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

import yaml

from manim_studio.catalog import CatalogEntry, entry_target, load_catalog_entries
from manim_studio import staged_edits


DEFAULT_DECK_ID = "interactive"
DEFAULT_BEAT_ID = "empty"
DEFAULT_SCENE_ROOT = "decks"


@dataclass(frozen=True)
class MovieSessionError(Exception):
    code: str
    message: str
    detail: Any = None


@dataclass(frozen=True)
class MovieSession:
    session_id: str
    title: str
    target: str
    deck_id: str
    scene_id: str
    class_name: str
    source_path: str
    steps_path: str
    created_at: str
    updated_at: str
    accepted_steps: tuple[dict[str, Any], ...]


def start_movie_session(
    repo_root: Path | str,
    catalog_path: Path | str,
    title: str = "Interactive Movie",
    deck_id: str = DEFAULT_DECK_ID,
    scene_id: str | None = None,
    class_name: str | None = None,
    scene_root: Path | str = DEFAULT_SCENE_ROOT,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    clean_title = title.strip() or "Interactive Movie"
    clean_deck_id = _safe_identifier(deck_id.strip() or DEFAULT_DECK_ID, "deck_id")
    clean_scene_id = _safe_identifier(scene_id or _default_scene_id(clean_title), "scene_id")
    clean_class_name = _safe_class_name(class_name or _default_class_name(clean_title))

    source_path = _scene_source_path(clean_deck_id, clean_scene_id, scene_root)
    steps_path = source_path.with_suffix(".steps.json")
    resolved_source = _repo_path(root, source_path, "source_path")
    resolved_steps = _repo_path(root, steps_path, "steps_path")

    target = f"{clean_deck_id}/{clean_scene_id}"
    _ensure_target_available(root, catalog_path, target)
    if resolved_source.exists():
        raise MovieSessionError(
            "target_exists",
            f"source file already exists for session target: {source_path.as_posix()}",
        )
    if resolved_steps.exists():
        raise MovieSessionError(
            "target_exists",
            f"steps ledger already exists for session target: {steps_path.as_posix()}",
        )

    created_at = _utc_now()
    session = MovieSession(
        session_id=_new_session_id(clean_deck_id, clean_scene_id),
        title=clean_title,
        target=target,
        deck_id=clean_deck_id,
        scene_id=clean_scene_id,
        class_name=clean_class_name,
        source_path=source_path.as_posix(),
        steps_path=steps_path.as_posix(),
        created_at=created_at,
        updated_at=created_at,
        accepted_steps=(),
    )

    resolved_source.parent.mkdir(parents=True, exist_ok=True)
    resolved_source.write_text(_empty_scene_source(clean_class_name), encoding="utf-8")
    _append_catalog_entry(root, catalog_path, session)
    _write_session(root, session)
    return _session_response(session)


def get_movie_session(
    repo_root: Path | str,
    session_id: str,
    scene_root: Path | str = DEFAULT_SCENE_ROOT,
) -> dict[str, Any]:
    session = _load_session(repo_root, session_id, scene_root)
    return _session_response(session)


def propose_movie_step(
    repo_root: Path | str,
    catalog_path: Path | str,
    builds_root: Path | str,
    session_id: str,
    edits: Sequence[dict[str, Any]],
    rationale: str = "",
    scene_root: Path | str = DEFAULT_SCENE_ROOT,
) -> dict[str, Any]:
    session = _load_session(repo_root, session_id, scene_root)
    entry = _session_entry(session)
    return staged_edits.propose_scene_patch(
        repo_root,
        catalog_path,
        builds_root,
        entry,
        edits,
        rationale,
    )


def accept_movie_step(
    repo_root: Path | str,
    builds_root: Path | str,
    session_id: str,
    proposal_id: str,
    note: str = "",
    confirm: str = "accept",
    scene_root: Path | str = DEFAULT_SCENE_ROOT,
) -> dict[str, Any]:
    if confirm != "accept":
        raise MovieSessionError(
            "approval_required",
            "accept_movie_step requires confirm='accept'",
        )

    root = Path(repo_root).resolve()
    session = _load_session(root, session_id, scene_root)
    for step in session.accepted_steps:
        if step.get("proposal_id") == proposal_id:
            return _session_response(session)

    proposal = staged_edits.inspect_scene_patch(root, builds_root, proposal_id)
    if proposal.get("target") != session.target:
        raise MovieSessionError(
            "invalid_target",
            "proposal target does not match movie session",
            detail={"proposal_target": proposal.get("target"), "session_target": session.target},
        )

    applied = staged_edits.apply_scene_patch(
        root,
        builds_root,
        proposal_id,
        _session_entry(session),
        "apply",
    )
    accepted_step = {
        "step": len(session.accepted_steps) + 1,
        "proposal_id": proposal_id,
        "accepted_at": _utc_now(),
        "note": note.strip(),
        "rationale": proposal.get("rationale", ""),
        "base_checksum": proposal.get("base_checksum"),
        "applied_checksum": applied.get("applied", {}).get("applied_checksum"),
        "diff": proposal.get("diff", ""),
    }
    updated = MovieSession(
        **{
            **asdict(session),
            "updated_at": accepted_step["accepted_at"],
            "accepted_steps": (*session.accepted_steps, accepted_step),
        }
    )
    _write_session(root, updated)
    return _session_response(updated)


def _session_response(session: MovieSession) -> dict[str, Any]:
    data = asdict(session)
    data["accepted_steps"] = list(session.accepted_steps)
    data["live"] = {
        "beat_id": DEFAULT_BEAT_ID,
        "command": f"studio live {session.target} --beat {DEFAULT_BEAT_ID} --diagnose",
    }
    return data


def _append_catalog_entry(
    repo_root: Path,
    catalog_path: Path | str,
    session: MovieSession,
) -> None:
    path = Path(catalog_path)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    _ensure_inside_repo(repo_root, path, "catalog_path")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            data = {"version": 1, "scenes": []}
    else:
        data = {"version": 1, "scenes": []}

    if not isinstance(data, dict):
        raise MovieSessionError("catalog_invalid", "catalog root must be a mapping")
    scenes = data.setdefault("scenes", [])
    if not isinstance(scenes, list):
        raise MovieSessionError("catalog_invalid", "catalog scenes must be a list")

    scenes.append(
        {
            "deck_id": session.deck_id,
            "scene_id": session.scene_id,
            "source_path": session.source_path,
            "class_name": session.class_name,
            "base_scene_type": "Scene",
            "renderer": "manim",
            "language": "en",
            "description": f"Interactive movie session: {session.title}",
            "parameter_notes": "Built incrementally from accepted interactive steps.",
            "render_command": f"manim -ql {session.source_path} {session.class_name}",
            "migration_notes": "Generated by studio session start.",
        }
    )
    if "version" not in data:
        data["version"] = 1
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _ensure_target_available(repo_root: Path, catalog_path: Path | str, target: str) -> None:
    result = load_catalog_entries(repo_root=repo_root, catalog_path=catalog_path)
    if not result.ok:
        catalog = Path(catalog_path)
        if catalog.is_absolute() or (repo_root / catalog).exists():
            raise MovieSessionError("catalog_invalid", "catalog could not be loaded", result.errors)
        return
    if any(entry_target(entry) == target for entry in result.entries):
        raise MovieSessionError("target_exists", f"catalog target already exists: {target}")


def _write_session(repo_root: Path, session: MovieSession) -> None:
    path = _repo_path(repo_root, Path(session.steps_path), "steps_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_session_response(session), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_session(
    repo_root: Path | str,
    session_id: str,
    scene_root: Path | str,
) -> MovieSession:
    if not _identifier_re.fullmatch(session_id):
        raise MovieSessionError("session_not_found", "session id must be a local identifier")
    root = Path(repo_root).resolve()
    scene_root_path = _repo_path(root, Path(scene_root), "scene_root")
    matches = list(scene_root_path.rglob("*.steps.json")) if scene_root_path.exists() else []
    for path in matches:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("session_id") == session_id:
            return _session_from_data(data)
    raise MovieSessionError("session_not_found", f"movie session not found: {session_id}")


def _session_from_data(data: dict[str, Any]) -> MovieSession:
    steps = data.get("accepted_steps", [])
    if not isinstance(steps, list):
        steps = []
    try:
        return MovieSession(
            session_id=str(data["session_id"]),
            title=str(data["title"]),
            target=str(data["target"]),
            deck_id=str(data["deck_id"]),
            scene_id=str(data["scene_id"]),
            class_name=str(data["class_name"]),
            source_path=str(data["source_path"]),
            steps_path=str(data["steps_path"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            accepted_steps=tuple(step for step in steps if isinstance(step, dict)),
        )
    except KeyError as exc:
        raise MovieSessionError("session_not_found", "session ledger is missing required fields") from exc


def _session_entry(session: MovieSession) -> CatalogEntry:
    return CatalogEntry(
        deck_id=session.deck_id,
        scene_id=session.scene_id,
        source_path=session.source_path,
        class_name=session.class_name,
        base_scene_type="Scene",
        renderer="manim",
        language="en",
        description=f"Interactive movie session: {session.title}",
        parameter_notes="Built incrementally from accepted interactive steps.",
        render_command=f"manim -ql {session.source_path} {session.class_name}",
        migration_notes="Generated by studio session start.",
    )


def _scene_source_path(deck_id: str, scene_id: str, scene_root: Path | str) -> Path:
    return Path(scene_root) / deck_id / f"{scene_id}.py"


def _empty_scene_source(class_name: str) -> str:
    return (
        "from manim import *\n"
        "\n"
        "from manim_kit.beats import BeatMixin\n"
        "\n"
        "\n"
        f"class {class_name}(BeatMixin, Scene):\n"
        "    def construct(self):\n"
        "        self.beat(\"empty\", label=\"Empty slate\")\n"
        "        self.wait(0.1)\n"
    )


def _repo_path(repo_root: Path, path: Path, label: str) -> Path:
    resolved = path if path.is_absolute() else repo_root / path
    resolved = resolved.resolve()
    _ensure_inside_repo(repo_root, resolved, label)
    return resolved


def _ensure_inside_repo(repo_root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise MovieSessionError("invalid_target", f"{label} must stay inside the repository") from exc


_identifier_re = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _safe_identifier(value: str, label: str) -> str:
    normalized = _slugify(value)
    if not normalized:
        raise MovieSessionError("invalid_target", f"{label} must be a local identifier")
    return normalized


def _safe_class_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", value.strip())
    parts = [part for part in cleaned.split("_") if part]
    class_name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not class_name or class_name[0].isdigit():
        class_name = f"Movie{class_name}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", class_name):
        raise MovieSessionError("invalid_target", "class_name must be a valid Python identifier")
    return class_name


def _default_scene_id(title: str) -> str:
    return f"{_slugify(title) or 'movie'}-{uuid4().hex[:6]}"


def _default_class_name(title: str) -> str:
    return f"{title} Scene"


def _new_session_id(deck_id: str, scene_id: str) -> str:
    return f"{deck_id}-{scene_id}-{uuid4().hex[:8]}"


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    chars = [char if char.isalnum() else "-" for char in lowered]
    return "-".join(part for part in "".join(chars).split("-") if part)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
