# Manim Studio

Manim Studio is a local, reproducible workspace for building educational
presentations, animations, and interactive slide decks with Manim Community and
Manim Slides.

It keeps your scenes as normal Python code while adding structure around the
rendering workflow: registered scenes and decks, reproducible render profiles,
isolated builds, named beats, reusable presentation helpers, and safe MCP
services.

## Why Manim Studio?

Manim already provides the animation engine. Manim Slides provides slide-based
presentation workflows. Manim Studio adds the project-level structure needed
to manage those scenes consistently as a larger presentation or teaching
workspace.

| | Manim | Manim Slides | Manim Studio |
| --- | --- | --- | --- |
| Python-based scenes | Yes | Yes | Yes |
| Mathematical and educational animation | Yes | Yes | Yes |
| Slide checkpoints | — | Yes | Yes, through Manim Slides |
| Registered scene catalog | — | — | Yes |
| Render profiles | — | — | Yes |
| Isolated build directories | — | — | Yes |
| Named beats for targeted iteration | — | — | Yes |
| Shared presentation helpers | — | — | Manim Kit |
| Project services for MCP clients | — | — | Yes |
| PPTX export workflow | — | Through supported tooling | Yes |

Manim Studio is therefore not a replacement for Manim or Manim Slides, and it
is not a separate animation language. Your scenes remain ordinary Manim Python
code.

## What the workflow looks like

A typical Studio workflow connects the project catalog to the rendering and
delivery artifacts:

```text
                 ┌──────────────┐
                 │    Catalog   │
                 │ scenes/decks │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │  Studio CLI  │
                 │ list/render  │
                 │ build/export │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │   Profiles   │
                 │ draft/review │
                 │    /final    │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │    Builds    │
                 │ isolated run │
                 │   metadata   │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │  Artifacts   │
                 │ MP4 / PNG /  │
                 │ PPTX / logs  │
                 └──────────────┘

        Manim Kit ───────┐
                         ├──► presentation scenes
        MCP services ────┘
```

The catalog records what can be rendered. The `studio` CLI provides the main
local workflow. Profiles control the intended render level. Each operation
creates an isolated build containing metadata and generated artifacts.

## What you actually get

A registered scene can be rendered with:

```bash
studio render examples/square_to_circle --profile draft
```

A complete registered deck can be built with:

```bash
studio build examples --profile review
```

A named beat can be inspected and rendered independently:

```bash
studio beats matrix_work/vectors_ab_to_v
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Completed builds can be inspected with:

```bash
studio inspect <build-id>
```

Artifacts produced by builds can include:

- MP4 videos
- PNG review frames
- contact sheets
- PPTX files
- logs
- metadata files

Builds are stored under `builds/`, while generated Manim output such as
`media/` and `slides/` remains local-only.

## The project model

Studio organizes normal Manim Python code into a small project model:

- **Deck** — a collection of related scenes forming a presentation or teaching
  unit.
- **Scene** — a normal Manim Python class registered in the catalog.
- **Beat** — an optional named conceptual segment inside a scene.
- **Build** — one isolated rendering, deck build, or export attempt.
- **Artifact** — an output produced by a build.

See the [Project Model](concepts/project-model.md) documentation for the full
model.

## Manim Kit

`manim_kit` is the shared component layer for recurring presentation needs. It
currently provides:

- theme values
- Hebrew/RTL helpers
- panel helpers
- slide base classes
- beat helpers

It is intentionally small and Python-native. Scene-specific diagrams,
constants, and teaching steps remain ordinary Manim code.

See [Manim Kit](manim-kit/index.md) for details.

## MCP and automation

Manim Studio includes a local MCP stdio server that exposes safe project
services to MCP clients.

The MCP layer is intended to provide project operations without granting
unrestricted shell access.

Run it from the runtime container with:

```bash
docker run --rm -i \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  -e MANIM_STUDIO_REPO_ROOT=/workspace \
  manim-studio:local \
  manim-mcp
```

See the [MCP Overview](mcp/index.md) for the currently implemented resources
and tools.

## Examples

The repository includes registered examples covering:

- a minimal Manim Cairo scene
- a Manim Slides smoke scene
- a Hebrew/RTL vector addition presentation
- a 3D parametric curve
- a binary cross-entropy visualization

Explore the [Examples](examples/index.md) and their
[visual gallery](examples/basic-scenes.md) to see real rendered outputs and
the commands used to reproduce them.

## First run

For a new project, start with the installation and quick-start documentation:

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quick-start.md)
- [External Projects](getting-started/external-projects.md)

For the repository itself, the fastest local path is:

```bash
studio doctor
studio list
studio render examples/square_to_circle --profile draft
```

For an external project, Studio can generate a project skeleton:

```bash
studio project init ./demo --name "Demo Project"
```

Then verify it separately:

```bash
studio project verify ./demo
```

The generated project does not automatically build Docker, pull images, start
MCP, or render. A configured runtime image must already be available.

## Current maturity and boundaries

Manim Studio is an **early but working foundation**. The implemented workflow
is centered on local, reproducible rendering and project services.

The following are intentionally not presented as finished capabilities:

- HTML, PDF, ZIP, and mixed Manim/non-slide deck export
- visual regression checks beyond review-frame/contact-sheet artifacts
- cloud rendering or distributed workers
- GPU/OpenGL as the default workflow
- a YAML-only animation language
- fully autonomous scene editing through MCP
- unrestricted shell access through MCP
- a zero-dependency public installer
- automatic Codex or Claude configuration

Public bootstrap installers, automatic client configuration, and cloud
rendering remain future distribution work.

## Where to go next

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quick-start.md)
- [Examples](examples/index.md)
- [Project Model](concepts/project-model.md)
- [CLI Reference](reference/cli.md)
- [Manim Kit](manim-kit/index.md)
- [MCP Overview](mcp/index.md)
- [External Projects](getting-started/external-projects.md)