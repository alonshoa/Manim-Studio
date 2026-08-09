from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from manim_studio.beats import beat_by_id, discover_entry_beats
from manim_studio.catalog import (
    CatalogEntry,
    entry_target,
    find_scene_entry,
    load_catalog_entries,
    parse_scene_target,
)


LIVE_BEAT_ENV = "MANIM_STUDIO_LIVE_BEAT"
TARGET_BEAT_ENV = "MANIM_STUDIO_BEAT"
DEFAULT_LIVE_ROOT = ".manim-studio/live"

ProcessRunner = Callable[..., subprocess.CompletedProcess]
ExecutableResolver = Callable[[str], str | None]
ModuleFinder = Callable[[str], object | None]
TtyChecker = Callable[[], bool]


@dataclass(frozen=True)
class LiveError(Exception):
    code: str
    message: str
    detail: object | None = None


@dataclass(frozen=True)
class LiveDiagnostic:
    name: str
    ok: bool
    code: str | None
    detail: str
    fix: str | None = None
    severity: str = "error"


@dataclass(frozen=True)
class LivePlan:
    target: str
    beat_id: str
    entry: CatalogEntry
    command: tuple[str, ...]
    cwd: Path
    media_dir: Path
    env: dict[str, str]


def plan_live_preview(
    target: str,
    beat_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    live_root: Path | str = DEFAULT_LIVE_ROOT,
    session_id: str | None = None,
    base_env: dict[str, str] | None = None,
) -> LivePlan:
    root = _repo_root(repo_root)
    try:
        deck_id, scene_id = parse_scene_target(target)
    except ValueError as exc:
        raise LiveError("invalid_target", str(exc)) from exc

    catalog_result = load_catalog_entries(repo_root=root, catalog_path=catalog_path)
    if not catalog_result.ok:
        raise LiveError("catalog_invalid", "catalog could not be loaded", catalog_result.errors)

    entry = find_scene_entry(catalog_result.entries, deck_id, scene_id)
    if entry is None:
        raise LiveError("target_not_found", f"Target not found: {target}")

    beat_result = discover_entry_beats(root, entry)
    if not beat_result.ok:
        raise LiveError("beat_not_found", "Beat validation failed", beat_result.errors)
    if not beat_result.beats:
        raise LiveError("beat_not_found", f"No beats found for target: {target}")
    if beat_by_id(beat_result.beats, beat_id) is None:
        available = ", ".join(beat.id for beat in beat_result.beats)
        raise LiveError(
            "beat_not_found",
            f"Beat not found: {beat_id}",
            {"available_beats": available},
        )

    live_base = Path(live_root)
    if not live_base.is_absolute():
        live_base = root / live_base
    session = session_id or f"{_slugify(target)}-{uuid4().hex[:8]}"
    media_dir = (live_base / session / "media").resolve()
    _ensure_inside_repo(root, media_dir, "live media directory")

    command = (
        "manim",
        "--renderer=opengl",
        "--force_window",
        "-ql",
        "--media_dir",
        str(media_dir),
        entry.source_path,
        entry.class_name,
    )
    env = _live_environment(root, beat_id, base_env)
    return LivePlan(
        target=entry_target(entry),
        beat_id=beat_id,
        entry=entry,
        command=command,
        cwd=root,
        media_dir=media_dir,
        env=env,
    )


def diagnose_live_preview(
    plan: LivePlan,
    executable_resolver: ExecutableResolver = shutil.which,
    module_finder: ModuleFinder = importlib.util.find_spec,
    tty_checker: TtyChecker = lambda: sys.stdin.isatty(),
) -> tuple[LiveDiagnostic, ...]:
    diagnostics: list[LiveDiagnostic] = []

    diagnostics.append(
        _ok_or_fail(
            "Manim CLI",
            executable_resolver("manim") is not None,
            "live_environment_failed",
            "manim was found on PATH",
            "manim was not found on PATH",
            "Install the pinned local dependencies, then retry: python -m pip install -e .",
        )
    )
    diagnostics.append(
        _ok_or_fail(
            "Python import: manim",
            _module_available(module_finder, "manim"),
            "live_environment_failed",
            "manim import is available",
            "manim import is not available",
            "Install Manim Community in the local live-preview Python environment.",
        )
    )
    if _needs_manim_slides(plan):
        diagnostics.append(
            _ok_or_fail(
                "Python import: manim_slides",
                _module_available(module_finder, "manim_slides"),
                "live_environment_failed",
                "manim_slides import is available",
                "manim_slides import is not available",
                "Install the pinned manim-slides dependency in the local Python environment.",
            )
        )
    diagnostics.append(
        _ok_or_fail(
            "OpenGL renderer import",
            _module_available(module_finder, "manim.renderer.opengl_renderer"),
            "live_environment_failed",
            "Manim OpenGL renderer import is available",
            "Manim OpenGL renderer import is not available",
            "Verify the pinned Manim Community installation.",
        )
    )
    diagnostics.append(
        _ok_or_fail(
            "Interactive terminal",
            tty_checker(),
            "live_tty_missing",
            "stdin is attached to a TTY",
            "stdin is not attached to an interactive TTY",
            "Run studio live from an interactive terminal so IPython can own stdin.",
        )
    )
    diagnostics.append(_display_diagnostic())
    diagnostics.append(_ipython_diagnostic(module_finder))
    return tuple(diagnostics)


def run_live_preview(
    target: str,
    beat_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    live_root: Path | str = DEFAULT_LIVE_ROOT,
    runner: ProcessRunner = subprocess.run,
    diagnose: bool = False,
    executable_resolver: ExecutableResolver = shutil.which,
    module_finder: ModuleFinder = importlib.util.find_spec,
    tty_checker: TtyChecker = lambda: sys.stdin.isatty(),
) -> int:
    try:
        plan = plan_live_preview(
            target,
            beat_id,
            repo_root=repo_root,
            catalog_path=catalog_path,
            live_root=live_root,
        )
    except LiveError as exc:
        _print_live_error(exc)
        return 1

    diagnostics = diagnose_live_preview(
        plan,
        executable_resolver=executable_resolver,
        module_finder=module_finder,
        tty_checker=tty_checker,
    )
    if diagnose:
        _print_diagnostics(plan, diagnostics)

    blocking = [item for item in diagnostics if not item.ok and item.severity == "error"]
    if blocking:
        if not diagnose:
            _print_diagnostics(plan, diagnostics)
        print(f"\nlive_environment_failed: {len(blocking)} live preview check(s) failed.")
        return 1

    plan.media_dir.mkdir(parents=True, exist_ok=True)
    print(f"Starting live preview: {plan.target} at beat {plan.beat_id}")
    print(f"Media dir: {plan.media_dir}")
    try:
        completed = runner(
            list(plan.command),
            cwd=plan.cwd,
            check=False,
            env=plan.env,
        )
    except OSError as exc:
        print(f"live_process_failed: {exc}")
        return 1
    return int(completed.returncode)


def _repo_root(repo_root: Path | str | None) -> Path:
    return (Path.cwd() if repo_root is None else Path(repo_root)).resolve()


def _ensure_inside_repo(repo_root: Path, path: Path, label: str) -> None:
    try:
        path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise LiveError("invalid_target", f"{label} must stay inside the repository") from exc


def _live_environment(repo_root: Path, beat_id: str, base_env: dict[str, str] | None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    workspace_src = repo_root / "src"
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [str(workspace_src), str(repo_root)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env[TARGET_BEAT_ENV] = beat_id
    env[LIVE_BEAT_ENV] = beat_id
    return env


def _needs_manim_slides(plan: LivePlan) -> bool:
    if plan.entry.renderer == "manim-slides":
        return True
    source_path = plan.cwd / plan.entry.source_path
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "manim_slides" in source


def _ok_or_fail(
    name: str,
    ok: bool,
    code: str,
    ok_detail: str,
    fail_detail: str,
    fix: str,
) -> LiveDiagnostic:
    return LiveDiagnostic(
        name=name,
        ok=ok,
        code=None if ok else code,
        detail=ok_detail if ok else fail_detail,
        fix=None if ok else fix,
    )


def _display_diagnostic() -> LiveDiagnostic:
    if _inside_container():
        return LiveDiagnostic(
            "Graphical display",
            False,
            "live_display_missing",
            "running inside a container; Docker GUI forwarding is not supported for studio live v1",
            "Use native host Python or WSLg for live preview. Use studio render --beat for headless fallback.",
        )
    if platform.system() == "Windows":
        return LiveDiagnostic(
            "Graphical display",
            True,
            None,
            "Windows native session detected; OpenGL window creation still requires local GUI verification",
            severity="info",
        )
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return LiveDiagnostic(
            "Graphical display",
            True,
            None,
            "DISPLAY or WAYLAND_DISPLAY is set",
        )
    return LiveDiagnostic(
        "Graphical display",
        False,
        "live_display_missing",
        "no DISPLAY or WAYLAND_DISPLAY was found",
        "Run from a desktop session, WSLg, or use studio render --beat as the headless fallback.",
    )


def _ipython_diagnostic(module_finder: ModuleFinder) -> LiveDiagnostic:
    if not _module_available(module_finder, "IPython"):
        return LiveDiagnostic(
            "IPython",
            True,
            None,
            "IPython import was not found during diagnostics; Manim may report this at runtime",
            "If interactive_embed fails, install a compatible IPython version.",
            severity="warning",
        )
    try:
        version = importlib.metadata.version("IPython")
    except importlib.metadata.PackageNotFoundError:
        version = "available, version unknown"
    return LiveDiagnostic(
        "IPython",
        True,
        None,
        f"IPython {version}",
        "If sqlite3.ProgrammingError appears, test the documented workaround: pip install IPython==8.0.1",
        severity="warning",
    )


def _module_available(module_finder: ModuleFinder, module_name: str) -> bool:
    try:
        return module_finder(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _inside_container() -> bool:
    if os.environ.get("MANIM_STUDIO_ALLOW_CONTAINER_LIVE") == "1":
        return False
    return Path("/.dockerenv").exists() or os.environ.get("container") is not None


def _print_live_error(exc: LiveError) -> None:
    print(f"{exc.code}: {exc.message}")
    if isinstance(exc.detail, dict) and exc.detail.get("available_beats"):
        print(f"Available beats: {exc.detail['available_beats']}")
    elif isinstance(exc.detail, (list, tuple)):
        for item in exc.detail:
            print(f"- {item}")
    elif exc.detail is not None:
        print(exc.detail)


def _print_diagnostics(plan: LivePlan, diagnostics: Sequence[LiveDiagnostic]) -> None:
    print("Manim Studio live preview diagnostics")
    print("=====================================")
    print(f"Target: {plan.target}")
    print(f"Beat: {plan.beat_id}")
    print(f"Command: {' '.join(plan.command)}")
    for item in diagnostics:
        if item.ok and item.severity == "warning":
            status = "WARN"
        elif item.ok:
            status = "OK"
        else:
            status = "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
        if item.fix:
            print(f"      Fix: {item.fix}")


def _slugify(value: str) -> str:
    lowered = value.lower()
    chars = [char if char.isalnum() else "-" for char in lowered]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "live"
