# External Projects

External Manim projects can use Manim Studio without copying their scenes into
this repository. Mount the external project at `/workspace` in the reusable
runtime container and run `studio` from that mounted root.

## Generate a Project

Create a new external project:

```bash
studio project init ./demo --name "Demo Project"
```

Generated projects use `manim-studio:local` by default. To write a different
locally available image tag into the generated Docker and MCP configuration:

```bash
studio project init ./demo --name "Demo Project" --image-tag manim-studio:custom
```

Project generation writes the starter files only. It does not build Docker
images, pull runtime images, validate the environment, start MCP, or render.

Generated projects include:

- `.gitignore`
- `README.md`
- `AGENTS.md`
- `compose.yml`
- `mcp.manim-studio.json`
- `catalog/scenes.yaml`
- a registered starter scene
- `docs/conventions.md`
- Windows command wrappers

Verify the generated project separately:

```bash
studio project verify ./demo
```

Run a draft render only when explicitly requested:

```bash
studio project verify ./demo --render
```

This flow is not yet a zero-dependency public installer. Build or install the
configured runtime image, such as `manim-studio:local`, before verification.
Public bootstrap installers, automatic Codex or Claude configuration, and cloud
rendering are future distribution work.

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
