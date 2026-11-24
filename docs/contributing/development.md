# Development

Use the devcontainer or local Python 3.11+ install for development.

## Devcontainer

Open the repository in VS Code and run **Dev Containers: Reopen in Container**.
The devcontainer builds from the same root `Dockerfile` as the reusable runtime
image and installs the project in editable mode.

For `studio live`, the devcontainer is configured for WSLg/X11 forwarding by
mounting `/mnt/wslg` and `/tmp/.X11-unix` and forwarding the display-related
environment variables. This is a development convenience, not the default final
render path. Verify it from an integrated terminal with:

```bash
studio live matrix_work/vectors_ab_to_v --beat resultant --diagnose
```

## Local Install

```bash
python -m pip install -e ".[dev]"
```

## Tests

Run:

```bash
pytest tests -q
```

If the package is not installed in the current shell, use:

```powershell
$env:PYTHONPATH='src'; pytest tests -q
```

The GitHub Actions test workflow runs:

- catalog validation
- Python tests in `manimcommunity/manim:v0.20.1`
- runtime image smoke checks against the external project fixture

## Development Principles

- Keep Python scene files as the source of truth.
- Build the Studio workflow before adding deeper automation.
- Keep generated output out of Git.
- Keep MCP operations structured and safe.
