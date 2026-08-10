# Interactive Authoring

Interactive authoring is the controller-backed workflow for previewing Codex
or MCP proposals in a local Manim OpenGL window before accepting them into the
canonical scene source.

The Python core owns the session state. VS Code, MCP, and CLI commands are thin
clients over the same `AuthoringSessionController`.

Persisted state is stored under `.manim-studio/authoring/<session-id>/` and
tracks:

- session and target identity
- `authoring_status`: `READY`, `DECISION_REQUIRED`, `PAUSED`, `FINISHING`,
  `COMPLETED`, or `ERROR`
- `proposal_status`: `NONE`, `PROPOSED`, `PREVIEWED`, or `NEEDS_REVISION`
- `live_status`: `STOPPED`, `STARTING`, `RUNNING`, `RELOADING`, or `FAILED`
- canonical source and candidate preview source
- active proposal ID, when a proposal is waiting or previewed
- working and preview revisions
- current accepted or candidate beat
- live status, live process ID, and last concise error
- computed `next_action`, used by thin clients for context-sensitive commands

## Source Selection

Canonical source is not changed during preview. A staged proposal lives in:

```text
builds/staged/<proposal-id>/workspace/
```

Preview runs live mode against that staged workspace and reports the exact
source root, source path, proposal, revision, and beat being displayed.

Acceptance validates and draft-renders the staged proposal, applies it to the
canonical source, updates the movie ledger, advances the revision, and returns
live preview to the canonical source.

Rejecting clears the active proposal and returns live preview to the last
accepted canonical revision.

Revision is a distinct decision. Studio stores the UTF-8 feedback, returns live
preview to the last accepted source, skips the revised proposal during
discovery, and waits for Codex/MCP to create a replacement proposal against the
same accepted revision.

The semantic default proposal path is `propose_next_movie_step`. It accepts a
Python body plus title/rationale, then Studio determines the next `step_NNN`,
insertion point inside the registered scene class's `construct()` method, beat
call, and staged candidate source. The canonical source is still unchanged until
acceptance.

## Beats

Generated movie sessions still start with `empty`. Each accepted step adds a
stable beat such as:

```text
step_001
step_002
step_003
```

The current beat is persisted and becomes the default live target after restart.

## Local Client Protocol

The VS Code extension starts:

```text
studio authoring rpc
```

It communicates with Studio over JSON lines on stdio. This avoids an exposed
network port and keeps catalog parsing, path validation, staged-edit rules, and
Manim command construction in Python.

This milestone supports local desktop VS Code with local Python. WSL,
devcontainers, and remote workspaces are experimental.

Existing checked-in sessions under `decks/test-movie`,
`decks/interactive-vsc`, and `decks/interactive/interactive-vstest-bfd60b`
appear to be manual smoke-test artifacts. They should be reviewed before a
future PR cleanup, but this workflow does not delete or rewrite them.
