# Repository Layout

```text
Manim-Studio/
|-- .devcontainer/            # Reproducible local development environment
|-- .github/workflows/        # Tests and GitHub Pages workflows
|-- baselines/                # Curated baseline review notes and snapshots
|-- builds/                   # Local isolated render outputs, ignored by Git
|-- catalog/                  # Registered deck and scene metadata
|-- decks/                    # Presentation content and migrated pilot scenes
|-- docs/                     # GitHub Pages documentation source
|-- examples/                 # Minimal Manim and Manim Slides smoke scenes
|-- media/                    # Local Manim output, ignored by Git
|-- slides/                   # Local Manim Slides output, ignored by Git
|-- src/
|   |-- manim_kit/            # Reusable visual and layout components
|   |-- manim_mcp/            # Local MCP server and service envelope
|   `-- manim_studio/         # CLI, catalog, validation, profiles, builds
|-- tests/                    # Unit and service tests
|-- Dockerfile                # Runtime and devcontainer image targets
|-- mkdocs.yml                # GitHub Pages documentation configuration
|-- pyproject.toml
`-- README.md
```

## Tracked Content

- `catalog/` stores lightweight registries such as `catalog/scenes.yaml`.
- `decks/` stores presentation content grouped by deck ID.
- `examples/` stores minimal smoke scenes.
- `baselines/` stores curated baseline notes and snapshots.
- `docs/` stores the GitHub Pages site source.
- `src/manim_kit/` stores reusable visual, layout, Hebrew/RTL, and beat helpers.
- `src/manim_studio/` stores project tooling such as catalog validation, build
  metadata, profiles, and CLI behavior.
- `src/manim_mcp/` stores the local MCP server and service envelope.
- `scripts/` stores repository utilities that are not public package APIs.
- `tests/` stores validation and regression tests.

## Generated Content

These directories are local-only and should stay out of Git:

- `builds/`
- `media/`
- `slides/`

Generated review artifacts inside `builds/` are for local inspection. Curated
baseline review frames or notes can be copied into `baselines/` intentionally.
