# Manim Studio Skill Contract Template

Manim-specific skills must operate through registered Studio targets and staged
patch proposals. A skill may inspect scene context, build manifests, logs, and
artifacts, but it must not write canonical scene files directly.

## Required Fields

- `name`: stable skill identifier.
- `objective`: one narrow workflow the skill supports.
- `inputs`: required MCP resources, tool responses, and user-provided context.
- `allowed_tools`: exact Studio MCP tools the skill may call.
- `expected_artifacts`: proposal IDs, diffs, validation results, draft renders,
  review frames, or notes the skill should produce.
- `stop_conditions`: cases where the skill must return diagnostics instead of
  proposing or applying a change.
- `acceptance_checks`: validation and render checks required before a proposal
  can be considered ready for human review.

## Safety Rules

- Work only on registered `<deck_id>/<scene_id>` targets.
- Propose changes with `propose_scene_patch`; do not use arbitrary file writes.
- Inspect generated diffs before validation or render.
- Validate and draft-render staged proposals before applying them.
- Apply only after explicit approval through `apply_scene_patch`.
- Return `unsupported` when a safe, minimal patch cannot be identified.

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
