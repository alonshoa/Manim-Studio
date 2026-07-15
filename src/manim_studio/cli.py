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
            "Install ffmpeg in the devcontainer image.",
        ),
        lambda: _check_command(
            "LaTeX",
            ("latex", "--version"),
            "Install the TeX Live LaTeX packages in the devcontainer image.",
        ),
        lambda: _check_command(
            "XeLaTeX",
            ("xelatex", "--version"),
            "Install texlive-xetex in the devcontainer image.",
        ),
        lambda: _check_command(
            "dvisvgm",
            ("dvisvgm", "--version"),
            "Install dvisvgm in the devcontainer image.",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studio",
        description="Manim Studio project tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
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
