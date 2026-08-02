Manim Studio
============

Manim Studio is a local, reproducible workspace for building educational
presentations, animations, and interactive slide decks with Manim Community and
Manim Slides.

The project is in an early but working foundation stage. It includes a
registered scene catalog, the `studio` CLI, render profiles, isolated build
directories, named beats for targeted iteration, a small reusable Manim Kit, and
a local MCP server that exposes safe project services to MCP clients.

Documentation
-------------

The canonical documentation is published with GitHub Pages:

https://alonshoa.github.io/Manim-Studio/

Useful starting points:

- [Installation](docs/getting-started/installation.md)
- [Quick Start](docs/getting-started/quick-start.md)
- [External Projects](docs/getting-started/external-projects.md)
- [Project Model](docs/concepts/project-model.md)
- [CLI Reference](docs/reference/cli.md)
- [MCP Overview](docs/mcp/index.md)
- [Contributing](docs/contributing/development.md)

Quick Start
-----------

Build the reusable runtime image:

```bash
docker build --target runtime -t manim-studio:local .
```

For local non-container development, use Python 3.11 or newer and install the
project in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Check the environment and catalog:

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

Inspect the generated build:

```bash
studio inspect <build-id>
```

Common Workflows
----------------

Render a named beat:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Build a registered deck:

```bash
studio build examples --profile review
```

Export an all-slides deck to PowerPoint:

```bash
studio export <all-slide-deck> --format pptx --profile final
```

Run Studio against an external Manim project mounted at `/workspace`:

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio list
```

Generated external projects default to `manim-studio:local` and can be pointed
at another locally available image when needed:

```bash
studio project init ./demo --name "Demo Project" --image-tag manim-studio:local
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

Tests
-----

Run tests from the repository root:

```bash
pytest tests -q
```

If the package is not installed in the current shell, use:

```powershell
$env:PYTHONPATH='src'; pytest tests -q
```

Build the documentation locally:

```bash
python -m pip install -r requirements-docs.txt
mkdocs build --strict
```

Current Boundaries
------------------

Still planned or intentionally unsupported:

- HTML, PDF, ZIP, and mixed Manim/non-slide deck export
- visual regression checks beyond review-frame/contact-sheet artifacts
- cloud rendering, distributed workers, or GPU/OpenGL as a default workflow
- a YAML-only animation language
- fully autonomous scene editing through MCP
- unrestricted shell access through MCP
