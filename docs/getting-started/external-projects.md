# External Projects

External Manim projects can use Manim Studio without copying their scenes into
this repository. Mount the external project at `/workspace` in the reusable
runtime container and run `studio` from that mounted root.

## One-Shot Docker Commands

Build the runtime image from the Manim Studio repository:

```bash
docker build --target runtime -t manim-studio:local .
```

Run commands against an external project:

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
  studio list
```

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio render demo/smoke --profile draft
```

Export an all-slides deck:

```bash
docker run --rm \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  manim-studio:local \
  studio export my_slides --format pptx --profile final
```

Generated `builds/`, `media/`, `slides/`, and review artifacts are written
inside the mounted project.

## Compose

`docs/compose.external.yml` is a copyable Compose service for an external
project:

```yaml
services:
  studio:
    image: manim-studio:local
    working_dir: /workspace
    environment:
      MANIM_STUDIO_REPO_ROOT: /workspace
    volumes:
      - .:/workspace
```

Copy it to the external project as `compose.yml` or adapt the service block.
Expected commands from the external project root:

```bash
docker compose run --rm studio studio doctor --catalog
docker compose run --rm studio studio list
docker compose run --rm studio studio catalog validate
docker compose run --rm studio studio render demo/smoke --profile draft
docker compose run --rm studio studio export my_slides --format pptx --profile final
docker compose run --rm -T studio manim-mcp
```

## MCP From Docker

Run the MCP stdio server without allocating a TTY:

```bash
docker run --rm -i \
  -v "/path/to/project:/workspace" \
  -w /workspace \
  -e MANIM_STUDIO_REPO_ROOT=/workspace \
  manim-studio:local \
  manim-mcp
```

Do not add `-t`; MCP stdio clients expect a non-interactive process.
