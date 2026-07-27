# MCP Conventions Resource

This file is kept at `docs/conventions.md` because the MCP server exposes it as
`manim-studio://conventions`. The public documentation site now splits the same
material across topic pages:

- [Repository Layout](reference/repository-layout.md)
- [Catalog](concepts/catalog.md)
- [Render A Beat](workflows/render-a-beat.md)
- [Manim Kit](manim-kit/index.md)
- [Scene Migration](contributing/scene-migration.md)

## Core Rules

Python scene files remain the source of truth. Catalog metadata describes scenes
so tools can inspect and validate them without rewriting animation code.

Generated output under `builds/`, `media/`, and `slides/` is local-only and
must stay out of Git.

Deck IDs and scene IDs use lowercase kebab-case or snake_case ASCII. Keep IDs
stable after they appear in `catalog/scenes.yaml`.

Scene targets use `<deck_id>/<scene_id>`. Deck targets use `<deck_id>`.

## Catalog Minimum

Each scene entry must include:

- `deck_id`
- `scene_id`
- `source_path`
- `class_name`
- `base_scene_type`
- `renderer`
- `language`

Use `renderer: manim` for normal Manim Community scenes and
`renderer: manim-slides` for slide scenes rendered through Manim Slides.

## Beats

Use beats when a scene is long enough that reviewing or rendering the whole
thing is too slow or vague. Beat IDs should describe teaching intent, such as
`intro`, `tail_to_head`, or `resultant`.

Add beats with `BeatMixin` and literal calls:

```python
self.beat("resultant", label="Reveal resultant vector")
```

## Migration

Migrate legacy scenes selectively. Copy one coherent scene into the new
structure with minimal code changes, register it in the catalog, then run:

```bash
studio catalog validate --strict-metadata
studio render <deck-id>/<scene-id> --profile draft
```

Only extract helpers into `manim_kit` when they recur across scenes or isolate
behavior that is easy to get wrong.
