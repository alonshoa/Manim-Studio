# Scene Migration

Migrate legacy scenes selectively. A migrated scene should first be copied into
the new structure with minimal code changes, then registered in the catalog.

Do not rewrite a scene into a new abstraction just to catalog it.

## Placement

Deck-specific scenes belong under:

```text
decks/<deck_id>/
```

Smoke tests and minimal examples can live under:

```text
examples/
```

Experimental work belongs under `decks/experiments/` or a clearly named scratch
subdirectory until it is promoted into a real deck.

## Catalog Registration

After adding the scene source, register it in:

```text
catalog/scenes.yaml
```

Include the required fields and the optional planning fields when known.

## Assets And Imports

Deck-specific assets belong next to the deck, typically under:

```text
decks/<deck_id>/assets/
```

Shared reusable assets should be introduced only when more than one deck
actually depends on them.

Scene imports should be normal Python imports that work from the mounted project
root inside the runtime container. Avoid hidden dependencies on the current
working directory, local absolute paths, or generated render output.

## Manim Kit Extraction

Only extract a helper into `manim_kit` when it recurs across scenes or
encapsulates difficult behavior such as Hebrew font setup, RTL alignment, slide
base behavior, or review-panel framing.

Keep one-off teaching details inside the scene.

## Checks

Before adding a migrated scene to a delivery deck:

```bash
studio catalog validate --strict-metadata
studio render <deck-id>/<scene-id> --profile draft
```

Larger render, build, and export workflows are separate phases and should not be
mixed into catalog registration.
