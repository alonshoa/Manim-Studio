from __future__ import annotations

import argparse
import importlib
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


MIN_PYTHON = (3, 11)
DEFAULT_CATALOG_PATH = "catalog/scenes.yaml"
HEBREW_FONT_QUERIES = (
    "Noto Sans Hebrew",
    "Noto Serif Hebrew",
    "DejaVu Sans",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def _run_command(command: Sequence[str]) -> tuple[bool, str]:
    executable = shutil.which(command[0])
    if executable is None:
        return False, f"{command[0]} was not found on PATH"

    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    output = (completed.stdout or completed.stderr).strip()
    first_line = output.splitlines()[0] if output else "no version output"
    if completed.returncode != 0:
        return False, first_line
    return True, first_line


def _check_python() -> CheckResult:
    version = sys.version_info
    display = platform.python_version()
    ok = version >= MIN_PYTHON
    return CheckResult(
        "Python",
        ok,
        display,
        f"Use Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer." if not ok else None,
    )


def _check_import(module_name: str, display_name: str) -> CheckResult:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        return CheckResult(
            display_name,
            False,
            str(exc),
            f"Install the pinned project dependencies, then retry: python -m pip install -e .",
        )

    version = getattr(module, "__version__", "import succeeded")
    return CheckResult(display_name, True, str(version))


def _check_command(name: str, command: Sequence[str], fix: str) -> CheckResult:
    ok, detail = _run_command(command)
    return CheckResult(name, ok, detail, None if ok else fix)


def _check_hebrew_fonts() -> CheckResult:
    if shutil.which("fc-match") is None:
        return CheckResult(
            "Hebrew-capable font",
            False,
            "fc-match was not found on PATH",
            "Install fontconfig and the documented Hebrew-capable font packages.",
        )

    matches: list[str] = []
    for query in HEBREW_FONT_QUERIES:
        ok, detail = _run_command(("fc-match", query))
        if ok:
            matches.append(f"{query}: {detail}")

    for match in matches:
        normalized = match.lower().replace("-", " ")
        if "noto" in normalized and "hebrew" in normalized:
            return CheckResult("Hebrew-capable font", True, match)
        if "dejavu sans" in normalized:
            return CheckResult("Hebrew-capable font", True, match)

    detail = "; ".join(matches) if matches else "no candidate fonts matched"
    return CheckResult(
        "Hebrew-capable font",
        False,
        detail,
        "Install fonts-dejavu and Noto Hebrew font packages, then run fc-cache -f.",
    )


def run_doctor(
    include_catalog: bool = False,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> int:
    checks: Sequence[Callable[[], CheckResult]] = (
        _check_python,
        lambda: _check_import("manim", "Python import: manim"),
        lambda: _check_import("manim_slides", "Python import: manim_slides"),
        lambda: _check_command(
            "Manim CLI",
            ("manim", "--version"),
            "Install Manim Community with the pinned project dependencies.",
        ),
        lambda: _check_command(
            "Manim Slides CLI",
            ("manim-slides", "--version"),
            "Install manim-slides with the pinned project dependencies.",
        ),
        lambda: _check_command(
            "FFmpeg",
            ("ffmpeg", "-version"),
            "Install ffmpeg in the runtime container image.",
        ),
        lambda: _check_command(
            "LaTeX",
            ("latex", "--version"),
            "Install the TeX Live LaTeX packages in the runtime container image.",
        ),
        lambda: _check_command(
            "XeLaTeX",
            ("xelatex", "--version"),
            "Install texlive-xetex in the runtime container image.",
        ),
        lambda: _check_command(
            "dvisvgm",
            ("dvisvgm", "--version"),
            "Install dvisvgm in the runtime container image.",
        ),
        _check_hebrew_fonts,
    )

    print("Manim Studio doctor")
    print("===================")

    results = [check() for check in checks]
    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
        if result.fix:
            print(f"      Fix: {result.fix}")

    failures = [result for result in results if not result.ok]

    catalog_exit_code = 0
    if include_catalog:
        print("\nCatalog metadata")
        print("----------------")
        catalog_exit_code = run_catalog_validate(
            repo_root=repo_root,
            catalog_path=catalog_path,
            strict_metadata=True,
        )

    if failures:
        print(f"\n{len(failures)} check(s) failed.")
        return 1

    if catalog_exit_code:
        return catalog_exit_code

    print("\nAll checks passed.")
    return 0


def run_catalog_validate(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    strict_metadata: bool = False,
) -> int:
    from manim_studio.catalog import validate_catalog

    result = validate_catalog(
        repo_root=repo_root,
        catalog_path=catalog_path,
        strict_metadata=strict_metadata,
    )
    if result.ok:
        mode = " with strict metadata" if strict_metadata else ""
        print(f"Catalog valid{mode}: {len(result.entries)} scene(s) registered.")
        return 0

    print("Catalog validation failed:")
    for error in result.errors:
        print(f"- {error}")
    return 1


def run_list(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> int:
    from manim_studio.catalog import load_catalog_entries, list_deck_entries, list_decks

    result = load_catalog_entries(repo_root=repo_root, catalog_path=catalog_path)
    if not result.ok:
        _print_catalog_errors(result.errors)
        return 1

    for deck_id in list_decks(result.entries):
        print(deck_id)
        for entry in list_deck_entries(result.entries, deck_id):
            print(
                f"  {entry.scene_id}  "
                f"{entry.renderer}  {entry.source_path}:{entry.class_name}"
            )
    return 0


def run_target_validate(
    target: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> int:
    from manim_studio.catalog import (
        parse_scene_target,
        validate_catalog_selection,
    )

    root = _repo_root(repo_root)
    try:
        if "/" in target:
            deck_id, scene_id = parse_scene_target(target)
            result = validate_catalog_selection(
                repo_root=root,
                catalog_path=catalog_path,
                deck_id=deck_id,
                scene_id=scene_id,
            )
            if not result.ok:
                _print_catalog_errors(result.errors)
                return 1
            if not result.entries:
                print(f"Target not found: {target}")
                return 1
            print(f"Target valid: {target}")
            return 0

        result = validate_catalog_selection(
            repo_root=root,
            catalog_path=catalog_path,
            deck_id=target,
        )
        if not result.ok:
            _print_catalog_errors(result.errors)
            return 1
        if not result.entries:
            print(f"Target not found: {target}")
            return 1
        print(f"Target valid: {target} ({len(result.entries)} scene(s))")
        return 0
    except ValueError as exc:
        print(str(exc))
        return 1


def run_render(
    target: str,
    profile_name: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    beat_id: str | None = None,
    force: bool = False,
    runner=None,
) -> int:
    from manim_studio.builds import render_scene
    from manim_studio.beats import beat_by_id, beats_to_json, discover_entry_beats
    from manim_studio.catalog import find_scene_entry, load_catalog_entries, parse_scene_target
    from manim_studio.profiles import get_profile

    root = _repo_root(repo_root)
    try:
        deck_id, scene_id = parse_scene_target(target)
        profile = get_profile(profile_name)
    except ValueError as exc:
        print(str(exc))
        return 1

    result = load_catalog_entries(repo_root=root, catalog_path=catalog_path)
    if not result.ok:
        _print_catalog_errors(result.errors)
        return 1

    entry = find_scene_entry(result.entries, deck_id, scene_id)
    if entry is None:
        print(f"Target not found: {target}")
        return 1

    beats = None
    if beat_id is not None:
        beat_result = discover_entry_beats(root, entry)
        if not beat_result.ok:
            print("Beat validation failed:")
            for error in beat_result.errors:
                print(f"- {error}")
            return 1
        if not beat_result.beats:
            print(f"No beats found for target: {target}")
            return 1
        if beat_by_id(beat_result.beats, beat_id) is None:
            available = ", ".join(beat.id for beat in beat_result.beats)
            print(f"Beat not found: {beat_id}")
            print(f"Available beats: {available}")
            return 1
        beats = beat_result.beats

    kwargs = {}
    if runner is not None:
        kwargs["runner"] = runner
    build_result = render_scene(
        root,
        entry,
        profile,
        builds_root=builds_root,
        beat_id=beat_id,
        beats=beats_to_json(beats) if beats is not None else None,
        force=force,
        **kwargs,
    )
    print(f"Build {build_result.status}: {build_result.build_id}")
    print(f"Path: {build_result.build_dir}")
    return build_result.returncode


def run_beats(
    target: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> int:
    from manim_studio.beats import discover_entry_beats
    from manim_studio.catalog import (
        find_scene_entry,
        load_catalog_entries,
        parse_scene_target,
    )

    root = _repo_root(repo_root)
    try:
        deck_id, scene_id = parse_scene_target(target)
    except ValueError as exc:
        print(str(exc))
        return 1

    result = load_catalog_entries(repo_root=root, catalog_path=catalog_path)
    if not result.ok:
        _print_catalog_errors(result.errors)
        return 1

    entry = find_scene_entry(result.entries, deck_id, scene_id)
    if entry is None:
        print(f"Target not found: {target}")
        return 1

    beat_result = discover_entry_beats(root, entry)
    if not beat_result.ok:
        print("Beat validation failed:")
        for error in beat_result.errors:
            print(f"- {error}")
        return 1

    print(target)
    if not beat_result.beats:
        print("Beats: none")
        return 0

    for beat in beat_result.beats:
        print(f"- {beat.id}  line {beat.line}  {beat.label}")
    return 0


def run_build(
    deck_id: str,
    profile_name: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    force: bool = False,
    runner=None,
) -> int:
    from manim_studio.builds import build_deck
    from manim_studio.catalog import list_deck_entries, load_catalog_entries
    from manim_studio.profiles import get_profile

    if "/" in deck_id:
        print("deck target must use '<deck_id>' syntax")
        return 1

    root = _repo_root(repo_root)
    try:
        profile = get_profile(profile_name)
    except ValueError as exc:
        print(str(exc))
        return 1

    result = load_catalog_entries(repo_root=root, catalog_path=catalog_path)
    if not result.ok:
        _print_catalog_errors(result.errors)
        return 1

    entries = list_deck_entries(result.entries, deck_id)
    if not entries:
        print(f"Target not found: {deck_id}")
        return 1

    kwargs = {}
    if runner is not None:
        kwargs["runner"] = runner
    build_result = build_deck(
        root,
        deck_id,
        entries,
        profile,
        builds_root=builds_root,
        force=force,
        **kwargs,
    )
    print(f"Deck build {build_result.status}: {build_result.build_id}")
    print(f"Path: {build_result.build_dir}")
    return build_result.returncode


def run_inspect(
    build_id: str,
    repo_root: Path | str | None = None,
    builds_root: Path | str = "builds",
) -> int:
    from manim_studio.builds import inspect_build

    try:
        inspection = inspect_build(_repo_root(repo_root), build_id, builds_root=builds_root)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    result = inspection["result"]
    artifacts = inspection["artifacts"]
    beats = inspection["beats"]
    build_dir = inspection["build_dir"]
    print(f"Build: {result.get('build_id', build_id)}")
    print(f"Kind: {result.get('kind', 'unknown')}")
    print(f"Target: {result.get('target', 'unknown')}")
    print(f"Profile: {result.get('profile', 'unknown')}")
    print(f"Status: {result.get('status', 'unknown')}")
    if "failure_class" in result:
        print(f"Failure class: {result['failure_class']}")
    print(f"Return code: {result.get('returncode', 'unknown')}")
    override = result.get("override")
    if isinstance(override, dict) and override.get("force"):
        print("Override: force")
    preflight = result.get("preflight")
    if isinstance(preflight, dict):
        print(f"Preflight: {'ok' if preflight.get('ok') else 'failed'}")
        issues = preflight.get("issues")
        if isinstance(issues, list) and issues:
            print("Validation issues:")
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                location = ""
                if issue.get("path"):
                    location = f" [{issue['path']}"
                    if issue.get("line"):
                        location += f":{issue['line']}"
                    location += "]"
                print(
                    f"- {issue.get('severity', 'unknown')} "
                    f"{issue.get('code', 'unknown')}: "
                    f"{issue.get('message', '')}{location}"
                )
    smoke = result.get("smoke")
    if isinstance(smoke, dict):
        print(f"Smoke render: return code {smoke.get('returncode', 'unknown')}")
    if "requested_beat" in result:
        print(f"Requested beat: {result['requested_beat']}")
    print(f"Path: {build_dir}")
    if "stdout_log" in result:
        print(f"Stdout: {build_dir / str(result['stdout_log'])}")
    if "stderr_log" in result:
        print(f"Stderr: {build_dir / str(result['stderr_log'])}")
    if artifacts:
        print("Artifacts:")
        for artifact in artifacts:
            if isinstance(artifact, dict):
                print(f"- {artifact.get('path')} ({artifact.get('kind', 'artifact')})")
            else:
                print(f"- {artifact}")
    else:
        print("Artifacts: none")
    if beats:
        print("Beats:")
        for beat in beats:
            if isinstance(beat, dict):
                print(
                    f"- {beat.get('id')}  "
                    f"line {beat.get('line', 'unknown')}  "
                    f"{beat.get('label', '')}"
                )
            else:
                print(f"- {beat}")
    return 0


def _repo_root(repo_root: Path | str | None) -> Path:
    return (Path.cwd() if repo_root is None else Path(repo_root)).resolve()


def _print_catalog_errors(errors: Sequence[str]) -> None:
    print("Catalog validation failed:")
    for error in errors:
        print(f"- {error}")


def build_parser() -> argparse.ArgumentParser:
    from manim_studio.profiles import profile_names

    parser = argparse.ArgumentParser(
        prog="studio",
        description="Manim Studio project tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    profile_choices = profile_names()

    list_parser = subparsers.add_parser(
        "list",
        help="List registered decks and scenes.",
    )
    list_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to list from. Defaults to the current directory.",
    )
    list_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )

    target_validate_parser = subparsers.add_parser(
        "validate",
        help="Validate the catalog and confirm a deck or scene target exists.",
    )
    target_validate_parser.add_argument("target", help="Deck ID or scene target.")
    target_validate_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to validate from. Defaults to the current directory.",
    )
    target_validate_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Render one registered scene into an isolated build directory.",
    )
    render_parser.add_argument("target", help="Scene target as <deck_id>/<scene_id>.")
    render_parser.add_argument(
        "--profile",
        default="draft",
        choices=profile_choices,
        help="Render profile. Defaults to draft.",
    )
    render_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to render from. Defaults to the current directory.",
    )
    render_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    render_parser.add_argument(
        "--builds-root",
        default="builds",
        help="Build output root. Defaults to builds.",
    )
    render_parser.add_argument(
        "--beat",
        default=None,
        help="Render a named beat using section-aware output where supported.",
    )
    render_parser.add_argument(
        "--force",
        action="store_true",
        help="Run despite preflight validation failures. Smoke render failures still block review/final.",
    )

    beats_parser = subparsers.add_parser(
        "beats",
        help="List named beats discovered in a registered scene.",
    )
    beats_parser.add_argument("target", help="Scene target as <deck_id>/<scene_id>.")
    beats_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to inspect from. Defaults to the current directory.",
    )
    beats_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )

    build_deck_parser = subparsers.add_parser(
        "build",
        help="Render all scenes in a registered deck serially.",
    )
    build_deck_parser.add_argument("deck", help="Deck ID.")
    build_deck_parser.add_argument(
        "--profile",
        default="review",
        choices=profile_choices,
        help="Render profile. Defaults to review.",
    )
    build_deck_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to build from. Defaults to the current directory.",
    )
    build_deck_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    build_deck_parser.add_argument(
        "--builds-root",
        default="builds",
        help="Build output root. Defaults to builds.",
    )
    build_deck_parser.add_argument(
        "--force",
        action="store_true",
        help="Run despite preflight validation failures. Smoke render failures still block review/final.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a previous isolated build by build ID.",
    )
    inspect_parser.add_argument("build_id", help="Build directory name under builds/.")
    inspect_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to inspect from. Defaults to the current directory.",
    )
    inspect_parser.add_argument(
        "--builds-root",
        default="builds",
        help="Build output root. Defaults to builds.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report versions and validate required local rendering prerequisites.",
    )
    doctor_parser.add_argument(
        "--catalog",
        action="store_true",
        help="Also run strict catalog metadata validation.",
    )
    doctor_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root for --catalog validation. Defaults to the current directory.",
    )
    doctor_parser.add_argument(
        "--catalog-path",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path for --catalog validation. Defaults to {DEFAULT_CATALOG_PATH}.",
    )

    catalog_parser = subparsers.add_parser(
        "catalog",
        help="Inspect and validate scene catalog metadata.",
    )
    catalog_subparsers = catalog_parser.add_subparsers(
        dest="catalog_command",
        required=True,
    )
    validate_parser = catalog_subparsers.add_parser(
        "validate",
        help="Validate catalog entries against files and scene classes.",
    )
    validate_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to validate from. Defaults to the current directory.",
    )
    validate_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    validate_parser.add_argument(
        "--strict-metadata",
        action="store_true",
        help="Require render commands, baseline paths, planning notes, and related metadata.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return run_list(repo_root=args.repo_root, catalog_path=args.catalog)

    if args.command == "validate":
        return run_target_validate(
            args.target,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
        )

    if args.command == "render":
        return run_render(
            args.target,
            args.profile,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            beat_id=args.beat,
            force=args.force,
        )

    if args.command == "beats":
        return run_beats(
            args.target,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
        )

    if args.command == "build":
        return run_build(
            args.deck,
            args.profile,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            force=args.force,
        )

    if args.command == "inspect":
        return run_inspect(
            args.build_id,
            repo_root=args.repo_root,
            builds_root=args.builds_root,
        )

    if args.command == "doctor":
        return run_doctor(
            include_catalog=args.catalog,
            repo_root=args.repo_root,
            catalog_path=args.catalog_path,
        )

    if args.command == "catalog" and args.catalog_command == "validate":
        return run_catalog_validate(
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            strict_metadata=args.strict_metadata,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
