Manim Studio
============

Manim Studio is a local, reproducible workspace for building educational
presentations, animations, and interactive slide decks with Manim Community and
manim-slides.

The project is in an early but working foundation stage. It now has a registered
scene catalog, a Studio CLI, render profiles, isolated build directories, named
beats for targeted iteration, a small reusable Manim Kit, and a local MCP server
that exposes the same project services to MCP clients.

Current Status
--------------

Implemented:

- Reusable local Docker runtime based on `manimcommunity/manim:v0.20.1`.
- VS Code devcontainer derived from the same runtime image definition.
- Pinned Python dependencies for Manim, manim-slides, PyYAML, and MCP.
- Five registered pilot scenes in `catalog/scenes.yaml`:
  - `examples/square_to_circle`
  - `examples/basic_slide`
  - `matrix_work/vectors_ab_to_v`
  - `matrix_work/parametric_curve_3d`
  - `losses/binary_cross_entropy`
- `studio` CLI commands:
  - `studio doctor`
  - `studio list`
  - `studio validate <deck-or-scene>`
  - `studio catalog validate`
  - `studio beats <deck>/<scene>`
  - `studio render <deck>/<scene> --profile draft`
  - `studio render <deck>/<scene> --beat <beat-id>`
  - `studio build <deck> --profile review`
  - `studio inspect <build-id>`
- Render profiles:
  - `draft`: low-quality fast render for iteration.
  - `review`: medium-quality render with smoke render and review artifacts.
  - `final`: high-quality render path for delivery-oriented output.
- Isolated build directories under `builds/`, with manifests, command metadata,
  environment metadata, logs, beat metadata, and collected artifacts.
- Named beat discovery through `self.beat(...)` calls and section-aware beat
  rendering through Manim sections.
- `manim_kit` helpers for themes, Hebrew text, RTL columns, panels, slide bases,
  and beat support.
- `manim-mcp` local stdio server with resources and tools for catalog, scene,
  validation, render, build, log, artifact, and staged patch workflows.
- Safe staged MCP scene edits under `builds/staged/<proposal_id>/workspace`,
  with inspectable diffs, staged validation, staged draft renders, and explicit
  apply checks before canonical scene files are changed.
- First Manim-specific skill contract for render-debugging assistance, starting
  with conservative failed-render-to-patch proposals for supported NameError
  repairs.
- Unit tests covering catalog handling, validation, profiles, CLI behavior,
  build metadata, beat discovery, Manim Kit exports, and MCP services.

Still planned or intentionally unsupported:

- Full deck export to HTML, PPTX, or other delivery formats.
- Visual regression checks beyond review-frame/contact-sheet artifacts.
- Cloud rendering, distributed workers, or GPU/OpenGL as a default workflow.
- A YAML-only animation language.
- Fully autonomous scene editing through MCP.
- Unrestricted shell access through MCP.

Quick Start
-----------

Build the reusable runtime image:

```bash
docker build --target runtime -t manim-studio:local .
```

Open the repository in VS Code and run **Dev Containers: Reopen in Container**.
The devcontainer installs the package in editable mode and runs `studio doctor`
as its post-create check.

For local non-container development, use Python 3.11 or newer and install the
project in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Check the environment:

```bash
studio doctor
studio doctor --catalog
```

Inspect registered content:

```bash
studio list
studio beats matrix_work/vectors_ab_to_v
```

Render a scene:

```bash
studio render examples/square_to_circle --profile draft
```

Render a named beat:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Build a registered deck:

```bash
studio build examples --profile review
```

Inspect a build:

```bash
studio inspect <build-id>
```

Run Studio against an external Manim project mounted at `/workspace`:

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio list
```

Run the MCP stdio server through the runtime container without allocating a TTY:

```bash
docker run --rm -i \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  -e MANIM_STUDIO_REPO_ROOT=/workspace \
  manim-studio:local \
  manim-mcp
```

Run tests from the repository root:

```bash
pytest tests -q
```

If the package is not installed in the current shell, use:

```powershell
$env:PYTHONPATH='src'; pytest tests -q
```

On the current Windows host shell, plain `pytest tests -q` does not collect
because the package is not installed/importable and the host interpreter is
Python 3.10 while the project declares Python 3.11+. With `PYTHONPATH=src`, the
suite currently passes with 64 tests passed and 7 skipped.

Project Concepts
----------------

Deck

A collection of related scenes that form a presentation or teaching unit.
Registered deck IDs currently include `examples`, `matrix_work`, and `losses`.

Scene

A normal Manim Python class registered in the catalog. Scenes may use `Scene`,
`MovingCameraScene`, `ThreeDScene`, `Slide`, or another suitable Manim base
class.

Beat

A named conceptual segment inside a scene. Slide-based scenes can call
`self.beat("beat_id", label="Human label")` to create a discoverable checkpoint
and make targeted iteration easier.

Build

A single rendering attempt with an isolated output directory. Scene builds store
metadata such as command arguments, environment details, preflight results,
stdout/stderr logs, manifests, beat metadata, and artifacts.

Artifact

Any output produced by a build, such as MP4 videos, PNG review frames, contact
sheets, HTML files, captions, logs, or metadata files.

Manim Kit

The `manim_kit` package is the shared component layer for recurring
presentation needs. It currently includes theme values, Hebrew/RTL helpers,
panel helpers, slide base classes, and beat helpers. It is intentionally small
and Python-native; it is not a replacement for ordinary Manim code.

Repository Structure
--------------------

```text
Manim-Studio/
|-- .devcontainer/            # Reproducible local development environment
|-- baselines/                # Curated baseline review notes and snapshots
|-- builds/                   # Local isolated render outputs, ignored by Git
|-- catalog/                  # Registered deck and scene metadata
|-- decks/                    # Presentation content and migrated pilot scenes
|-- docs/                     # Environment, conventions, pilot, kit, and MCP docs
|-- examples/                 # Minimal Manim and manim-slides smoke scenes
|-- media/                    # Local Manim output, ignored by Git
|-- slides/                   # Local manim-slides output, ignored by Git
|-- src/
|   |-- manim_kit/            # Reusable visual and layout components
|   |-- manim_mcp/            # Local MCP server and service envelope
|   `-- manim_studio/         # CLI, catalog, validation, profiles, builds
|-- tests/                    # Unit and service tests
|-- Dockerfile                # Runtime and devcontainer image targets
|-- pyproject.toml
`-- README.md
```

CLI And Package Entry Points
----------------------------

`pyproject.toml` exposes two console scripts:

```text
studio = manim_studio.cli:main
manim-mcp = manim_mcp.server:main
```

The `studio` CLI is the normal local workflow entry point for catalog
inspection, validation, rendering, deck builds, beat discovery, and build
inspection.

The `manim-mcp` command starts a local MCP stdio server for clients that should
operate through structured project services instead of unrestricted shell
commands.

MCP Server
----------

The MCP server is implemented in `src/manim_mcp` and documented in
`docs/mcp.md`. It reuses the same catalog, validation, beat, render, build, log,
and artifact services as the CLI.

Resources include:

- `manim-studio://conventions`
- `manim-studio://catalog`
- `manim-studio://scene/{deck_id}/{scene_id}`
- `manim-studio://build/{build_id}/manifest`
- `manim-studio://build/{build_id}/artifacts`
- `manim-studio://build/{build_id}/log/{stream}`

Tools include:

- `list_decks`
- `get_scene_context`
- `validate_scene`
- `render_scene`
- `render_beat`
- `build_deck`
- `get_build_log`
- `get_artifacts`
- `propose_scene_patch`
- `inspect_scene_patch`
- `validate_scene_patch`
- `render_scene_patch`
- `apply_scene_patch`
- `propose_render_debug_patch`
- `export_deck`

All MCP responses use a structured envelope with `ok`, `status`, `data`, and
`error`. `export_deck` is present for surface compatibility but currently
returns `unsupported` because full export services are not implemented yet.

Design Principles
-----------------

Python remains the source of truth.

Scenes are written as normal Manim code. Metadata, scene plans, and future YAML
specifications are supporting layers for documentation, orchestration, and AI
assistance.

Build the studio before adding deeper automation.

The core workflow is:

```text
scene code
-> validation
-> draft render
-> review artifacts
-> final render/export
```

Migrate selectively.

Existing Manim scenes should be imported gradually as pilot examples. The
project should continue proving support for real presentation needs: Hebrew and
RTL text, manim-slides checkpoints, complex transforms, long scenes, camera
movement, updaters, and 3D scenes where useful.

Stay local-first and reproducible.

The supported paths are the reusable local runtime container and the VS Code
devcontainer derived from it. The project should remain usable without cloud
infrastructure or remote render workers.

Keep MCP safe.

MCP tools expose structured operations such as scene inspection, validation,
rendering, beat rendering, build inspection, log reading, and artifact listing.
They do not expose unrestricted shell access or direct scene-editing
operations.

Further Documentation
---------------------

- `docs/environment.md`: supported devcontainer, pinned runtime, first-run
  checks, external project workflow, and build artifact behavior.
- `docs/compose.external.yml`: copyable Compose service for external projects.
- `docs/conventions.md`: repository conventions for scenes, catalog metadata,
  rendering, and review.
- `docs/pilot_scenes.md`: implementation notes for migrated pilot scenes.
- `docs/manim_kit.md`: public Manim Kit helpers and contribution rules.
- `docs/mcp.md`: local MCP server configuration, resources, tools, envelopes,
  and safety model.
