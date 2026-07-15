from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml


CATALOG_PATH = Path("catalog/scenes.yaml")
CATALOG_VERSION = 1
REQUIRED_FIELDS = frozenset(
    {
        "deck_id",
        "scene_id",
        "source_path",
        "class_name",
        "base_scene_type",
        "renderer",
        "language",
    }
)
OPTIONAL_FIELDS = frozenset({"asset_notes"})
SUPPORTED_RENDERERS = frozenset({"manim", "manim-slides"})


@dataclass(frozen=True)
class CatalogEntry:
    deck_id: str
    scene_id: str
    source_path: str
    class_name: str
    base_scene_type: str
    renderer: str
    language: str
    asset_notes: str | None = None


@dataclass(frozen=True)
class CatalogValidationResult:
    ok: bool
    errors: tuple[str, ...]
    entries: tuple[CatalogEntry, ...] = ()


def validate_catalog(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> CatalogValidationResult:
    root = Path.cwd() if repo_root is None else Path(repo_root)
    root = root.resolve()
    path = Path(catalog_path) if catalog_path is not None else CATALOG_PATH
    if not path.is_absolute():
        path = root / path

    errors: list[str] = []
    raw_catalog = _load_catalog(path, errors)
    if raw_catalog is None:
        return CatalogValidationResult(False, tuple(errors))

    entries = _parse_entries(raw_catalog, errors)
    _validate_entries(root, entries, errors)
    return CatalogValidationResult(not errors, tuple(errors), tuple(entries))


def _load_catalog(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        errors.append(f"{path}: catalog file does not exist.")
        return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        errors.append(f"{path}: YAML could not be parsed: {exc}")
        return None
    except OSError as exc:
        errors.append(f"{path}: catalog could not be read: {exc}")
        return None

    if not isinstance(loaded, dict):
        errors.append(f"{path}: catalog root must be a mapping.")
        return None

    version = loaded.get("version")
    if version != CATALOG_VERSION:
        errors.append(
            f"{path}: expected version {CATALOG_VERSION}, found {version!r}."
        )

    scenes = loaded.get("scenes")
    if not isinstance(scenes, list):
        errors.append(f"{path}: 'scenes' must be a list.")

    return loaded


def _parse_entries(raw_catalog: dict[str, Any], errors: list[str]) -> list[CatalogEntry]:
    scenes = raw_catalog.get("scenes")
    if not isinstance(scenes, list):
        return []

    entries: list[CatalogEntry] = []
    for index, item in enumerate(scenes, start=1):
        label = f"scene #{index}"
        if not isinstance(item, dict):
            errors.append(f"{label}: entry must be a mapping.")
            continue

        missing = sorted(REQUIRED_FIELDS - item.keys())
        if missing:
            errors.append(f"{label}: missing required field(s): {', '.join(missing)}.")
            continue

        unknown = sorted(item.keys() - REQUIRED_FIELDS - OPTIONAL_FIELDS)
        if unknown:
            errors.append(f"{label}: unknown field(s): {', '.join(unknown)}.")

        invalid_required_fields = []
        for field in sorted(REQUIRED_FIELDS):
            if not isinstance(item[field], str) or not item[field].strip():
                invalid_required_fields.append(field)
                errors.append(f"{label}: '{field}' must be a non-empty string.")

        asset_notes = item.get("asset_notes")
        if asset_notes is not None and not isinstance(asset_notes, str):
            errors.append(f"{label}: 'asset_notes' must be a string when provided.")

        if item.get("renderer") not in SUPPORTED_RENDERERS:
            renderers = ", ".join(sorted(SUPPORTED_RENDERERS))
            errors.append(
                f"{label}: renderer {item.get('renderer')!r} is not supported "
                f"(expected one of: {renderers})."
            )

        if invalid_required_fields:
            continue

        entries.append(
            CatalogEntry(
                deck_id=item["deck_id"].strip(),
                scene_id=item["scene_id"].strip(),
                source_path=item["source_path"].strip(),
                class_name=item["class_name"].strip(),
                base_scene_type=item["base_scene_type"].strip(),
                renderer=item["renderer"].strip(),
                language=item["language"].strip(),
                asset_notes=asset_notes.strip() if isinstance(asset_notes, str) else None,
            )
        )

    return entries


def _validate_entries(
    repo_root: Path,
    entries: list[CatalogEntry],
    errors: list[str],
) -> None:
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        label = f"{entry.deck_id}/{entry.scene_id}"
        key = (entry.deck_id, entry.scene_id)
        if key in seen:
            errors.append(f"{label}: duplicate deck_id + scene_id.")
        seen.add(key)

        source_path = _resolve_source_path(repo_root, entry.source_path, label, errors)
        if source_path is None:
            continue

        if not _source_defines_class(source_path, entry.class_name, label, errors):
            continue

        _import_source_file(repo_root, source_path, entry.class_name, label, errors)


def _resolve_source_path(
    repo_root: Path,
    source_path: str,
    label: str,
    errors: list[str],
) -> Path | None:
    resolved = (repo_root / source_path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        errors.append(f"{label}: source_path must stay inside the repository.")
        return None

    if not resolved.exists():
        errors.append(f"{label}: source file does not exist: {source_path}.")
        return None

    if not resolved.is_file():
        errors.append(f"{label}: source_path is not a file: {source_path}.")
        return None

    return resolved


def _source_defines_class(
    source_path: Path,
    class_name: str,
    label: str,
    errors: list[str],
) -> bool:
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        errors.append(f"{label}: source file has invalid Python syntax: {exc}.")
        return False
    except OSError as exc:
        errors.append(f"{label}: source file could not be read: {exc}.")
        return False

    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    if class_name not in class_names:
        errors.append(f"{label}: class {class_name!r} was not found in source file.")
        return False

    return True


def _import_source_file(
    repo_root: Path,
    source_path: Path,
    class_name: str,
    label: str,
    errors: list[str],
) -> ModuleType | None:
    module_name = f"_manim_studio_catalog_{abs(hash(source_path))}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        errors.append(f"{label}: source file could not be imported.")
        return None

    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    sys.path.insert(0, str(repo_root))
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report scene import failures.
        errors.append(f"{label}: source file import failed: {exc}.")
        return None
    finally:
        sys.path[:] = original_path

    if not hasattr(module, class_name):
        errors.append(f"{label}: class {class_name!r} was not available after import.")
        return None

    return module
