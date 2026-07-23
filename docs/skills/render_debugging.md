# Render Debugging Skill

## Contract

`render_debugging` helps turn a failed render into a reviewable staged patch
proposal. It is intentionally conservative: when the failure does not match a
supported minimal repair pattern, it returns diagnostics rather than editing.

## Inputs

- Scene context from `get_scene_context`.
- A failed build manifest from `manim-studio://build/{build_id}/manifest`.
- Build logs from `get_build_log`.
- The registered target metadata for the scene being debugged.

## Allowed Tools

- `get_scene_context`
- `get_build_log`
- `get_artifacts`
- `propose_render_debug_patch`
- `inspect_scene_patch`
- `validate_scene_patch`
- `render_scene_patch`
- `apply_scene_patch`

The skill must not call shell tools or write scene files directly.

## Expected Artifacts

- A staged proposal ID when a safe fix is found.
- A unified diff for the proposed source change.
- Validation and draft-render results after review-time checks run.
- An `unsupported` failure with log-derived diagnostics when no safe fix is
  available.

## Stop Conditions

- The target is not registered in the catalog.
- The build manifest is missing or belongs to a different scene.
- The build succeeded.
- Logs do not contain a supported failure signature.
- The proposed change would affect more than the registered scene source file.

## Acceptance Checks

- The canonical source remains unchanged after proposal creation.
- `validate_scene_patch` succeeds in the staged workspace.
- `render_scene_patch` succeeds with the draft profile.
- `apply_scene_patch` is called only after explicit human approval.

## Initial Supported Repair

The first implementation supports a narrow Manim `NameError` repair. When logs
show an undefined symbol close to a known Manim class, such as `Sqare` for
`Square`, the skill proposes a one-line replacement in the registered scene
source. All other failures return `unsupported`.
