# Installation

Manim Studio supports three local development paths:

- reusable Docker runtime for this repo or external Manim projects
- VS Code devcontainer for contributors
- local editable Python install for environments that already have the render
  toolchain

Python source remains the source of truth in every path.

## Runtime Image

Build the local runtime image from the repository root:

```bash
docker build --target runtime -t manim-studio:local .
```

The runtime image:

- uses `manimcommunity/manim:v0.20.1` as its base
- installs FFmpeg, TeX Live, `dvisvgm`, fontconfig, DejaVu fonts, and Noto fonts
- installs Manim Studio into `/opt/venv`
- sets `/workspace` as the mounted external project root
- exposes `studio` and `manim-mcp` on `PATH`

Linux users can match host ownership at build time:

```bash
docker build \
  --target runtime \
  --build-arg USER_UID="$(id -u)" \
  --build-arg USER_GID="$(id -g)" \
  -t manim-studio:local .
```

The defaults are `1000:1000`. On Docker Desktop for Windows and macOS,
bind-mount ownership is mediated by Docker Desktop.

## Devcontainer

Install these host tools:

- VS Code
- Docker Desktop
- VS Code Dev Containers extension
- WSL 2 on Windows hosts, with the repository cloned inside the Linux
  filesystem when possible

Open the repository in VS Code and run **Dev Containers: Reopen in Container**.
The devcontainer builds the `dev` target from the root `Dockerfile`, installs
the package in editable mode, and runs `studio doctor` after creation.

## Local Python Install

For non-container development, use Python 3.11 or newer:

```bash
python -m pip install -e ".[dev]"
```

This path expects the local machine to already provide compatible render
prerequisites such as Manim, Manim Slides, FFmpeg, LaTeX/XeLaTeX, `dvisvgm`, and
Hebrew-capable fonts. The Docker runtime is the supported reproducible path when
those tools are not already installed.

## Verify Installation

Run:

```bash
studio doctor
studio doctor --catalog
```

Expected checks include Python, Manim, Manim Slides, FFmpeg, LaTeX, XeLaTeX,
`dvisvgm`, and Hebrew-capable font availability. The `--catalog` option also
checks migrated scene metadata, baseline paths, render command coverage, and
font notes.
