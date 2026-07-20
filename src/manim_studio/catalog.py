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
OPTIONAL_FIELDS = frozenset(
    {
        "asset_notes",
        "baseline_path",
        "description",
        "font_notes",
        "migration_notes",
        "parameter_notes",
        "render_command",
    }
)
SUPPORTED_RENDERERS = frozenset({"manim", "manim-slides"})
RTL_LANGUAGES = frozenset({"he", "hebrew", "he-il", "rtl"})


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
    baseline_path: str | None = None
    description: str | None = None
    font_notes: str | None = None
    migration_notes: str | None = None
    parameter_notes: str | None = None
    render_command: str | None = None


@dataclass(frozen=True)
class CatalogValidationResult:
    ok: bool
    errors: tuple[str, ...]
    entries: tuple[CatalogEntry, ...] = ()


def entry_target(entry: CatalogEntry) -> str:
    return f"{entry.deck_id}/{entry.scene_id}"


def list_decks(entries: tuple[CatalogEntry, ...] | list[CatalogEntry]) -> tuple[str, ...]:
    return tuple(sorted({entry.deck_id for entry in entries}))


def list_deck_entries(
    entries: tuple[CatalogEntry, ...] | list[CatalogEntry],
    deck_id: str,
) -> tuple[CatalogEntry, ...]:
    return tuple(entry for entry in entries if entry.deck_id == deck_id)


def find_scene_entry(
    entries: tuple[CatalogEntry, ...] | list[CatalogEntry],
    deck_id: str,
    scene_id: str,
) -> CatalogEntry | None:
    for entry in entries:
        if entry.deck_id == deck_id and entry.scene_id == scene_id:
            return entry
    return None


def parse_scene_target(target: str) -> tuple[str, str]:
    parts = target.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("scene target must use '<deck_id>/<scene_id>' syntax")
    return parts[0], parts[1]


def validate_catalog(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    strict_metadata: bool = False,
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
    _validate_entries(root, entries, errors, strict_metadata=strict_metadata)
    return CatalogValidationResult(not errors, tuple(errors), tuple(entries))


def validate_catalog_selection(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    deck_id: str | None = None,
    scene_id: str | None = None,
    strict_metadata: bool = False,
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
    if errors:
        return CatalogValidationResult(False, tuple(errors), tuple(entries))

    selected_entries = _select_entries(entries, deck_id=deck_id, scene_id=scene_id)
    _validate_entries(root, selected_entries, errors, strict_metadata=strict_metadata)
    return CatalogValidationResult(not errors, tuple(errors), tuple(selected_entries))


def load_catalog_entries(
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
    return CatalogValidationResult(not errors, tuple(errors), tuple(entries))


def _select_entries(
    entries: list[CatalogEntry],
    deck_id: str | None,
    scene_id: str | None,
) -> list[CatalogEntry]:
    selected = entries
    if deck_id is not None:
        selected = [entry for entry in selected if entry.deck_id == deck_id]
    if scene_id is not None:
        selected = [entry for entry in selected if entry.scene_id == scene_id]
    return selected


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

        optional_values = _parse_optional_strings(item, label, errors)

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
                asset_notes=optional_values["asset_notes"],
                baseline_path=optional_values["baseline_path"],
                description=optional_values["description"],
                font_notes=optional_values["font_notes"],
                migration_notes=optional_values["migration_notes"],
                parameter_notes=optional_values["parameter_notes"],
                render_command=optional_values["render_command"],
            )
        )

    return entries


def _parse_optional_strings(
    item: dict[str, Any],
    label: str,
    errors: list[str],
) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for field in sorted(OPTIONAL_FIELDS):
        value = item.get(field)
        if value is None:
            values[field] = None
            continue
        if not isinstance(value, str):
            errors.append(f"{label}: '{field}' must be a string when provided.")
            values[field] = None
            continue
        values[field] = value.strip()
    return values


def _validate_entries(
    repo_root: Path,
    entries: list[CatalogEntry],
    errors: list[str],
    strict_metadata: bool,
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

        _validate_metadata(repo_root, source_path, entry, label, errors, strict_metadata)
        _import_source_file(repo_root, source_path, entry.class_name, label, errors)


def _validate_metadata(
    repo_root: Path,
    source_path: Path,
    entry: CatalogEntry,
    label: str,
    errors: list[str],
    strict_metadata: bool,
) -> None:
    if entry.render_command is not None:
        if entry.source_path not in entry.render_command:
            errors.append(f"{label}: render_command must include source_path.")
        if entry.class_name not in entry.render_command:
            errors.append(f"{label}: render_command must include class_name.")

    if entry.baseline_path is not None:
        _resolve_repo_path(repo_root, entry.baseline_path, label, "baseline_path", errors)

    if _uses_external_assets(source_path) and not entry.asset_notes:
        errors.append(f"{label}: asset_notes must describe external assets.")

    if _is_rtl_entry(entry) and not entry.font_notes:
        errors.append(f"{label}: font_notes must describe Hebrew/RTL font requirements.")

    if not strict_metadata:
        return

    required_metadata = (
        "description",
        "render_command",
        "parameter_notes",
        "baseline_path",
        "migration_notes",
    )
    for field in required_metadata:
        if not getattr(entry, field):
            errors.append(f"{label}: {field} is required in strict metadata mode.")


def _is_rtl_entry(entry: CatalogEntry) -> bool:
    return entry.language.lower() in RTL_LANGUAGES


def _uses_external_assets(source_path: Path) -> bool:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return False
    asset_markers = ("ImageMobject", "SVGMobject", "set_texture", "Code(")
    return any(marker in source for marker in asset_markers)


def _resolve_repo_path(
    repo_root: Path,
    repo_path: str,
    label: str,
    field_name: str,
    errors: list[str],
) -> Path | None:
    resolved = (repo_root / repo_path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        errors.append(f"{label}: {field_name} must stay inside the repository.")
        return None

    if not resolved.exists():
        errors.append(f"{label}: {field_name} does not exist: {repo_path}.")
        return None

    return resolved


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
    except ModuleNotFoundError as exc:
        if exc.name in {"manim", "manim_slides"}:
            errors.append(
                f"{label}: source file import failed because {exc.name!r} is not "
                "installed. Run catalog validation inside the runtime container "
                "or install the pinned project dependencies."
            )
        else:
            errors.append(f"{label}: source file import failed: {exc}.")
        return None
    except Exception as exc:  # noqa: BLE001 - report scene import failures.
        errors.append(f"{label}: source file import failed: {exc}.")
        return None
    finally:
        sys.path[:] = original_path

    if not hasattr(module, class_name):
        errors.append(f"{label}: class {class_name!r} was not available after import.")
        return None

    return module
