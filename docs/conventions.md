# Manim Studio Conventions

These conventions define where project content belongs and how scenes are
registered during the early foundation phase. Python scene files remain the
source of truth; catalog metadata describes scenes so tools can inspect and
validate them without rewriting the animation code.

## Repository Layout

- `catalog/` stores lightweight registries such as `catalog/scenes.yaml`.
- `decks/` stores presentation content grouped by deck ID.
- `src/manim_kit/` stores reusable visual, layout, Hebrew/RTL, and diagram
  helpers shared by scenes.
- `src/manim_studio/` stores project tooling such as catalog validation,
  build metadata, artifact inspection, and future orchestration helpers.
- `scripts/` stores small repository utilities that are not public package APIs.
- `tests/` stores validation and regression tests.
- `builds/`, `media/`, and `slides/` are local generated output directories
  and must stay out of Git.
- `old_version/` is a read-only reference archive until scenes are migrated
  intentionally.

## IDs And Filenames

Deck IDs and scene IDs use lowercase kebab-case or snake_case ASCII. Keep IDs
stable after they appear in `catalog/scenes.yaml`, because future build
artifacts and review notes will use them as durable references.

Scene files should use descriptive snake_case filenames. A deck-specific scene
belongs under `decks/<deck_id>/`, while smoke tests or minimal examples can live
under `examples/`. Experimental work belongs under `decks/experiments/` or a
clearly named scratch subdirectory until it is promoted into a real deck.

## Catalog Entries

`catalog/scenes.yaml` is descriptive metadata. It registers existing Python
scene classes without changing their implementation.

Each scene entry must include:

- `deck_id`
- `scene_id`
- `source_path`
- `class_name`
- `base_scene_type`
- `renderer`
- `language`

`asset_notes` is optional and should briefly describe external images, fonts,
data files, or generated assets the scene expects.

Use `renderer: manim` for normal Manim Community scenes and
`renderer: manim-slides` for slide scenes that should be rendered through
Manim Slides. `base_scene_type` should name the main scene base class such as
`Scene`, `MovingCameraScene`, `ThreeDScene`, or `Slide`.

## Assets And Imports

Deck-specific assets belong next to the deck, typically under
`decks/<deck_id>/assets/`. Shared reusable assets belong under a future shared
asset directory only when more than one deck actually depends on them.

Scene imports should be normal Python imports that work from the repository
root inside the devcontainer. Avoid hidden dependencies on the current working
directory, local absolute paths, or generated render output.

## Migration Rules

Migrate legacy scenes selectively. A migrated scene should first be copied into
the new structure with minimal code changes, then registered in the catalog.
Do not rewrite a scene into a new abstraction just to catalog it.

Before adding a migrated scene to a delivery deck, run catalog validation and a
small render smoke check in the devcontainer. Larger render, build, and export
workflows are separate phases and should not be mixed into catalog registration.
