# Environment

Manim Studio uses a reusable local Docker runtime for validation, rendering,
builds, Manim Kit, and the local MCP server. External Manim projects can mount
at `/workspace` and run Studio without copying their scenes into this
repository.

The VS Code devcontainer remains supported, but it now builds from the same
root `Dockerfile` as the reusable runtime.

## Runtime Image

Build the local runtime image from the Manim Studio repository root:

```bash
docker build --target runtime -t manim-studio:local .
```

The runtime image:

- uses `manimcommunity/manim:v0.20.1` as its base
- installs FFmpeg, TeX Live, `dvisvgm`, fontconfig, DejaVu fonts, and Noto fonts
- installs the packaged `manim-studio` project into `/opt/venv`
- sets `/workspace` as the mounted external project root
- exposes the `studio` and `manim-mcp` entry points on `PATH`

Run one-shot commands against an external project:

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio doctor --catalog
```

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio render demo/smoke --profile draft
```

Run the MCP stdio server without a TTY:

```bash
docker run --rm -i \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  -e MANIM_STUDIO_REPO_ROOT=/workspace \
  manim-studio:local \
  manim-mcp
```

Do not add `-t` for MCP stdio clients.

## External Project Compose

`docs/compose.external.yml` is a copyable Compose example for an external
project repository. After building `manim-studio:local`, copy that file into the
external project as `compose.yml` or adapt the service block.

Expected commands from the external project root:

```bash
docker compose run --rm studio studio doctor --catalog
docker compose run --rm studio studio list
docker compose run --rm studio studio catalog validate
docker compose run --rm studio studio render demo/smoke --profile draft
docker compose run --rm -T studio manim-mcp
```

Generated `builds/`, `media/`, `slides/`, and review artifacts are written
inside the mounted external project so the host can inspect and manage them.

## UID And GID

The runtime image accepts Linux ownership build arguments:

```bash
docker build \
  --target runtime \
  --build-arg USER_UID="$(id -u)" \
  --build-arg USER_GID="$(id -g)" \
  -t manim-studio:local .
```

The defaults are `1000:1000`, matching common Linux development users. On
Docker Desktop for Windows and macOS, bind-mount ownership is mediated by Docker
Desktop; files should remain visible and manageable from the host even when the
container user appears different inside Linux.

## Devcontainer Flow

Install these host tools:

- VS Code
- Docker Desktop
- VS Code Dev Containers extension
- WSL 2 on Windows hosts, with the repository cloned inside the Linux filesystem
  when possible for better filesystem performance

Open the repository in VS Code, run **Dev Containers: Reopen in Container**, and
let the container build the `dev` target from the root `Dockerfile`.

The devcontainer post-create step installs the local `studio` package and dev
test tools into the container virtual environment in editable mode. For local
non-container development, install the same test path with:

```bash
python -m pip install -e ".[dev]"
```

## Pinned Dependencies

The runtime currently pins:

- Base image: `manimcommunity/manim:v0.20.1`
- Python package: `manim==0.20.1`
- Python package: `manim-slides==5.6.0`

The image also installs FFmpeg, TeX Live LaTeX/XeLaTeX support, `dvisvgm`,
fontconfig, DejaVu fonts, and Noto fonts for Hebrew-capable text rendering.

## First-Run Checks

After the container is ready, run:

```bash
studio doctor
```

Expected checks include Python, Manim, Manim Slides, FFmpeg, LaTeX, XeLaTeX,
`dvisvgm`, and Hebrew-capable font availability.

To also verify migrated scene metadata, baseline paths, render command
coverage, and font notes, run:

```bash
studio doctor --catalog
```

Run the repository test suite:

```bash
pytest tests -q
```

Render the minimal Cairo scene:

```bash
manim -ql examples/basic_scene.py SquareToCircle
```

Render the minimal slide scene:

```bash
manim-slides render -ql examples/basic_slide.py BasicSlide
```

Generated output under `media/`, `slides/`, and `builds/` directories is
local-only and ignored by Git.

Curated baseline review frames belong under `baselines/` and may be tracked.
Do not move full Manim output directories into the baseline tree.

## Build Preflight And Review Artifacts

`studio render` and `studio build` write an inspectable build directory for
every selected scene. Each scene build includes the compatibility files
`result.json` and `artifacts.json`, plus a canonical `manifest.json` with
preflight issues, command context, smoke-render status, logs, override flags,
beat metadata, and artifact paths.

Review and final builds run a draft-quality smoke render before the expensive
profile render. Preflight failures stop the build unless `--force` is provided;
smoke render failures always stop review/final rendering. Successful review
renders produce representative PNG frames and `review/contact_sheet.png` when
FFmpeg can extract frames from the rendered video.

## Out of Scope

This runtime does not add cloud rendering, distributed workers, GPU/OpenGL as a
default path, image registry publication, or a full external project template.
Optional GPU/OpenGL configuration can be documented later for specific
workstations, but it is intentionally disabled in the default container.
