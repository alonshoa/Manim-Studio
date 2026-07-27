# MCP Overview

Manim Studio exposes a local MCP stdio server for registered project content.
The server reuses the same catalog, validation, beat, build, log, artifact, and
export services as the `studio` CLI.

The command is:

```bash
manim-mcp
```

## Local Install

Inside the devcontainer or a local Python 3.11 environment:

```bash
python -m pip install -e ".[dev]"
manim-mcp
```

MCP clients launch stdio servers as non-interactive processes. In a runtime
container, the process must see `/opt/venv/bin` on `PATH` so `manim`,
`manim-slides`, and `manim-mcp` resolve consistently.

## Client Configuration

Use the repository root as the working directory:

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

For Docker-backed external projects, launch Docker with stdin attached and no
TTY:

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

On Windows hosts, run expected renders inside the devcontainer/runtime container
or through WSL with matching Linux project paths.
