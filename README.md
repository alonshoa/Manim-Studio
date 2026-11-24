Manim Studio
============

Manim Studio is a local, reproducible workspace for building educational
presentations, animations, and interactive slide decks with Manim Community and
Manim Slides.

Version **0.1.0** combines interactive authoring and movie sessions, a VS Code
extension, native Windows installation, CLI/MCP project services, and optional local
research capture. Python scenes remain the source of truth.

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

Quick Start — Windows
---------------------

1. Download a verified Windows installation package from a successful
   [Windows package workflow](https://github.com/alonshoa/Manim-Studio/actions/workflows/windows-research-package.yml).
   Extract it and run `Start-Setup.cmd` as administrator under your normal account.
   This is an online bootstrap ZIP, not a signed EXE/MSI; third-party downloads require Internet.
2. Open the installed Manim Studio workspace, or initialize a separate project with
   `studio project init ./demo --name "Demo Project"`.
3. Connect the agent. The installed workspace supplies local Codex MCP configuration;
   sign in and trust the project separately. Generated external projects include shared
   Creator instructions for Codex and Claude; their default wrappers/MCP snippet use
   Docker and need adaptation to a native interpreter (see installation guidance).
4. Explicitly select **Guided** or **Flexible** for each new creation task. The Creator
   skill must read that mode's reference before creating content.
5. Create, review, revise, render and export. Start with `studio doctor --catalog`,
   `studio list`, and `studio render examples/square_to_circle --profile draft` in the
   installed repository workspace. Export supported all-slide decks with `studio export`.

Research is optional and disabled on new installations unless explicitly enabled.
See [Windows setup](docs/getting-started/windows-research-setup.md) for prerequisites,
source pinning, agent connection and remaining acceptance checks. Complete practical
walkthroughs remain tracked in [#31](https://github.com/alonshoa/Manim-Studio/issues/31).

For development, existing Docker/devcontainer workflows remain available. Build with
`docker build --target runtime -t manim-studio:local .`, or install locally using
Python 3.11+ and `python -m pip install -e ".[dev]"` after installing render prerequisites.

Common Workflows
----------------

Render a named beat:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Start an experimental local OpenGL live preview at a named beat:

```bash
studio live matrix_work/vectors_ab_to_v --beat resultant --diagnose
```

Live preview is a development aid. Final artifacts still come from
`studio render`, `studio build`, and `studio export`.

Start an interactive movie session from an empty slate:

```bash
studio session start --title "Vector Movie" --deck-id vector_movie
```

The session command creates a registered scratch scene and a `.steps.json`
ledger for accepted staged additions.

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
- verified GUI live preview in headless/container environments
- a YAML-only animation language
- fully autonomous scene editing through MCP
- unrestricted shell access through MCP

## Research logging

Optional local prompt/response and action logging, retrospective classification and
JSONL export and opt-in automatic Codex hook capture:
[research logging](docs/concepts/research-logging.md).
Other chat clients must explicitly supply prompts and responses to the bridge.

Clean Windows machine: [research workstation setup](docs/getting-started/windows-research-setup.md).
