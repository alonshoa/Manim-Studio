# Debug Render Failures

Manim Studio keeps failed renders inspectable. A failed build still writes logs,
metadata, preflight results, and a manifest under `builds/`.

## Inspect The Build

```bash
studio inspect <build-id>
```

Look for:

- `Status`
- `Failure class`
- `Preflight`
- validation issues
- stdout and stderr log paths
- generated artifacts

## Common Failure Classes

- `validation_failed`: preflight found issues before rendering
- `smoke_render_failed`: review/final smoke render failed
- `render_failed`: the renderer returned a non-zero exit code
- `export_failed`: export conversion failed after scene rendering

## MCP Render Debugging

The MCP server exposes a conservative render-debugging workflow. It can propose
a staged patch only for supported minimal repairs. Unsupported failures return
diagnostics instead of editing source files.

The staged flow is:

```text
propose_render_debug_patch
-> inspect_scene_patch
-> validate_scene_patch
-> render_scene_patch
-> apply_scene_patch
```

The first supported repair is a narrow Manim `NameError` correction, such as
replacing an undefined symbol close to a known Manim class.

## Safety Boundaries

Staged proposals are isolated under:

```text
builds/staged/<proposal_id>/workspace
```

The canonical scene source is unchanged until `apply_scene_patch` receives
`confirm: "apply"` and the staged validation and draft render have passed.
