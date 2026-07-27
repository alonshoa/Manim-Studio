# Build A Deck

Build all scenes in a registered deck:

```bash
studio build <deck_id> --profile review
```

Example:

```bash
studio build examples --profile review
```

Deck targets use only the deck ID. Do not use `<deck>/<scene>` syntax with
`studio build`.

## Validation

Before building:

```bash
studio catalog validate
studio validate examples
```

## Output

Deck builds create one parent build under `builds/` and render each scene
serially into its own scene build. The parent manifest records the child scene
build IDs and statuses.

Inspect the parent build:

```bash
studio inspect <deck-build-id>
```

Inspect individual scene builds when a deck build reports a scene failure.

## Review Artifacts

The `review` and `final` profiles run a draft-quality smoke render before the
expensive render. Successful review renders produce representative PNG frames
and `review/contact_sheet.png` when FFmpeg can extract frames from the video.

Use review builds to check layout, pacing, Hebrew/RTL rendering, camera framing,
and artifacts before running final exports.
