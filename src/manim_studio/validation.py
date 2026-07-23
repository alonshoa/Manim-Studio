from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Sequence

from manim_studio.catalog import CatalogEntry, SUPPORTED_RENDERERS, entry_target
from manim_studio.profiles import RenderProfile


ExecutableResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightResult:
    target: str
    ok: bool
    issues: tuple[ValidationIssue, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "target": self.target,
            "ok": self.ok,
            "issues": [issue.to_json() for issue in self.issues],
        }


def validate_scene_preflight(
    repo_root: Path | str,
    entry: CatalogEntry,
    profile: RenderProfile,
    check_executables: bool = True,
    executable_resolver: ExecutableResolver = shutil.which,
) -> PreflightResult:
    root = Path(repo_root).resolve()
    target = entry_target(entry)
    issues: list[ValidationIssue] = []

    source_path = _resolve_source_path(root, entry, issues)
    if entry.renderer not in SUPPORTED_RENDERERS:
        renderers = ", ".join(sorted(SUPPORTED_RENDERERS))
        issues.append(
            ValidationIssue(
                "unsupported_renderer",
                "error",
                f"renderer {entry.renderer!r} is not supported; expected one of: {renderers}",
                entry.source_path,
            )
        )
    elif check_executables:
        executable = _renderer_executable(entry)
        if executable_resolver(executable) is None:
            issues.append(
                ValidationIssue(
                    "missing_renderer_executable",
                    "error",
                    f"{executable} was not found on PATH",
                    entry.source_path,
                )
            )

    if not profile.name or not profile.quality_flag:
        issues.append(
            ValidationIssue(
                "invalid_render_profile",
                "error",
                "render profile must include a name and quality flag",
            )
        )

    if source_path is None:
        return _result(target, issues)

    tree = _parse_source(source_path, entry, issues)
    if tree is None:
        return _result(target, issues)

    _validate_class(tree, entry, issues)
    _validate_literal_assets(root, source_path, tree, issues)
    _import_source(root, source_path, entry, issues)
    return _result(target, issues)


def _result(target: str, issues: Sequence[ValidationIssue]) -> PreflightResult:
    return PreflightResult(
        target=target,
        ok=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
    )


def _resolve_source_path(
    repo_root: Path,
    entry: CatalogEntry,
    issues: list[ValidationIssue],
) -> Path | None:
    source_path = (repo_root / entry.source_path).resolve()
    try:
        source_path.relative_to(repo_root)
    except ValueError:
        issues.append(
            ValidationIssue(
                "source_outside_repo",
                "error",
                "source_path must stay inside the repository",
                entry.source_path,
            )
        )
        return None

    if not source_path.exists():
        issues.append(
            ValidationIssue(
                "missing_source",
                "error",
                f"source file does not exist: {entry.source_path}",
                entry.source_path,
            )
        )
        return None

    if not source_path.is_file():
        issues.append(
            ValidationIssue(
                "invalid_source_path",
                "error",
                f"source_path is not a file: {entry.source_path}",
                entry.source_path,
            )
        )
        return None

    return source_path


def _parse_source(
    source_path: Path,
    entry: CatalogEntry,
    issues: list[ValidationIssue],
) -> ast.Module | None:
    try:
        source = source_path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        issues.append(
            ValidationIssue(
                "python_syntax_error",
                "error",
                f"source file has invalid Python syntax: {exc.msg}",
                entry.source_path,
                exc.lineno,
            )
        )
    except OSError as exc:
        issues.append(
            ValidationIssue(
                "source_read_failed",
                "error",
                f"source file could not be read: {exc}",
                entry.source_path,
            )
        )
    return None


def _validate_class(
    tree: ast.Module,
    entry: CatalogEntry,
    issues: list[ValidationIssue],
) -> None:
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    if entry.class_name not in class_names:
        issues.append(
            ValidationIssue(
                "missing_scene_class",
                "error",
                f"class {entry.class_name!r} was not found in source file",
                entry.source_path,
            )
        )


def _validate_literal_assets(
    repo_root: Path,
    source_path: Path,
    tree: ast.Module,
    issues: list[ValidationIssue],
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        marker = _asset_marker(node)
        if marker is None:
            continue

        asset_value = _asset_value(node)
        if asset_value is None:
            issues.append(
                ValidationIssue(
                    "dynamic_asset_reference",
                    "warning",
                    f"{marker} uses a dynamic asset path that cannot be checked statically",
                    _repo_relative(source_path, repo_root),
                    node.lineno,
                )
            )
            continue

        if not _asset_exists(repo_root, source_path.parent, asset_value):
            issues.append(
                ValidationIssue(
                    "missing_asset",
                    "error",
                    f"{marker} references missing asset: {asset_value}",
                    _repo_relative(source_path, repo_root),
                    node.lineno,
                )
            )


def _asset_marker(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name) and func.id in {"ImageMobject", "SVGMobject", "Code"}:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr == "set_texture":
        return "set_texture"
    return None


def _asset_value(node: ast.Call) -> str | None:
    if node.args:
        return _string_constant(node.args[0])
    for keyword in node.keywords:
        if keyword.arg in {"file_name", "filename", "file", "path", "image_file"}:
            return _string_constant(keyword.value)
    return None


def _asset_exists(repo_root: Path, source_dir: Path, asset_value: str) -> bool:
    asset_path = Path(asset_value)
    candidates = [asset_path] if asset_path.is_absolute() else [
        repo_root / asset_path,
        source_dir / asset_path,
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(repo_root)
        except ValueError:
            continue
        if resolved.exists():
            return True
    return False


def _import_source(
    repo_root: Path,
    source_path: Path,
    entry: CatalogEntry,
    issues: list[ValidationIssue],
) -> ModuleType | None:
    module_name = f"_manim_studio_preflight_{abs(hash(source_path))}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        issues.append(
            ValidationIssue(
                "source_import_failed",
                "error",
                "source file could not be imported",
                entry.source_path,
            )
        )
        return None

    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    sys.path.insert(0, str(repo_root / "src"))
    sys.path.insert(0, str(repo_root))
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        issues.append(
            ValidationIssue(
                "source_import_failed",
                "error",
                f"source file import failed: missing module {exc.name!r}",
                entry.source_path,
            )
        )
        return None
    except Exception as exc:  # noqa: BLE001 - surface scene import failures.
        issues.append(
            ValidationIssue(
                "source_import_failed",
                "error",
                f"source file import failed: {exc}",
                entry.source_path,
            )
        )
        return None
    finally:
        sys.path[:] = original_path

    if not hasattr(module, entry.class_name):
        issues.append(
            ValidationIssue(
                "missing_scene_class_after_import",
                "error",
                f"class {entry.class_name!r} was not available after import",
                entry.source_path,
            )
        )
        return None
    return module


def _renderer_executable(entry: CatalogEntry) -> str:
    if entry.renderer == "manim-slides":
        return "manim-slides"
    return entry.renderer


def _string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return value or None
    return None


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)
