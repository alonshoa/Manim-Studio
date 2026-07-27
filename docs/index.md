# Manim Studio

Manim Studio is a local, reproducible workspace for building educational
presentations, animations, and interactive slide decks with Manim Community and
Manim Slides.

The project is in an early but working foundation stage. It provides a
registered scene catalog, the `studio` CLI, render profiles, isolated build
directories, named beats for targeted iteration, a small reusable Manim Kit, and
a local MCP server that exposes the same project services to MCP clients.

## Who This Is For

Use Manim Studio when you want to:

- keep Manim scenes as normal Python source files
- register scenes and decks so tools can validate and render them consistently
- iterate on long scenes through named conceptual beats
- build review artifacts and delivery-oriented exports from reproducible local
  commands
- expose safe Manim project operations to MCP clients without giving them shell
  access

## Fastest Path

Build the local runtime image:

```bash
docker build --target runtime -t manim-studio:local .
```

Then inspect and render the registered examples:

```bash
studio doctor
studio list
studio render examples/square_to_circle --profile draft
studio inspect <build-id>
```

If the package is not installed in the current shell, install it locally with
Python 3.11 or newer:

```bash
python -m pip install -e ".[dev]"
```

## Current Capabilities

- Docker runtime based on `manimcommunity/manim:v0.20.1`
- VS Code devcontainer derived from the same runtime image definition
- Pinned dependencies for Manim, Manim Slides, PyYAML, MCP, and PPTX export
- Registered scene catalog in `catalog/scenes.yaml`
- `studio` commands for doctor, list, validate, beats, render, build, export,
  and inspect
- Render profiles: `draft`, `review`, and `final`
- Isolated build directories under `builds/`
- Review frames and contact sheets for review/final renders when FFmpeg can
  extract frames
- Manim Kit helpers for theme values, Hebrew/RTL text, panels, slide bases, and
  beats
- Local MCP server with safe resources, tools, staged scene edits, and render
  debugging proposals

## Not In Scope Yet

- HTML, PDF, ZIP, and mixed Manim/non-slide deck export
- Visual regression checks beyond review-frame/contact-sheet artifacts
- Cloud rendering, distributed workers, or GPU/OpenGL as the default workflow
- A YAML-only animation language
- Fully autonomous scene editing through MCP
- Unrestricted shell access through MCP

## Start Reading

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quick-start.md)
- [Project Model](concepts/project-model.md)
- [CLI Reference](reference/cli.md)
- [MCP Overview](mcp/index.md)
