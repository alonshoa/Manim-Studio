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
