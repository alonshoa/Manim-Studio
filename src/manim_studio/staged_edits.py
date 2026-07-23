from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from manim_studio.builds import BuildResult, inspect_build, render_scene
from manim_studio.catalog import CatalogEntry, entry_target
from manim_studio.profiles import RenderProfile
from manim_studio.validation import validate_scene_preflight


METADATA_NAME = "proposal.json"
STAGED_DIR_NAME = "staged"
WORKSPACE_DIR_NAME = "workspace"
COPY_IGNORE = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "builds",
    "media",
    "slides",
}
COMMON_MANIM_SYMBOLS = (
    "AnimationGroup",
    "Arrow",
    "Axes",
    "Circle",
    "Code",
    "Dot",
    "ImageMobject",
    "Line",
    "MathTex",
    "NumberPlane",
    "Rectangle",
    "Scene",
    "Square",
    "Tex",
    "Text",
    "ThreeDScene",
    "Triangle",
    "VGroup",
)


class StagedEditError(Exception):
    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def propose_scene_patch(
    repo_root: Path | str,
    catalog_path: Path | str,
    builds_root: Path | str,
    entry: CatalogEntry,
    edits: Sequence[dict[str, Any]],
    rationale: str = "",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    source_path = _source_path(root, entry)
    original = source_path.read_text(encoding="utf-8")
    patched = _apply_edits(original, edits)
    if patched == original:
        raise StagedEditError("empty_patch", "patch does not change the source")

    proposal_id = _new_proposal_id(entry_target(entry))
    proposal_dir = _proposal_dir(root, builds_root, proposal_id)
    workspace_dir = proposal_dir / WORKSPACE_DIR_NAME
    _copy_workspace(root, workspace_dir)

    staged_source = (workspace_dir / entry.source_path).resolve()
    try:
        staged_source.relative_to(workspace_dir)
    except ValueError as exc:
        raise StagedEditError(
            "invalid_target",
            "registered source path escapes staged workspace",
        ) from exc
    staged_source.parent.mkdir(parents=True, exist_ok=True)
    staged_source.write_text(patched, encoding="utf-8")

    diff = _diff_text(entry.source_path, original, patched)
    metadata = {
        "proposal_id": proposal_id,
        "target": entry_target(entry),
        "entry": asdict(entry),
        "catalog_path": str(catalog_path),
        "created_at": _utc_now(),
        "rationale": str(rationale or ""),
        "source_path": entry.source_path,
        "base_checksum": _sha256_text(original),
        "patched_checksum": _sha256_text(patched),
        "edits": list(edits),
        "diff": diff,
        "workspace_dir": str(workspace_dir),
        "proposal_dir": str(proposal_dir),
        "validation": None,
        "draft_render": None,
        "applied": None,
    }
    _write_metadata(proposal_dir, metadata)
    return _public_metadata(metadata)


def inspect_scene_patch(
    repo_root: Path | str,
    builds_root: Path | str,
    proposal_id: str,
) -> dict[str, Any]:
    metadata = _load_metadata(repo_root, builds_root, proposal_id)
    return _public_metadata(metadata)


def validate_scene_patch(
    repo_root: Path | str,
    builds_root: Path | str,
    proposal_id: str,
    profile: RenderProfile,
    check_executables: bool = True,
) -> dict[str, Any]:
    metadata = _load_metadata(repo_root, builds_root, proposal_id)
    workspace_dir = _workspace_dir_from_metadata(metadata)
    entry = _entry_from_metadata(metadata)
    preflight = validate_scene_preflight(
        workspace_dir,
        entry,
        profile,
        check_executables=check_executables,
    )
    metadata["validation"] = {
        "profile": profile.name,
        "status": "success" if preflight.ok else "failed",
        "preflight": preflight.to_json(),
        "validated_at": _utc_now(),
    }
    _write_metadata(_proposal_dir(repo_root, builds_root, proposal_id), metadata)
    return _public_metadata(metadata)


def render_scene_patch(
    repo_root: Path | str,
    builds_root: Path | str,
    proposal_id: str,
    profile: RenderProfile,
    runner: Any,
    check_executables: bool = True,
) -> tuple[dict[str, Any], BuildResult]:
    metadata = _load_metadata(repo_root, builds_root, proposal_id)
    workspace_dir = _workspace_dir_from_metadata(metadata)
    entry = _entry_from_metadata(metadata)
    proposal_builds = _proposal_dir(repo_root, builds_root, proposal_id) / "builds"
    build = render_scene(
        workspace_dir,
        entry,
        profile,
        builds_root=proposal_builds,
        runner=runner,
        force=False,
    )
    inspection = inspect_build(workspace_dir, build.build_id, builds_root=proposal_builds)
    manifest = inspection["result"]
    metadata["draft_render"] = {
        "profile": profile.name,
        "status": build.status,
        "build_id": build.build_id,
        "build_dir": str(build.build_dir),
        "rendered_at": _utc_now(),
        "manifest": manifest,
        "artifacts": inspection["artifacts"],
    }
    if check_executables:
        metadata["draft_render"]["check_executables"] = True
    _write_metadata(_proposal_dir(repo_root, builds_root, proposal_id), metadata)
    return _public_metadata(metadata), build


def apply_scene_patch(
    repo_root: Path | str,
    builds_root: Path | str,
    proposal_id: str,
    current_entry: CatalogEntry,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "apply":
        raise StagedEditError(
            "approval_required",
            "apply_scene_patch requires confirm='apply'",
        )

    root = Path(repo_root).resolve()
    metadata = _load_metadata(root, builds_root, proposal_id)
    entry = _entry_from_metadata(metadata)
    if entry_target(current_entry) != metadata["target"]:
        raise StagedEditError("target_not_found", "proposal target is no longer registered")
    if current_entry.source_path != entry.source_path:
        raise StagedEditError(
            "stale_proposal",
            "registered source path changed since proposal creation",
        )

    validation = metadata.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "success":
        raise StagedEditError(
            "validation_required",
            "proposal must pass staged validation before apply",
        )

    draft_render = metadata.get("draft_render")
    if not isinstance(draft_render, dict) or draft_render.get("status") != "success":
        raise StagedEditError(
            "render_required",
            "proposal must pass staged draft render before apply",
        )

    source_path = _source_path(root, current_entry)
    current = source_path.read_text(encoding="utf-8")
    current_checksum = _sha256_text(current)
    if current_checksum != metadata.get("base_checksum"):
        raise StagedEditError(
            "stale_proposal",
            "canonical source changed since proposal creation",
            detail={
                "expected": metadata.get("base_checksum"),
                "actual": current_checksum,
            },
        )

    staged_source = (_workspace_dir_from_metadata(metadata) / entry.source_path).resolve()
    patched = staged_source.read_text(encoding="utf-8")
    source_path.write_text(patched, encoding="utf-8")
    metadata["applied"] = {
        "status": "success",
        "applied_at": _utc_now(),
        "applied_checksum": _sha256_text(patched),
    }
    _write_metadata(_proposal_dir(root, builds_root, proposal_id), metadata)
    return _public_metadata(metadata)


def propose_render_debug_patch(
    repo_root: Path | str,
    catalog_path: Path | str,
    builds_root: Path | str,
    entry: CatalogEntry,
    manifest: dict[str, Any],
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    if manifest.get("target") != entry_target(entry):
        raise StagedEditError(
            "invalid_target",
            "failed build target does not match requested scene",
            detail={"build_target": manifest.get("target"), "target": entry_target(entry)},
        )
    if manifest.get("status") == "success":
        raise StagedEditError(
            "unsupported",
            "render-debugging requires a failed build manifest",
        )

    log_text = "\n".join([stdout or "", stderr or ""])
    bad_name = _name_error_symbol(log_text)
    if bad_name is None:
        raise StagedEditError(
            "unsupported",
            "render-debugging found no supported NameError pattern",
        )

    replacement = _closest_manim_symbol(bad_name)
    if replacement is None:
        raise StagedEditError(
            "unsupported",
            f"render-debugging has no safe correction for {bad_name!r}",
        )

    source_path = _source_path(Path(repo_root).resolve(), entry)
    lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    token_pattern = re.compile(rf"\b{re.escape(bad_name)}\b")
    for index, line in enumerate(lines, start=1):
        if token_pattern.search(line):
            patched_line = token_pattern.sub(replacement, line, count=1)
            return propose_scene_patch(
                repo_root,
                catalog_path,
                builds_root,
                entry,
                [
                    {
                        "op": "replace",
                        "start_line": index,
                        "end_line": index,
                        "expected": line,
                        "text": patched_line,
                    }
                ],
                rationale=(
                    "render_debugging: replace undefined Manim symbol "
                    f"{bad_name!r} with {replacement!r}"
                ),
            )

    raise StagedEditError(
        "unsupported",
        f"render-debugging could not find {bad_name!r} in the registered source",
    )


def _apply_edits(source: str, edits: Sequence[dict[str, Any]]) -> str:
    if not isinstance(edits, Sequence) or isinstance(edits, (str, bytes)):
        raise StagedEditError("invalid_patch", "edits must be a list of operations")
    lines = source.splitlines(keepends=True)
    result = list(lines)
    normalized = [_normalize_edit(edit, len(lines)) for edit in edits]
    for edit in sorted(normalized, key=lambda item: item["start_line"], reverse=True):
        start = int(edit["start_line"])
        end = int(edit["end_line"])
        expected = edit.get("expected")
        if expected is not None:
            if edit["op"] == "insert_after":
                line = int(edit["line"])
                actual = result[line - 1] if line > 0 else ""
            else:
                actual = "".join(result[start - 1 : end])
            if actual != expected:
                raise StagedEditError(
                    "patch_conflict",
                    "expected text did not match source lines",
                    detail={"start_line": start, "end_line": end},
                )
        op = edit["op"]
        if op == "replace":
            result[start - 1 : end] = _text_lines(edit["text"])
        elif op == "insert_after":
            result[end:end] = _text_lines(edit["text"])
        elif op == "delete":
            result[start - 1 : end] = []
        else:
            raise StagedEditError("invalid_patch", f"unsupported edit op: {op}")
    return "".join(result)


def _normalize_edit(edit: dict[str, Any], line_count: int) -> dict[str, Any]:
    if not isinstance(edit, dict):
        raise StagedEditError("invalid_patch", "each edit must be an object")
    op = edit.get("op") or edit.get("operation")
    if op not in {"replace", "insert_after", "delete"}:
        raise StagedEditError("invalid_patch", "edit op must be replace, insert_after, or delete")

    if op == "insert_after":
        line = _int_field(edit, "line")
        if line < 0 or line > line_count:
            raise StagedEditError("invalid_patch", "insert_after line is out of range")
        return {
            "op": op,
            "line": line,
            "start_line": line + 1,
            "end_line": line,
            "text": _string_field(edit, "text"),
            "expected": edit.get("expected"),
        }

    start = _int_field(edit, "start_line")
    end = _int_field(edit, "end_line")
    if start < 1 or end < start or end > line_count:
        raise StagedEditError("invalid_patch", "edit line range is out of range")
    normalized = {
        "op": op,
        "start_line": start,
        "end_line": end,
        "expected": edit.get("expected"),
    }
    if op in {"replace"}:
        normalized["text"] = _string_field(edit, "text")
    return normalized


def _int_field(edit: dict[str, Any], name: str) -> int:
    value = edit.get(name)
    if not isinstance(value, int):
        raise StagedEditError("invalid_patch", f"{name} must be an integer")
    return value


def _string_field(edit: dict[str, Any], name: str) -> str:
    value = edit.get(name)
    if not isinstance(value, str):
        raise StagedEditError("invalid_patch", f"{name} must be a string")
    return value


def _text_lines(text: str) -> list[str]:
    if text == "":
        return []
    return (text if text.endswith("\n") else text + "\n").splitlines(keepends=True)


def _source_path(repo_root: Path, entry: CatalogEntry) -> Path:
    source_path = (repo_root / entry.source_path).resolve()
    try:
        source_path.relative_to(repo_root)
    except ValueError as exc:
        raise StagedEditError("invalid_target", "registered source path escapes repository") from exc
    if not source_path.is_file():
        raise StagedEditError("target_not_found", f"registered source not found: {entry.source_path}")
    return source_path


def _copy_workspace(repo_root: Path, workspace_dir: Path) -> None:
    proposal_dir = workspace_dir.parent
    proposal_dir.mkdir(parents=True, exist_ok=False)
    shutil.copytree(repo_root, workspace_dir, ignore=_ignore_copy_items)


def _ignore_copy_items(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in COPY_IGNORE}
    ignored.update(name for name in names if name.endswith(".egg-info"))
    return ignored


def _load_metadata(repo_root: Path | str, builds_root: Path | str, proposal_id: str) -> dict[str, Any]:
    if not _safe_identifier(proposal_id):
        raise StagedEditError("proposal_not_found", "proposal id must be a local identifier")
    path = _proposal_dir(repo_root, builds_root, proposal_id) / METADATA_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StagedEditError("proposal_not_found", f"proposal not found: {proposal_id}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise StagedEditError("internal_error", "proposal metadata could not be read", str(exc)) from exc


def _write_metadata(proposal_dir: Path, metadata: dict[str, Any]) -> None:
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / METADATA_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _entry_from_metadata(metadata: dict[str, Any]) -> CatalogEntry:
    entry = metadata.get("entry")
    if not isinstance(entry, dict):
        raise StagedEditError("internal_error", "proposal metadata is missing entry")
    return CatalogEntry(**entry)


def _workspace_dir_from_metadata(metadata: dict[str, Any]) -> Path:
    workspace = Path(str(metadata.get("workspace_dir", ""))).resolve()
    if not workspace.is_dir():
        raise StagedEditError("proposal_not_found", "proposal workspace is missing")
    return workspace


def _proposal_dir(repo_root: Path | str, builds_root: Path | str, proposal_id: str) -> Path:
    return _staged_root(repo_root, builds_root) / proposal_id


def _staged_root(repo_root: Path | str, builds_root: Path | str) -> Path:
    root = Path(repo_root).resolve()
    path = Path(builds_root)
    if not path.is_absolute():
        path = root / path
    return (path / STAGED_DIR_NAME).resolve()


def _new_proposal_id(target: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = "".join(char if char.isalnum() else "-" for char in target.lower()).strip("-")
    return f"{timestamp}-patch-{slug}-{uuid4().hex[:8]}"


def _diff_text(path: str, original: str, patched: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    public = dict(metadata)
    public.pop("workspace_dir", None)
    public.pop("proposal_dir", None)
    return public


def _name_error_symbol(log_text: str) -> str | None:
    patterns = (
        r"NameError:\s+name ['\"]([^'\"]+)['\"] is not defined",
        r"name ['\"]([^'\"]+)['\"] is not defined",
    )
    for pattern in patterns:
        match = re.search(pattern, log_text)
        if match:
            return match.group(1)
    return None


def _closest_manim_symbol(value: str) -> str | None:
    best_symbol = None
    best_distance = 999
    for symbol in COMMON_MANIM_SYMBOLS:
        distance = _edit_distance(value, symbol)
        if distance < best_distance:
            best_symbol = symbol
            best_distance = distance
    if best_symbol is not None and best_distance <= 2:
        return best_symbol
    return None


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[right_index - 1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _safe_identifier(value: str) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value:
        return False
    path = Path(value)
    if path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    return "/" not in value and "\\" not in value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
