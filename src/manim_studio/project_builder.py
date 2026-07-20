from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_IMAGE_TAG = "manim-studio:local"
DEFAULT_SCENE_ID = "intro"
DEFAULT_LANGUAGE = "en"


class ProjectBuilderError(RuntimeError):
    """Raised when a project cannot be generated safely."""


@dataclass(frozen=True)
class ProjectOptions:
    path: Path
    name: str
    deck_id: str
    scene_id: str
    class_name: str
    language: str = DEFAULT_LANGUAGE
    image_tag: str = DEFAULT_IMAGE_TAG
    force: bool = False

    @property
    def target(self) -> str:
        return f"{self.deck_id}/{self.scene_id}"


@dataclass(frozen=True)
class ProjectCreationResult:
    root: Path
    target: str
    files_written: tuple[Path, ...]


def slugify_identifier(value: str, default: str = "project") -> str:
    words = re.findall(r"[A-Za-z0-9]+", value.lower())
    slug = "_".join(words).strip("_")
    if not slug:
        slug = default
    if slug[0].isdigit():
        slug = f"project_{slug}"
    return slug


def pascal_case(value: str, default: str = "Project") -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        return default
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append(part)
        else:
            normalized.append(part[:1].upper() + part[1:])
    result = "".join(normalized)
    if result and result[0].isdigit():
        result = f"Project{result}"
    return result or default


def default_class_name(project_name: str) -> str:
    base = pascal_case(project_name)
    if base.endswith("IntroSlide"):
        return base
    return f"{base}IntroSlide"


def default_options(
    path: Path | str,
    name: str,
    deck_id: str | None = None,
    scene_id: str | None = None,
    class_name: str | None = None,
    language: str | None = None,
    image_tag: str | None = None,
    force: bool = False,
) -> ProjectOptions:
    resolved_name = name.strip()
    if not resolved_name:
        raise ProjectBuilderError("project name cannot be empty")

    resolved_deck_id = deck_id.strip() if deck_id else slugify_identifier(resolved_name)
    resolved_scene_id = scene_id.strip() if scene_id else DEFAULT_SCENE_ID
    resolved_class_name = class_name.strip() if class_name else default_class_name(resolved_name)
    resolved_language = language.strip() if language else DEFAULT_LANGUAGE
    resolved_image_tag = image_tag.strip() if image_tag else DEFAULT_IMAGE_TAG

    _validate_identifier(resolved_deck_id, "deck_id")
    _validate_identifier(resolved_scene_id, "scene_id")
    _validate_class_name(resolved_class_name)

    return ProjectOptions(
        path=Path(path).expanduser().resolve(),
        name=resolved_name,
        deck_id=resolved_deck_id,
        scene_id=resolved_scene_id,
        class_name=resolved_class_name,
        language=resolved_language,
        image_tag=resolved_image_tag,
        force=force,
    )


def create_project(options: ProjectOptions) -> ProjectCreationResult:
    root = options.path
    if root.exists() and any(root.iterdir()) and not options.force:
        raise ProjectBuilderError(
            f"{root} is not empty; rerun with --force to overwrite generated files"
        )

    files = _render_files(options)
    written: list[Path] = []
    for relative_path, content in files:
        destination = root / relative_path
        if destination.exists() and not options.force:
            raise ProjectBuilderError(
                f"{destination} already exists; rerun with --force to overwrite it"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
        written.append(destination)

    return ProjectCreationResult(root=root, target=options.target, files_written=tuple(written))


def docker_available() -> bool:
    return shutil.which("docker") is not None


def docker_image_exists(image_tag: str) -> bool:
    completed = subprocess.run(
        ["docker", "image", "inspect", image_tag],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def build_runtime_image(image_tag: str, studio_root: Path) -> int:
    completed = subprocess.run(
        ["docker", "build", "--target", "runtime", "-t", image_tag, str(studio_root)],
        check=False,
    )
    return completed.returncode


def run_validation(root: Path, target: str) -> int:
    commands = (
        ["docker", "compose", "run", "--rm", "studio", "studio", "doctor", "--catalog"],
        ["docker", "compose", "run", "--rm", "studio", "studio", "list"],
        ["docker", "compose", "run", "--rm", "studio", "studio", "validate", target],
    )
    for command in commands:
        print(f"\n> {' '.join(command)}")
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_path = args.path or _prompt_required("Project path")
    project_name = args.name or _prompt_required("Project name")

    try:
        options = default_options(
            path=project_path,
            name=project_name,
            deck_id=args.deck_id,
            scene_id=args.scene_id,
            class_name=args.class_name,
            language=args.language,
            image_tag=args.image_tag,
            force=args.force,
        )
        result = create_project(options)
    except ProjectBuilderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created Manim Studio project: {result.root}")
    print(f"Registered starter scene: {result.target}")
    print(f"Files written: {len(result.files_written)}")

    if not docker_available():
        print("\nDocker was not found on PATH; skipping runtime validation.")
        _print_next_steps(result)
        return 0

    image_ready = docker_image_exists(options.image_tag)
    if not image_ready:
        print(f"\nDocker image not found: {options.image_tag}")
        should_build = args.yes or _confirm("Build the Manim Studio runtime image now?")
        if should_build:
            studio_root = Path(args.studio_root).expanduser().resolve()
            build_exit = build_runtime_image(options.image_tag, studio_root)
            if build_exit != 0:
                print("Runtime image build failed; skipping validation.", file=sys.stderr)
                _print_next_steps(result)
                return build_exit
            image_ready = True
        else:
            print("Runtime image build skipped; skipping validation.")

    if image_ready:
        validation_exit = run_validation(result.root, result.target)
        if validation_exit != 0:
            print("\nValidation failed. The project files were still generated.", file=sys.stderr)
            _print_next_steps(result)
            return validation_exit

    _print_next_steps(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="new-manim-project",
        description="Create a Docker/MCP-ready external Manim Studio slide project.",
    )
    parser.add_argument("--path", "-Path", dest="path", default=None)
    parser.add_argument("--name", "-Name", dest="name", default=None)
    parser.add_argument("--deck-id", "-DeckId", dest="deck_id", default=None)
    parser.add_argument("--scene-id", "-SceneId", dest="scene_id", default=None)
    parser.add_argument("--class-name", "-ClassName", dest="class_name", default=None)
    parser.add_argument("--language", "-Language", dest="language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--image-tag", "-ImageTag", dest="image_tag", default=DEFAULT_IMAGE_TAG)
    parser.add_argument("--yes", "-Yes", action="store_true")
    parser.add_argument("--force", "-Force", action="store_true")
    parser.add_argument(
        "--studio-root",
        default=Path.cwd(),
        help=argparse.SUPPRESS,
    )
    return parser


def _prompt_required(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value


def _confirm(question: str) -> bool:
    answer = input(f"{question} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _print_next_steps(result: ProjectCreationResult) -> None:
    print("\nNext commands:")
    print(r"  tools\render-draft.cmd")
    print(r"  tools\start-mcp.cmd")


def _validate_identifier(value: str, label: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise ProjectBuilderError(
            f"{label} must start with a letter and contain only ASCII letters, digits, _ or -"
        )


def _validate_class_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ProjectBuilderError(
            "class_name must be a valid ASCII Python identifier"
        )


def _render_files(options: ProjectOptions) -> tuple[tuple[Path, str], ...]:
    return tuple(
        (Path(path), content)
        for path, content in (
            (".gitignore", _gitignore()),
            ("README.md", _readme(options)),
            ("compose.yml", _compose(options)),
            ("mcp.manim-studio.json", _mcp_json(options)),
            ("catalog/scenes.yaml", _catalog(options)),
            (f"decks/{options.deck_id}/{options.scene_id}.py", _scene(options)),
            (f"baselines/{options.deck_id}/{options.scene_id}/README.md", _baseline_readme(options)),
            ("docs/conventions.md", _conventions(options)),
            ("tools/studio.cmd", _studio_cmd()),
            ("tools/start-mcp.cmd", _ps_cmd_wrapper("start-mcp.ps1")),
            ("tools/start-mcp.ps1", _start_mcp_ps1()),
            ("tools/stop-mcp.cmd", _ps_cmd_wrapper("stop-mcp.ps1")),
            ("tools/stop-mcp.ps1", _stop_mcp_ps1()),
            ("tools/validate.cmd", _validate_cmd(options)),
            ("tools/render-draft.cmd", _render_draft_cmd(options)),
        )
    )


def _gitignore() -> str:
    return """# Python
__pycache__/
*.py[cod]
.pytest_cache/

# Local environments
.venv/
venv/
env/
.env
.env.*

# Manim Studio generated output
builds/
media/
slides/

# Logs and OS/editor noise
*.log
*.tmp
.DS_Store
Thumbs.db
"""


def _readme(options: ProjectOptions) -> str:
    return f"""# {options.name}

External Manim Studio project generated for Docker-based rendering and MCP access.

## Validate

```powershell
tools\\validate.cmd
```

## Render Draft

```powershell
tools\\render-draft.cmd
```

## Start MCP

Use `mcp.manim-studio.json` as a generic MCP client snippet, or run the stdio
server manually:

```powershell
tools\\start-mcp.cmd
```

The MCP process is foreground stdio. Most MCP clients start and stop it
themselves.

## Registered Scene

- Target: `{options.target}`
- Source: `decks/{options.deck_id}/{options.scene_id}.py`
- Class: `{options.class_name}`
"""


def _compose(options: ProjectOptions) -> str:
    return f"""services:
  studio:
    image: {options.image_tag}
    working_dir: /workspace
    environment:
      MANIM_STUDIO_REPO_ROOT: /workspace
    volumes:
      - .:/workspace
"""


def _mcp_json(options: ProjectOptions) -> str:
    project_path = _docker_mount_path(options.path)
    payload = {
        "mcpServers": {
            "manim-studio": {
                "command": "docker",
                "args": [
                    "run",
                    "--rm",
                    "-i",
                    "-v",
                    f"{project_path}:/workspace",
                    "-w",
                    "/workspace",
                    "-e",
                    "MANIM_STUDIO_REPO_ROOT=/workspace",
                    options.image_tag,
                    "manim-mcp",
                ],
            }
        }
    }
    return json.dumps(payload, indent=2) + "\n"


def _catalog(options: ProjectOptions) -> str:
    return f"""version: 1
scenes:
  - deck_id: {options.deck_id}
    scene_id: {options.scene_id}
    source_path: decks/{options.deck_id}/{options.scene_id}.py
    class_name: {options.class_name}
    base_scene_type: Slide
    renderer: manim-slides
    language: {options.language}
    description: {_yaml_string(f"Starter slide scene for {options.name}.")}
    asset_notes: "No external assets."
    font_notes: "Uses DejaVu Sans from the Manim Studio runtime."
    parameter_notes: "Title, subtitle, and bullet text are safe to edit."
    render_command: "manim-slides render -ql decks/{options.deck_id}/{options.scene_id}.py {options.class_name}"
    baseline_path: baselines/{options.deck_id}/{options.scene_id}
    migration_notes: "Generated by the Manim Studio external project builder."
"""


def _scene(options: ProjectOptions) -> str:
    return f'''from manim import DOWN, FadeIn, FadeOut, LEFT, Text, VGroup
from manim_kit import BeatMixin
from manim_slides import Slide


class {options.class_name}(BeatMixin, Slide):
    def construct(self):
        self.beat("title", label="Title")
        title = Text({_py_string(options.name)}, font="DejaVu Sans")
        subtitle = Text("Manim Studio slide project", font="DejaVu Sans").scale(0.55)
        subtitle.next_to(title, DOWN)

        self.play(FadeIn(title))
        self.next_slide()

        self.beat("overview", label="Overview")
        bullets = VGroup(
            Text("Docker runtime", font="DejaVu Sans").scale(0.45),
            Text("Registered scene catalog", font="DejaVu Sans").scale(0.45),
            Text("MCP-ready project tools", font="DejaVu Sans").scale(0.45),
        ).arrange(DOWN, aligned_edge=LEFT)
        bullets.next_to(subtitle, DOWN)

        self.play(FadeIn(subtitle), FadeIn(bullets))
        self.next_slide()

        self.beat("outro", label="Outro")
        self.play(FadeOut(title), FadeOut(subtitle), FadeOut(bullets))
        self.next_slide()
'''


def _baseline_readme(options: ProjectOptions) -> str:
    return f"""# {options.name} Intro Baseline

Render command:

```bash
manim-slides render -ql decks/{options.deck_id}/{options.scene_id}.py {options.class_name}
```

Copy curated review frames here after rendering when you want tracked baselines.
"""


def _conventions(options: ProjectOptions) -> str:
    return f"""# {options.name} Conventions

This is an external Manim Studio project. Python scene files are the source of
truth, and `catalog/scenes.yaml` registers scenes for Studio CLI and MCP tools.

- Keep deck-specific scenes under `decks/{options.deck_id}/`.
- Keep generated render output in `builds/`, `media/`, and `slides/`.
- Use `self.beat(...)` for stable review checkpoints in slide scenes.
- Validate with `tools\\validate.cmd` before relying on MCP rendering.
"""


def _studio_cmd() -> str:
    return """@echo off
setlocal
pushd "%~dp0.." >nul
docker compose run --rm studio studio %*
set "exit_code=%ERRORLEVEL%"
popd >nul
exit /b %exit_code%
"""


def _ps_cmd_wrapper(script_name: str) -> str:
    return f"""@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0{script_name}" %*
exit /b %ERRORLEVEL%
"""


def _start_mcp_ps1() -> str:
    return """$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
    docker compose run --rm -T studio manim-mcp
}
finally {
    Pop-Location
}
"""


def _stop_mcp_ps1() -> str:
    return """$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
    docker compose down --remove-orphans
}
finally {
    Pop-Location
}
"""


def _validate_cmd(options: ProjectOptions) -> str:
    return f"""@echo off
setlocal
call "%~dp0studio.cmd" doctor --catalog
if errorlevel 1 exit /b %ERRORLEVEL%
call "%~dp0studio.cmd" list
if errorlevel 1 exit /b %ERRORLEVEL%
call "%~dp0studio.cmd" validate {options.target}
exit /b %ERRORLEVEL%
"""


def _render_draft_cmd(options: ProjectOptions) -> str:
    return f"""@echo off
setlocal
call "%~dp0studio.cmd" render {options.target} --profile draft %*
exit /b %ERRORLEVEL%
"""


def _docker_mount_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _py_string(value: str) -> str:
    return json.dumps(value)


def _yaml_string(value: str) -> str:
    return json.dumps(value)


if __name__ == "__main__":
    raise SystemExit(main())
