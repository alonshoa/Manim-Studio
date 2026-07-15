# Environment

Manim Studio uses a local VS Code devcontainer as the supported development and
rendering environment. The container pins Manim Community and Manim Slides so a
clean clone can rebuild a known-good workspace before later catalog and render
services are added.

## Supported Host Flow

Install these host tools:

- VS Code
- Docker Desktop
- VS Code Dev Containers extension
- WSL 2 on Windows hosts, with the repository cloned inside the Linux filesystem
  when possible for better filesystem performance

Open the repository in VS Code, run **Dev Containers: Reopen in Container**, and
let the container build from `.devcontainer/Dockerfile`.

The devcontainer post-create step installs the local `studio` package into the
container virtual environment in editable mode without reinstalling dependencies,
because the pinned Manim runtime is already baked into the image.

## Pinned Runtime

The devcontainer currently pins:

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

Render the minimal Cairo scene:

```bash
manim -ql examples/basic_scene.py SquareToCircle
```

Render the minimal slide scene:

```bash
manim-slides render -ql examples/basic_slide.py BasicSlide
```

Generated output under `media/`, `slides/`, and future `builds/` directories is
local-only and ignored by Git.

Curated baseline review frames belong under `baselines/` and may be tracked.
Do not move full Manim output directories into the baseline tree.

## Out of Scope for Phase 1

This environment issue does not add cloud rendering, distributed workers, GPU or
OpenGL acceleration, the full Studio CLI, MCP tooling, or migration of the
legacy scene archive. Optional GPU/OpenGL configuration can be documented later
for specific workstations, but it is intentionally disabled in the default
container.
