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

MCP clients launch stdio servers as non-interactive processes. In the
devcontainer, that process must see `/opt/venv/bin` on `PATH` so `manim`,
`manim-slides`, and the `manim-mcp` entry point resolve consistently. This is
the same environment concern tracked in GitHub issue #13.

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

On a Windows host that starts the server through WSL, run the command inside
the devcontainer or use the matching Linux repository path. Avoid pointing MCP
clients at the Windows checkout path when renders are expected to run in the
Linux container.

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
`render_failed`, `unsupported`, and `internal_error`.

## Safety Model

The server does not expose a shell tool and does not expose direct scene-editing
operations. Tools accept registered deck IDs, scene IDs, build IDs, and log
stream names; path-like input is rejected before reaching the Studio services.

`export_deck` is present for MCP surface compatibility but currently returns
`unsupported` because Manim Studio does not yet have an export service.
