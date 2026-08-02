# CLI Reference

`studio` is the main local workflow entry point.

## Entry Points

`pyproject.toml` exposes:

```text
studio = manim_studio.cli:main
manim-mcp = manim_mcp.server:main
```

## `studio doctor`

Report local render prerequisites:

```bash
studio doctor
```

Also validate strict catalog metadata:

```bash
studio doctor --catalog
```

## `studio list`

List registered decks and scenes:

```bash
studio list
```

Options:

- `--repo-root`
- `--catalog`

## `studio validate`

Confirm a deck or scene target exists and catalog metadata can be loaded:

```bash
studio validate <deck-id>
studio validate <deck-id>/<scene-id>
```

## `studio catalog validate`

Validate catalog entries against files and scene classes:

```bash
studio catalog validate
```

Require optional planning metadata:

```bash
studio catalog validate --strict-metadata
```

## `studio project init`

Generate an external Manim Studio project without running Docker, building an
image, validating the runtime, or rendering:

```bash
studio project init ./demo --name "Demo Project"
```

Options:

- `--name`
- `--deck-id`
- `--scene-id`
- `--class-name`
- `--language`
- `--image-tag`
- `--force`

The generated project includes a catalog, starter scene, Compose file, MCP
snippet, `AGENTS.md`, documentation, and Windows helper wrappers.

## `studio project verify`

Verify the Docker runtime for a generated external project:

```bash
studio project verify ./demo
```

This checks Docker availability, Docker responsiveness, the configured runtime
image, `studio doctor --catalog`, `studio list`, and starter target validation.
It does not build or pull a runtime image automatically.

Run an optional draft render and confirm a host-visible artifact:

```bash
studio project verify ./demo --render
```

This command is verification only. Public bootstrap installation, image
publication, automatic client configuration, and cloud rendering are future
distribution work.

## `studio beats`

List named beats discovered in a registered scene:

```bash
studio beats <deck-id>/<scene-id>
```

## `studio render`

Render one registered scene into an isolated build directory:

```bash
studio render <deck-id>/<scene-id> --profile draft
```

Options:

- `--profile draft|review|final`
- `--repo-root`
- `--catalog`
- `--builds-root`
- `--beat <beat-id>`
- `--force`

## `studio build`

Render all scenes in a registered deck serially:

```bash
studio build <deck-id> --profile review
```

Options:

- `--profile draft|review|final`
- `--repo-root`
- `--catalog`
- `--builds-root`
- `--force`

## `studio export`

Export an all-slides deck to a delivery artifact:

```bash
studio export <deck-id> --format pptx --profile final
```

Options:

- `--format pptx`
- `--profile draft|review|final`
- `--repo-root`
- `--catalog`
- `--builds-root`
- `--force`

## `studio inspect`

Inspect a previous isolated build by build ID:

```bash
studio inspect <build-id>
```

Options:

- `--repo-root`
- `--builds-root`
