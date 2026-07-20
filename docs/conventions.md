# Manim Studio Conventions

These conventions define where project content belongs and how scenes are
registered during the early foundation phase. Python scene files remain the
source of truth; catalog metadata describes scenes so tools can inspect and
validate them without rewriting the animation code.

## Repository Layout

- `catalog/` stores lightweight registries such as `catalog/scenes.yaml`.
- `decks/` stores presentation content grouped by deck ID.
- `src/manim_kit/` stores reusable visual, layout, Hebrew/RTL, and diagram
  helpers shared by scenes. See `docs/manim_kit.md` for the supported public
  API and extraction rules.
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

Pilot scenes and migrated scenes should also include these optional planning
fields when known:

- `description`
- `render_command`
- `font_notes`
- `parameter_notes`
- `baseline_path`
- `migration_notes`

Use `renderer: manim` for normal Manim Community scenes and
`renderer: manim-slides` for slide scenes that should be rendered through
Manim Slides. `base_scene_type` should name the main scene base class such as
`Scene`, `MovingCameraScene`, `ThreeDScene`, or `Slide`.

`parameter_notes` should name the scene knobs that a maintainer can safely
change: matrix values, vectors, graph ranges, tracker ranges, camera angles,
font choices, and teaching intent. `baseline_path` should point at a tracked
directory containing curated preview frames or a note describing the expected
baseline captures.

## Named Beats

A beat is an optional named conceptual segment inside a scene. Use beats when a
scene is long enough that reviewing or rendering the whole thing is too slow or
too vague. Beat IDs should describe teaching intent, such as `intro`,
`tail_to_head`, or `resultant`, rather than implementation mechanics.

Scene code remains the source of truth. Add beats with `BeatMixin` and simple
literal calls that Studio can inspect without rendering:

```python
from manim_kit.beats import BeatMixin
from manim_slides import Slide


class VectorScene(BeatMixin, Slide):
    def construct(self):
        self.beat("intro", label="Title")
        ...
        self.beat("resultant", label="Reveal resultant vector")
```

Beat IDs use lowercase ASCII snake_case or kebab-case, and should stay stable
after introduction because build artifacts and review notes may reference them.
For slide scenes, `beat()` preserves ordinary `next_slide()` boundaries after
the first beat. For regular Manim scenes, it maps to named Manim sections.
Targeted rendering is section-based; if a beat depends on earlier scene state,
render the full scene with saved sections and review the selected section
artifact.

## Assets And Imports

Deck-specific assets belong next to the deck, typically under
`decks/<deck_id>/assets/`. Shared reusable assets belong under a future shared
asset directory only when more than one deck actually depends on them.

Scene imports should be normal Python imports that work from the mounted project
root inside the runtime container. Avoid hidden dependencies on the current
working directory, local absolute paths, or generated render output.

## Migration Rules

Migrate legacy scenes selectively. A migrated scene should first be copied into
the new structure with minimal code changes, then registered in the catalog.
Do not rewrite a scene into a new abstraction just to catalog it.

Do not catalog mixed legacy scratch files directly. If a file contains unrelated
tutorials, absolute-path asset experiments, and reusable ideas, extract or
rewrite one coherent scene and document the parameter model in catalog metadata
and scene notes.

Only extract a helper into `manim_kit` when it recurs across scenes or
encapsulates difficult behavior such as Hebrew font setup, RTL alignment, slide
base behavior, or review-panel framing. Keep one-off teaching details inside the
scene.

Before adding a migrated scene to a delivery deck, run catalog validation and a
small render smoke check in the runtime container or devcontainer. Larger
render, build, and export workflows are separate phases and should not be mixed
into catalog registration.
