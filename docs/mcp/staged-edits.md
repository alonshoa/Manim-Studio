# Staged Edits

MCP scene edits use an explicit staged workflow. The canonical scene source is
not modified until the proposal is inspected, validated, draft-rendered, and
explicitly applied.

## Workflow

```text
propose_scene_patch
-> inspect_scene_patch
-> validate_scene_patch
-> render_scene_patch
-> apply_scene_patch
```

Render debugging uses the same staged model:

```text
propose_render_debug_patch
-> inspect_scene_patch
-> validate_scene_patch
-> render_scene_patch
-> apply_scene_patch
```

## Proposal Storage

Patch proposals are isolated under:

```text
builds/staged/<proposal_id>/workspace
```

Applying refuses stale proposals when the registered source path or source
checksum changed after proposal creation.

## Supported Patch Operations

Structured patch operations are the only supported edit input:

- `replace`: `start_line`, `end_line`, `text`, optional `expected`
- `insert_after`: `line`, `text`, optional `expected`
- `delete`: `start_line`, `end_line`, optional `expected`

## Safety Model

The MCP server does not expose a shell tool and does not expose direct arbitrary
scene-editing operations. Tools accept registered deck IDs, scene IDs, build
IDs, proposal IDs, and log stream names. Path-like input is rejected before it
reaches Studio services.
