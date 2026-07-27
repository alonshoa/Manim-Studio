# Skill Contracts

Manim-specific skills must operate through registered Studio targets and staged
patch proposals. A skill may inspect scene context, build manifests, logs, and
artifacts, but it must not write canonical scene files directly.

## Render Debugging Skill

`render_debugging` helps turn a failed render into a reviewable staged patch
proposal. It is intentionally conservative: when the failure does not match a
supported minimal repair pattern, it returns diagnostics rather than editing.

Inputs:

- scene context from `get_scene_context`
- failed build manifest from `manim-studio://build/{build_id}/manifest`
- build logs from `get_build_log`
- registered target metadata for the scene being debugged

Allowed tools:

- `get_scene_context`
- `get_build_log`
- `get_artifacts`
- `propose_render_debug_patch`
- `inspect_scene_patch`
- `validate_scene_patch`
- `render_scene_patch`
- `apply_scene_patch`

Initial supported repair: a narrow Manim `NameError` correction when logs show
an undefined symbol close to a known Manim class.

## Contract Skeleton

```yaml
name:
objective:
inputs:
  - scene_context
  - build_manifest
  - logs
allowed_tools:
  - get_scene_context
  - get_build_log
  - propose_scene_patch
  - inspect_scene_patch
  - validate_scene_patch
  - render_scene_patch
  - apply_scene_patch
expected_artifacts:
  - staged_patch_proposal
  - unified_diff
  - validation_result
  - draft_render_manifest
stop_conditions:
  - target_not_registered
  - missing_required_context
  - ambiguous_or_large_change
  - unsupported_failure_pattern
acceptance_checks:
  - canonical_source_unchanged_before_apply
  - staged_validation_success
  - staged_draft_render_success
  - explicit_apply_approval
```
