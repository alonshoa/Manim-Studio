# Live Preview

`studio live` is an experimental local development workflow for reaching a
named beat and entering Manim Community's OpenGL interactive shell.

It is separate from the reproducible render pipeline:

```text
studio render/build/export -> normal Cairo/Docker delivery workflow
studio live                -> optional local OpenGL development workflow
```

Use final renders, builds, exports, and review artifacts from the existing
Studio pipeline. Live preview is for local iteration only.

## Command

Start a registered scene at a named beat:

```bash
studio live matrix_work/vectors_ab_to_v --beat resultant
```

Print diagnostics before starting:

```bash
studio live matrix_work/vectors_ab_to_v --beat resultant --diagnose
```

The live command validates the catalog target and beat before launching Manim.
For the first vertical slice it uses host Python and starts Manim directly:

```text
python -m manim --renderer=opengl --force_window -ql --media_dir <live-media-dir> <source.py> <SceneClass>
```

The command keeps stdin, stdout, and stderr attached so the embedded IPython
session can own the terminal.

## Runtime Model

When live mode targets a beat, Studio sets both environment variables:

- `MANIM_STUDIO_BEAT=<beat>`
- `MANIM_STUDIO_LIVE_BEAT=<beat>`

`MANIM_STUDIO_BEAT` preserves the existing beat-skipping behavior. The live
variable tells `BeatMixin` to call `interactive_embed()` only when the selected
beat is reached. Scene files do not need to call `interactive_embed()` manually.

Live output goes under `.manim-studio/live/`. It is ignored by Git and is not a
normal production build record.

## Environment

The supported v1 path is native host Python with the pinned project
dependencies installed:

```bash
python -m pip install -e .
```

WSLg is supported through the VS Code devcontainer configuration when the host
provides `/mnt/wslg` and `/tmp/.X11-unix`. The devcontainer forwards the display
environment and sets `MANIM_STUDIO_ALLOW_CONTAINER_LIVE=1` so diagnostics permit
the GUI attempt. Generic Docker GUI forwarding outside that devcontainer remains
unsupported in v1.

In headless or container-only environments, use the existing beat render
fallback:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

Diagnostics report common blockers:

- missing `manim` CLI or import
- missing `manim_slides` import for slide scenes
- missing OpenGL renderer import
- missing interactive TTY
- missing graphical display
- container contexts where GUI forwarding is not a supported default
- IPython version notes

Manim CE v0.20.1's OpenGL interactive path can be sensitive to IPython
versions. If `sqlite3.ProgrammingError` appears during interactive embed,
test Manim's documented workaround:

```bash
python -m pip install IPython==8.0.1
```

Do not pin this globally until the local GUI failure is reproduced.

## Manual Smoke Test

Run this on a machine with a graphical display and local Manim dependencies:

```bash
studio live matrix_work/vectors_ab_to_v --beat resultant --diagnose
```

Then verify:

- the OpenGL window opens
- the scene reaches the selected beat
- the IPython prompt remains usable
- this command changes the active scene:

```python
add(Dot())
```

- a simple animation command works:

```python
play(FadeIn(Text("live")))
```

- `rerun()` either reloads successfully or fails in a documented way
- closing the window or terminal exits cleanly

Headless CI cannot verify the OpenGL window, terminal control behavior, or GPU
compatibility. Documentation and test reports must not claim GUI verification
unless this smoke test has actually passed.

## Future Layers

VS Code integration should be a thin adapter over the Studio CLI or a future
Studio-owned session API. It should not reimplement catalog resolution, beat
parsing, or Manim command construction.

Potential MCP tools remain future work:

```text
live_preview_status
start_live_preview
reload_live_preview
stop_live_preview
```

Do not add an MCP tool that accepts arbitrary Python code until there is an
explicit local-only safety design. Running project Python locally is part of
Manim development; the risk is accidentally exposing that execution channel
through MCP or a network-accessible control API.
