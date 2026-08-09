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

## `studio live`

Start an experimental OpenGL live-preview session at a named beat:

```bash
studio live <deck-id>/<scene-id> --beat <beat-id>
```

Print environment diagnostics before starting:

```bash
studio live <deck-id>/<scene-id> --beat <beat-id> --diagnose
```

Options:

- `--beat <beat-id>` (required)
- `--repo-root`
- `--catalog`
- `--live-root`
- `--diagnose`

Live preview uses local host Python and Manim CE's OpenGL renderer. It is not
part of the Docker/Cairo final-render path and does not create normal Studio
build manifests. See [Live Preview](../concepts/live-preview.md) for the
current limitations and manual GUI smoke test.

## `studio session`

Create and maintain interactive movie sessions.

Start a registered empty-slate scene:

```bash
studio session start --title "Vector Movie" --deck-id vector_movie
```

Options:

- `--title`
- `--deck-id`
- `--scene-id`
- `--class-name`
- `--repo-root`
- `--catalog`

Inspect the accepted step ledger:

```bash
studio session inspect <session-id>
```

Accept a staged proposal after validation and draft render:

```bash
studio session accept <session-id> <proposal-id> --confirm accept
```

Options:

- `--note`
- `--confirm`
- `--repo-root`
- `--builds-root`

Session start writes a normal catalog entry and a source file under `decks/`.
Accepted proposals are recorded in a `.steps.json` file beside the source. See
[Movie Sessions](../concepts/movie-sessions.md).

## `studio authoring`

Run the controller-backed interactive authoring workflow used by CLI, MCP, and
the VS Code extension.

```bash
studio authoring start --title "Vector Movie" --deck-id vector_movie
studio authoring status <session-id>
studio authoring live-start <session-id>
studio authoring preview <session-id> <proposal-id>
studio authoring accept <session-id> <proposal-id> --confirm accept
studio authoring reject <session-id> [proposal-id]
studio authoring live-restart <session-id>
studio authoring live-stop <session-id>
```

Add `--json` to command-style operations for compact machine-readable output.
The VS Code extension uses:

```bash
studio authoring rpc
```

This mode communicates over JSON lines on stdio and does not expose a network
port.

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
