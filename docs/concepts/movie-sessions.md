# Movie Sessions

Movie sessions are the interactive-authoring workflow for building a scene from
an empty slate with small accepted additions.

The session model has four parts:

1. Start from a generated blank, registered scene.
2. Let Codex propose small staged addons against that scene.
3. Validate and draft-render each proposal before user acceptance.
4. Apply accepted proposals and save them into a `.steps.json` ledger beside the
   scene source.

## Start From An Empty Slate

Create a session:

```bash
studio session start --title "Vector Movie" --deck-id vector_movie
```

The command creates:

- a registered scene source under `decks/<deck-id>/<scene-id>.py`
- a versionable steps ledger beside it
- a catalog entry

It also prints the live-preview command:

```bash
studio live <deck-id>/<scene-id> --beat empty --diagnose
```

The generated source starts with one named beat, `empty`, so the interactive
OpenGL shell can enter before any visual content is added.

## Codex Addons

Codex uses the MCP staged-edit workflow for addons. A movie session wraps the
normal staged patch tools with session-aware helpers:

```text
propose_movie_step
-> inspect_scene_patch
-> validate_scene_patch
-> render_scene_patch
-> accept_movie_step
```

`propose_movie_step` creates a staged patch against the session target. The
canonical source remains unchanged until the proposal is accepted.

## Acceptance

Acceptance is explicit:

```bash
studio session accept <session-id> <proposal-id> --confirm accept
```

The proposal must already have passed staged validation and draft render. The
accept command applies the proposal to the canonical source and appends the
accepted diff, rationale, checksums, and note to the session ledger.

## Final Movie

The final movie is still produced by the normal reproducible pipeline:

```bash
studio render <deck-id>/<scene-id> --profile final
```

The `.steps.json` ledger is authoring history. The `.py` scene source is the
renderable artifact.
