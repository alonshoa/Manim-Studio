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
