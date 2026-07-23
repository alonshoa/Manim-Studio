# Local MCP Server

Manim Studio exposes a minimal local MCP server for registered project content.
The server runs over stdio and reuses the same catalog, validation, beat, and
build services as the `studio` CLI.

## Install

Inside the devcontainer, install the package in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Then verify that the entry point resolves:

```bash
manim-mcp
```

MCP clients launch stdio servers as non-interactive processes. In any runtime
container, that process must see `/opt/venv/bin` on `PATH` so `manim`,
`manim-slides`, and the `manim-mcp` entry point resolve consistently.

## Client Configuration

Use the repository root as the working directory. A typical local MCP client
configuration looks like:

```json
{
  "mcpServers": {
    "manim-studio": {
      "command": "manim-mcp",
      "cwd": "/workspaces/Manim-Studio",
      "env": {
        "MANIM_STUDIO_REPO_ROOT": "/workspaces/Manim-Studio",
        "PATH": "/opt/venv/bin:/manim/.local/bin:/home/manimuser/.local/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

For an external project through the reusable Docker runtime, launch Docker with
stdin attached and no TTY:

```json
{
  "mcpServers": {
    "manim-studio": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "/path/to/project:/workspace",
        "-w",
        "/workspace",
        "-e",
        "MANIM_STUDIO_REPO_ROOT=/workspace",
        "manim-studio:local",
        "manim-mcp"
      ]
    }
  }
}
```

Do not include `-t` or allocate a TTY for the MCP stdio process.

On a Windows host that starts the server through WSL, run the command inside
the devcontainer/runtime container or use the matching Linux project path.
Avoid pointing MCP clients at the Windows checkout path when renders are
expected to run in the Linux container.

## Exposed Surface

Resources:

- `manim-studio://conventions`
- `manim-studio://catalog`
- `manim-studio://scene/{deck_id}/{scene_id}`
- `manim-studio://build/{build_id}/manifest`
- `manim-studio://build/{build_id}/artifacts`
- `manim-studio://build/{build_id}/log/{stream}`

Tools:

- `list_decks`
- `get_scene_context`
- `validate_scene`
- `render_scene`
- `render_beat`
- `build_deck`
- `get_build_log`
- `get_artifacts`
- `propose_scene_patch`
- `inspect_scene_patch`
- `validate_scene_patch`
- `render_scene_patch`
- `apply_scene_patch`
- `propose_render_debug_patch`
- `export_deck`

All tool responses use the same structured envelope:

```json
{
  "ok": true,
  "status": "success",
  "data": {},
  "error": null
}
```

Failures use stable error codes such as `invalid_target`, `target_not_found`,
`catalog_invalid`, `validation_failed`, `beat_not_found`, `build_not_found`,
`render_failed`, `export_failed`, `unsupported_deck`, `unsupported`, and
`internal_error`.

## Deck Export

`export_deck` exports a registered all-slides deck through the same Studio build
service used by the CLI. The initial supported format is `pptx`:

```json
{
  "deck_id": "my_slides",
  "format": "pptx",
  "profile": "final",
  "force": false
}
```

PPTX export renders each registered `renderer: manim-slides` scene, collects the
generated Manim Slides `slides/<ClassName>.json` and `slides/files/<ClassName>/`
outputs into an isolated export build, then runs:

```bash
manim-slides convert --folder <export-build>/slides --to=pptx <ClassName...> <export-build>/export/<deck>.pptx
```

The generated `.pptx` is listed as a `presentation` artifact and can be
discovered through `get_artifacts` or
`manim-studio://build/{build_id}/artifacts`. HTML, PDF, ZIP, and other formats
currently return `unsupported`. Decks that include any non-`manim-slides` scene
return `unsupported_deck` with the incompatible scene targets.

Manim Slides documents PPTX conversion as experimental because playback support
can vary between PowerPoint and LibreOffice versions. PowerPoint or LibreOffice
is not required to generate the file in the runtime container.

## Safety Model

The server does not expose a shell tool and does not expose direct arbitrary
scene-editing operations. Tools accept registered deck IDs, scene IDs, build
IDs, proposal IDs, and log stream names; path-like input is rejected before
reaching the Studio services.

Scene edits use an explicit staged workflow:

```text
propose_scene_patch
-> inspect_scene_patch
-> validate_scene_patch
-> render_scene_patch
-> apply_scene_patch
```

Patch proposals are isolated under `builds/staged/<proposal_id>/workspace`.
The canonical scene source is not modified until `apply_scene_patch` receives
`confirm: "apply"` and the proposal has passed staged validation and draft
rendering. Applying also refuses stale proposals when the registered source path
or source checksum changed after proposal creation.

Structured patch operations are the only supported edit input:

- `replace`: `start_line`, `end_line`, `text`, optional `expected`
- `insert_after`: `line`, `text`, optional `expected`
- `delete`: `start_line`, `end_line`, optional `expected`

`propose_render_debug_patch` implements the first Manim-specific skill surface.
It consumes a failed build manifest and logs, then creates a staged proposal only
for supported minimal repairs. Unsupported failures return structured
diagnostics instead of editing.

`export_deck` does not expose arbitrary shell execution. It accepts only a
registered deck ID, a supported format, a render profile, and the explicit
`force` override used by existing render/build services.
