from __future__ import annotations

import argparse
import importlib
import json
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
    if sys.platform == "win32":
        # Pango is the text backend used by Manim and sees installed Windows fonts.
        try:
            from manimpango import list_fonts
            installed = {name.casefold(): name for name in list_fonts()}
        except (ImportError, OSError) as exc:
            return CheckResult("Hebrew-capable font", False, str(exc),
                               "Install the pinned Manim dependencies and the DejaVu fonts.")
        for candidate in HEBREW_FONT_QUERIES:
            if candidate.casefold() in installed:
                return CheckResult("Hebrew-capable font", True, installed[candidate.casefold()])
        return CheckResult("Hebrew-capable font", False, "No documented Hebrew font found by Pango",
                           "Install DejaVu Sans or Noto Sans Hebrew, then restart the Python process.")
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


def run_live(
    target: str,
    beat_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    live_root: Path | str = ".manim-studio/live",
    diagnose: bool = False,
    runner=None,
) -> int:
    from manim_studio.live import run_live_preview

    kwargs = {}
    if runner is not None:
        kwargs["runner"] = runner
    return run_live_preview(
        target,
        beat_id,
        repo_root=repo_root,
        catalog_path=catalog_path,
        live_root=live_root,
        diagnose=diagnose,
        **kwargs,
    )


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


def run_export(
    deck_id: str,
    format: str,
    profile_name: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    force: bool = False,
    runner=None,
) -> int:
    from manim_studio.builds import ExportDeckError, export_deck, inspect_build
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
    try:
        build_result = export_deck(
            root,
            deck_id,
            entries,
            profile,
            format=format,
            builds_root=builds_root,
            force=force,
            **kwargs,
        )
    except ExportDeckError as exc:
        print(f"{exc.code}: {exc.message}")
        if exc.detail:
            print(exc.detail)
        return 1

    print(f"Deck export {build_result.status}: {build_result.build_id}")
    print(f"Path: {build_result.build_dir}")
    try:
        inspection = inspect_build(root, build_result.build_id, builds_root=builds_root)
    except FileNotFoundError:
        return build_result.returncode
    artifacts = inspection["artifacts"]
    if artifacts:
        print("Artifacts:")
        for artifact in artifacts:
            if isinstance(artifact, dict):
                print(f"- {artifact.get('path')} ({artifact.get('kind', 'artifact')})")
            else:
                print(f"- {artifact}")
    else:
        print("Artifacts: none")
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


def run_project_init(
    path: Path | str,
    name: str,
    deck_id: str | None = None,
    scene_id: str | None = None,
    class_name: str | None = None,
    language: str | None = None,
    image_tag: str | None = None,
    force: bool = False,
) -> int:
    from manim_studio.project_builder import ProjectBuilderError, create_project, default_options

    try:
        options = default_options(
            path=path,
            name=name,
            deck_id=deck_id,
            scene_id=scene_id,
            class_name=class_name,
            language=language,
            image_tag=image_tag,
            force=force,
        )
        result = create_project(options)
    except ProjectBuilderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created Manim Studio project: {result.root}")
    print(f"Registered starter target: {result.target}")
    print(f"Files written: {len(result.files_written)}")
    for path_written in result.files_written:
        print(f"- {path_written.relative_to(result.root).as_posix()}")
    print("\nNext command:")
    print(f"  studio project verify {result.root}")
    return 0


def run_project_verify(path: Path | str, render: bool = False) -> int:
    from manim_studio.project_verifier import verify_project

    result = verify_project(path, render=render)
    for stage in result.completed_stages:
        print(f"[OK] {stage.name}: {stage.detail}")

    if result.failed_stage is not None:
        stage = result.failed_stage
        print(f"[FAILED] {stage.name}: {stage.detail}")
        print()
        print(result.message)
        print()
        print("Rerun after fixing the failed stage:")
        command = f"studio project verify {result.project_root}"
        if render:
            command += " --render"
        print(command)
        return 1

    print(result.message)
    if result.artifact is not None:
        print(f"Artifact: {result.artifact}")
    return 0


def run_session_start(
    title: str,
    deck_id: str,
    scene_id: str | None = None,
    class_name: str | None = None,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
) -> int:
    from manim_studio.movie_sessions import MovieSessionError, start_movie_session

    try:
        session = start_movie_session(
            _repo_root(repo_root),
            catalog_path or DEFAULT_CATALOG_PATH,
            title=title,
            deck_id=deck_id,
            scene_id=scene_id,
            class_name=class_name,
        )
    except MovieSessionError as exc:
        print(f"{exc.code}: {exc.message}")
        if exc.detail is not None:
            print(exc.detail)
        return 1

    print(f"Movie session started: {session['session_id']}")
    print(f"Target: {session['target']}")
    print(f"Source: {session['source_path']}")
    print(f"Steps: {session['steps_path']}")
    print(f"Live command: {session['live']['command']}")
    return 0


def run_session_inspect(
    session_id: str,
    repo_root: Path | str | None = None,
) -> int:
    from manim_studio.movie_sessions import MovieSessionError, get_movie_session

    try:
        session = get_movie_session(_repo_root(repo_root), session_id)
    except MovieSessionError as exc:
        print(f"{exc.code}: {exc.message}")
        if exc.detail is not None:
            print(exc.detail)
        return 1

    print(f"Movie session: {session['session_id']}")
    print(f"Title: {session['title']}")
    print(f"Target: {session['target']}")
    print(f"Source: {session['source_path']}")
    print(f"Steps: {session['steps_path']}")
    print(f"Live command: {session['live']['command']}")
    steps = session["accepted_steps"]
    if not steps:
        print("Accepted steps: none")
        return 0
    print("Accepted steps:")
    for step in steps:
        note = step.get("note") or step.get("rationale") or ""
        print(f"- {step.get('step')}  {step.get('proposal_id')}  {note}")
    return 0


def run_session_accept(
    session_id: str,
    proposal_id: str,
    note: str = "",
    confirm: str = "accept",
    repo_root: Path | str | None = None,
    builds_root: Path | str = "builds",
) -> int:
    from manim_studio.movie_sessions import MovieSessionError, accept_movie_step
    from manim_studio.staged_edits import StagedEditError

    try:
        session = accept_movie_step(
            _repo_root(repo_root),
            builds_root,
            session_id,
            proposal_id,
            note=note,
            confirm=confirm,
        )
    except (MovieSessionError, StagedEditError) as exc:
        print(f"{exc.code}: {exc.message}")
        if exc.detail is not None:
            print(exc.detail)
        return 1

    print(f"Accepted proposal: {proposal_id}")
    print(f"Movie session: {session['session_id']}")
    print(f"Accepted steps: {len(session['accepted_steps'])}")
    print(f"Steps: {session['steps_path']}")
    return 0


def run_authoring_start(
    title: str,
    deck_id: str,
    scene_id: str | None = None,
    class_name: str | None = None,
    language: str | None = None,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    try:
        data = _authoring_controller(repo_root, catalog_path).start_session(
            title=title,
            deck_id=deck_id,
            scene_id=scene_id,
            class_name=class_name,
            language=language,
        )
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_status(
    session_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    try:
        data = _authoring_controller(repo_root, catalog_path).get_status(session_id)
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_list(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError

    try:
        data = _authoring_controller(repo_root, catalog_path).list_sessions()
    except AuthoringSessionError as exc:
        return _print_authoring_error(exc, json_output)
    if json_output:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    for session in data.get("sessions", []):
        print(
            f"{session['session_id']}  {session['title']}  {session['target']}  "
            f"{session['authoring_status']}  {session['beat']}  {session['updated_at']}"
        )
    return 0


def run_authoring_append(
    session_id: str,
    body: str,
    title: str,
    rationale: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError
    from manim_studio.staged_edits import StagedEditError

    try:
        data = _authoring_controller(repo_root, catalog_path, builds_root).propose_next_movie_step(
            session_id,
            body,
            title=title,
            rationale=rationale,
        )
    except (AuthoringSessionError, MovieSessionError, StagedEditError, SyntaxError, OSError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_preview(
    session_id: str,
    proposal_id: str | None = None,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError
    from manim_studio.staged_edits import StagedEditError

    try:
        data = _authoring_controller(repo_root, catalog_path, builds_root).preview_proposal(
            session_id,
            proposal_id,
        )
    except (AuthoringSessionError, MovieSessionError, StagedEditError, SyntaxError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_accept(
    session_id: str,
    proposal_id: str | None = None,
    note: str = "",
    confirm: str = "accept",
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError
    from manim_studio.staged_edits import StagedEditError

    try:
        data = _authoring_controller(repo_root, catalog_path, builds_root).accept_proposal(
            session_id,
            proposal_id,
            note=note,
            confirm=confirm,
        )
    except (AuthoringSessionError, MovieSessionError, StagedEditError, SyntaxError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_reject(
    session_id: str,
    proposal_id: str | None = None,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    try:
        data = _authoring_controller(repo_root, catalog_path).reject_proposal(
            session_id,
            proposal_id,
        )
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_revise(
    session_id: str,
    feedback: str,
    proposal_id: str | None = None,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    try:
        data = _authoring_controller(repo_root, catalog_path).revise_proposal(
            session_id,
            feedback,
            proposal_id,
        )
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_session_action(
    action: str,
    session_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    controller = _authoring_controller(repo_root, catalog_path, builds_root)
    try:
        if action == "pause":
            data = controller.pause_session(session_id)
        elif action == "resume":
            data = controller.resume_session(session_id)
        elif action == "finish":
            data = controller.finish_session(session_id)
        elif action == "discover":
            data = controller.discover_active_proposal(session_id)
        else:
            raise AuthoringSessionError("unsupported", f"unknown authoring action: {action}")
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_live_action(
    action: str,
    session_id: str,
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    json_output: bool = False,
) -> int:
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.movie_sessions import MovieSessionError

    controller = _authoring_controller(repo_root, catalog_path)
    try:
        if action == "live-start":
            data = controller.start_live(session_id)
        elif action == "live-restart":
            data = controller.reload_live(session_id)
        elif action == "live-stop":
            data = controller.stop_live(session_id)
        else:
            raise AuthoringSessionError("unsupported", f"unknown live action: {action}")
    except (AuthoringSessionError, MovieSessionError) as exc:
        return _print_authoring_error(exc, json_output)
    _print_authoring_response(data, json_output)
    return 0


def run_authoring_rpc(
    repo_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    builds_root: Path | str = "builds",
) -> int:
    return _authoring_controller(repo_root, catalog_path, builds_root).rpc_loop()


def _authoring_controller(
    repo_root: Path | str | None,
    catalog_path: Path | str | None,
    builds_root: Path | str = "builds",
):
    from manim_studio.authoring_sessions import AuthoringSessionController

    return AuthoringSessionController(
        _repo_root(repo_root),
        catalog_path=catalog_path or DEFAULT_CATALOG_PATH,
        builds_root=builds_root,
    )


def _print_authoring_response(data: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    print(f"Authoring session: {data['session_id']}")
    print(f"Status: {data['status']}")
    print(f"Target: {data['target']}")
    print(f"Revision: {data['revision']}")
    print(f"Beat: {data['beat']}")
    print(f"Live: {data['live_status']}")
    if data.get("proposal_id"):
        print(f"Proposal: {data['proposal_id']}")
    print(f"Source: {data['source_path']}")
    if data.get("error"):
        print(f"Error: {data['error']}")


def _print_authoring_error(exc: Exception, json_output: bool) -> int:
    code = getattr(exc, "code", "internal_error")
    message = getattr(exc, "message", str(exc))
    detail = getattr(exc, "detail", None)
    if json_output:
        print(
            json.dumps(
                {"ok": False, "error": {"code": code, "message": message, "detail": detail}},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"{code}: {message}")
        if detail is not None:
            print(detail)
    return 1


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
    research_parser = subparsers.add_parser('research', help='Research annotation tools.')
    research_commands = research_parser.add_subparsers(dest='research_command', required=True)
    research_rpc = research_commands.add_parser('rpc', help='Dedicated prompt annotation RPC transport.')
    research_rpc.add_argument('--repo-root', default=None)
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

    live_parser = subparsers.add_parser(
        "live",
        help="Start an experimental OpenGL live preview at a named beat.",
    )
    live_parser.add_argument("target", help="Scene target as <deck_id>/<scene_id>.")
    live_parser.add_argument(
        "--beat",
        required=True,
        help="Named beat where the scene should enter interactive mode.",
    )
    live_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to run from. Defaults to the current directory.",
    )
    live_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    live_parser.add_argument(
        "--live-root",
        default=".manim-studio/live",
        help="Transient live-preview output root. Defaults to .manim-studio/live.",
    )
    live_parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print live-preview environment diagnostics before starting.",
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

    export_parser = subparsers.add_parser(
        "export",
        help="Export an all-slides deck to a delivery artifact.",
    )
    export_parser.add_argument("deck", help="Deck ID.")
    export_parser.add_argument(
        "--format",
        default="pptx",
        choices=("pptx",),
        help="Export format. Defaults to pptx.",
    )
    export_parser.add_argument(
        "--profile",
        default="final",
        choices=profile_choices,
        help="Render profile used before export. Defaults to final.",
    )
    export_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to export from. Defaults to the current directory.",
    )
    export_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )
    export_parser.add_argument(
        "--builds-root",
        default="builds",
        help="Build output root. Defaults to builds.",
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="Run despite preflight validation failures. Smoke render failures still block final rendering.",
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

    project_parser = subparsers.add_parser(
        "project",
        help="Create and verify external Manim Studio projects.",
    )
    project_subparsers = project_parser.add_subparsers(
        dest="project_command",
        required=True,
    )
    init_parser = project_subparsers.add_parser(
        "init",
        help="Generate an external Manim Studio project.",
    )
    init_parser.add_argument("path", help="Directory where the project will be generated.")
    init_parser.add_argument("--name", required=True, help="Human-readable project name.")
    init_parser.add_argument("--deck-id", default=None, help="Starter deck ID.")
    init_parser.add_argument("--scene-id", default=None, help="Starter scene ID.")
    init_parser.add_argument("--class-name", default=None, help="Starter scene class name.")
    init_parser.add_argument(
        "--language",
        default=None,
        help="Starter scene language metadata. Defaults to en.",
    )
    init_parser.add_argument(
        "--image-tag",
        default=None,
        help="Runtime image tag. Defaults to manim-studio:local.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite generated files in an existing non-empty directory.",
    )

    verify_parser = project_subparsers.add_parser(
        "verify",
        help="Verify the Docker runtime for a generated external project.",
    )
    verify_parser.add_argument("path", help="Generated external project directory.")
    verify_parser.add_argument(
        "--render",
        action="store_true",
        help="Also run a draft render and confirm a host-visible artifact.",
    )

    session_parser = subparsers.add_parser(
        "session",
        help="Create and maintain interactive movie sessions.",
    )
    session_subparsers = session_parser.add_subparsers(
        dest="session_command",
        required=True,
    )
    session_start_parser = session_subparsers.add_parser(
        "start",
        help="Create a registered empty-slate scene for interactive movie building.",
    )
    session_start_parser.add_argument(
        "--title",
        default="Interactive Movie",
        help="Human-readable movie session title.",
    )
    session_start_parser.add_argument(
        "--deck-id",
        default="interactive",
        help="Deck ID for the generated scene. Defaults to interactive.",
    )
    session_start_parser.add_argument("--scene-id", default=None, help="Scene ID.")
    session_start_parser.add_argument("--class-name", default=None, help="Scene class name.")
    session_start_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to create the session in. Defaults to the current directory.",
    )
    session_start_parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG_PATH,
        help=f"Catalog file path. Defaults to {DEFAULT_CATALOG_PATH}.",
    )

    session_inspect_parser = session_subparsers.add_parser(
        "inspect",
        help="Inspect an interactive movie session ledger.",
    )
    session_inspect_parser.add_argument("session_id", help="Movie session ID.")
    session_inspect_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to inspect from. Defaults to the current directory.",
    )

    session_accept_parser = session_subparsers.add_parser(
        "accept",
        help="Apply an approved staged proposal and save it as an accepted movie step.",
    )
    session_accept_parser.add_argument("session_id", help="Movie session ID.")
    session_accept_parser.add_argument("proposal_id", help="Staged proposal ID.")
    session_accept_parser.add_argument("--note", default="", help="Short acceptance note.")
    session_accept_parser.add_argument(
        "--confirm",
        default="accept",
        help="Must be accept. Defaults to accept.",
    )
    session_accept_parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root to accept into. Defaults to the current directory.",
    )
    session_accept_parser.add_argument(
        "--builds-root",
        default="builds",
        help="Build output root. Defaults to builds.",
    )

    authoring_parser = subparsers.add_parser(
        "authoring",
        help="Run controller-backed interactive authoring sessions.",
    )
    authoring_subparsers = authoring_parser.add_subparsers(
        dest="authoring_command",
        required=True,
    )
    authoring_start_parser = authoring_subparsers.add_parser(
        "start",
        help="Create a registered authoring session.",
    )
    authoring_start_parser.add_argument("--title", default="Interactive Movie")
    authoring_start_parser.add_argument("--deck-id", default="interactive")
    authoring_start_parser.add_argument("--scene-id", default=None)
    authoring_start_parser.add_argument("--class-name", default=None)
    authoring_start_parser.add_argument("--language", default=None)
    authoring_start_parser.add_argument("--repo-root", default=None)
    authoring_start_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_start_parser.add_argument("--json", action="store_true")

    authoring_status_parser = authoring_subparsers.add_parser(
        "status",
        help="Show compact authoring-session status.",
    )
    authoring_status_parser.add_argument("session_id")
    authoring_status_parser.add_argument("--repo-root", default=None)
    authoring_status_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_status_parser.add_argument("--json", action="store_true")

    authoring_list_parser = authoring_subparsers.add_parser(
        "list",
        help="List compact authoring sessions.",
    )
    authoring_list_parser.add_argument("--repo-root", default=None)
    authoring_list_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_list_parser.add_argument("--json", action="store_true")

    authoring_append_parser = authoring_subparsers.add_parser(
        "append",
        help="Create a semantic append-next-step proposal.",
    )
    authoring_append_parser.add_argument("session_id")
    authoring_append_parser.add_argument("--body", required=True, help="Python body to append inside construct().")
    authoring_append_parser.add_argument("--title", default="Next step")
    authoring_append_parser.add_argument("--rationale", default="")
    authoring_append_parser.add_argument("--repo-root", default=None)
    authoring_append_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_append_parser.add_argument("--builds-root", default="builds")
    authoring_append_parser.add_argument("--json", action="store_true")

    authoring_discover_parser = authoring_subparsers.add_parser(
        "discover",
        help="Discover the newest actionable proposal for a session.",
    )
    authoring_discover_parser.add_argument("session_id")
    authoring_discover_parser.add_argument("--repo-root", default=None)
    authoring_discover_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_discover_parser.add_argument("--builds-root", default="builds")
    authoring_discover_parser.add_argument("--json", action="store_true")

    authoring_preview_parser = authoring_subparsers.add_parser(
        "preview",
        help="Preview a staged proposal without changing canonical source.",
    )
    authoring_preview_parser.add_argument("session_id")
    authoring_preview_parser.add_argument("proposal_id", nargs="?")
    authoring_preview_parser.add_argument("--repo-root", default=None)
    authoring_preview_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_preview_parser.add_argument("--builds-root", default="builds")
    authoring_preview_parser.add_argument("--json", action="store_true")

    authoring_accept_parser = authoring_subparsers.add_parser(
        "accept",
        help="Validate, render, and accept a staged authoring proposal.",
    )
    authoring_accept_parser.add_argument("session_id")
    authoring_accept_parser.add_argument("proposal_id", nargs="?")
    authoring_accept_parser.add_argument("--note", default="")
    authoring_accept_parser.add_argument("--confirm", default="accept")
    authoring_accept_parser.add_argument("--repo-root", default=None)
    authoring_accept_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_accept_parser.add_argument("--builds-root", default="builds")
    authoring_accept_parser.add_argument("--json", action="store_true")

    authoring_reject_parser = authoring_subparsers.add_parser(
        "reject",
        help="Reject the active proposal and return to accepted source.",
    )
    authoring_reject_parser.add_argument("session_id")
    authoring_reject_parser.add_argument("proposal_id", nargs="?")
    authoring_reject_parser.add_argument("--repo-root", default=None)
    authoring_reject_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_reject_parser.add_argument("--json", action="store_true")

    authoring_revise_parser = authoring_subparsers.add_parser(
        "revise",
        help="Request a distinct proposal revision with feedback.",
    )
    authoring_revise_parser.add_argument("session_id")
    authoring_revise_parser.add_argument("--feedback", required=True)
    authoring_revise_parser.add_argument("proposal_id", nargs="?")
    authoring_revise_parser.add_argument("--repo-root", default=None)
    authoring_revise_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_revise_parser.add_argument("--json", action="store_true")

    for command_name, help_text in (
        ("pause", "Pause an authoring session."),
        ("resume", "Resume an authoring session."),
        ("finish", "Validate and draft-render the accepted session scene."),
    ):
        session_action_parser = authoring_subparsers.add_parser(command_name, help=help_text)
        session_action_parser.add_argument("session_id")
        session_action_parser.add_argument("--repo-root", default=None)
        session_action_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
        session_action_parser.add_argument("--builds-root", default="builds")
        session_action_parser.add_argument("--json", action="store_true")

    for command_name, help_text in (
        ("live-start", "Start local live preview."),
        ("live-restart", "Restart local live preview."),
        ("live-stop", "Stop local live preview."),
    ):
        live_action_parser = authoring_subparsers.add_parser(command_name, help=help_text)
        live_action_parser.add_argument("session_id")
        live_action_parser.add_argument("--repo-root", default=None)
        live_action_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
        live_action_parser.add_argument("--json", action="store_true")

    authoring_rpc_parser = authoring_subparsers.add_parser(
        "rpc",
        help="Run a local JSON-lines authoring protocol on stdio.",
    )
    authoring_rpc_parser.add_argument("--repo-root", default=None)
    authoring_rpc_parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH)
    authoring_rpc_parser.add_argument("--builds-root", default="builds")

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
    if args.command == 'research':
        from manim_studio.research_cli import rpc_loop
        return rpc_loop(Path(args.repo_root or Path.cwd()).resolve())

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

    if args.command == "live":
        return run_live(
            args.target,
            args.beat,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            live_root=args.live_root,
            diagnose=args.diagnose,
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

    if args.command == "export":
        return run_export(
            args.deck,
            args.format,
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

    if args.command == "project" and args.project_command == "init":
        return run_project_init(
            args.path,
            args.name,
            deck_id=args.deck_id,
            scene_id=args.scene_id,
            class_name=args.class_name,
            language=args.language,
            image_tag=args.image_tag,
            force=args.force,
        )

    if args.command == "project" and args.project_command == "verify":
        return run_project_verify(args.path, render=args.render)

    if args.command == "session" and args.session_command == "start":
        return run_session_start(
            args.title,
            args.deck_id,
            scene_id=args.scene_id,
            class_name=args.class_name,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
        )

    if args.command == "session" and args.session_command == "inspect":
        return run_session_inspect(args.session_id, repo_root=args.repo_root)

    if args.command == "session" and args.session_command == "accept":
        return run_session_accept(
            args.session_id,
            args.proposal_id,
            note=args.note,
            confirm=args.confirm,
            repo_root=args.repo_root,
            builds_root=args.builds_root,
        )

    if args.command == "authoring" and args.authoring_command == "start":
        return run_authoring_start(
            args.title,
            args.deck_id,
            scene_id=args.scene_id,
            class_name=args.class_name,
            language=args.language,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "status":
        return run_authoring_status(
            args.session_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "list":
        return run_authoring_list(
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "append":
        return run_authoring_append(
            args.session_id,
            args.body,
            args.title,
            args.rationale,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "discover":
        return run_authoring_session_action(
            args.authoring_command,
            args.session_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "preview":
        return run_authoring_preview(
            args.session_id,
            args.proposal_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "revise":
        return run_authoring_revise(
            args.session_id,
            args.feedback,
            args.proposal_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command in {"pause", "resume", "finish"}:
        return run_authoring_session_action(
            args.authoring_command,
            args.session_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "accept":
        return run_authoring_accept(
            args.session_id,
            args.proposal_id,
            note=args.note,
            confirm=args.confirm,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "reject":
        return run_authoring_reject(
            args.session_id,
            args.proposal_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command in {
        "live-start",
        "live-restart",
        "live-stop",
    }:
        return run_authoring_live_action(
            args.authoring_command,
            args.session_id,
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            json_output=args.json,
        )

    if args.command == "authoring" and args.authoring_command == "rpc":
        return run_authoring_rpc(
            repo_root=args.repo_root,
            catalog_path=args.catalog,
            builds_root=args.builds_root,
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
