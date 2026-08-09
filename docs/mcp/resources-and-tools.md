# Resources And Tools

The MCP server exposes registered Manim Studio operations. It does not expose an
unrestricted shell.

## Resources

- `manim-studio://conventions`
- `manim-studio://catalog`
- `manim-studio://scene/{deck_id}/{scene_id}`
- `manim-studio://build/{build_id}/manifest`
- `manim-studio://build/{build_id}/artifacts`
- `manim-studio://build/{build_id}/log/{stream}`

## Tools

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
- `start_movie_session`
- `get_movie_session`
- `get_authoring_session_status`
- `propose_movie_step`
- `preview_movie_step`
- `accept_movie_step`
- `reject_movie_step`
- `start_authoring_live`
- `restart_authoring_live`
- `stop_authoring_live`
- `export_deck`

## Response Envelope

All tool responses use the same structured envelope:

```json
{
  "ok": true,
  "status": "success",
  "data": {},
  "error": null
}
```

Failures use stable error codes such as:

- `invalid_target`
- `target_not_found`
- `catalog_invalid`
- `validation_failed`
- `beat_not_found`
- `build_not_found`
- `render_failed`
- `export_failed`
- `unsupported_deck`
- `unsupported`
- `internal_error`

## Export Tool

`export_deck` supports `format: "pptx"` for decks whose registered scenes all
use `renderer: manim-slides`.

```json
{
  "deck_id": "my_slides",
  "format": "pptx",
  "profile": "final",
  "force": false
}
```

Other formats return `unsupported`; mixed decks return `unsupported_deck`.

## Movie Session Tools

`start_movie_session` creates a registered empty-slate scene and initializes
controller-owned authoring state.

`propose_movie_step` stages a small addon against the session target. The
canonical source remains unchanged.

`preview_movie_step` selects the staged candidate workspace for live preview and
returns compact state:

```json
{
  "ok": true,
  "status": "preview_ready",
  "data": {
    "session_id": "story-scratch-abc12345",
    "proposal_id": "20260809-190000-patch-story-scratch-abc12345",
    "revision": 0,
    "beat": "step_001",
    "changed_lines": "8-11",
    "warnings": []
  },
  "error": null
}
```

`accept_movie_step` requires `confirm: "accept"`. It validates, draft-renders,
applies the staged proposal to the canonical source, appends the accepted step
to the ledger, and returns compact authoring state.

`reject_movie_step` clears the active proposal and returns live preview to the
last accepted canonical revision. Use `get_movie_session` only when full
accepted-step history is explicitly needed.
