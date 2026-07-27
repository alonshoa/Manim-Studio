# Catalog

`catalog/scenes.yaml` is descriptive metadata. It registers existing Python
scene classes so Studio can inspect, validate, render, build, and expose them
through MCP.

Scene code remains the source of truth. Catalog metadata should describe the
scene; it should not try to encode the animation.

## Required Fields

Each scene entry must include:

- `deck_id`
- `scene_id`
- `source_path`
- `class_name`
- `base_scene_type`
- `renderer`
- `language`

Use `renderer: manim` for normal Manim Community scenes and
`renderer: manim-slides` for scenes rendered through Manim Slides.

`base_scene_type` should name the main scene base class, such as `Scene`,
`MovingCameraScene`, `ThreeDScene`, or `Slide`.

## Optional Planning Fields

Pilot scenes and migrated scenes should include these fields when known:

- `description`
- `asset_notes`
- `font_notes`
- `parameter_notes`
- `render_command`
- `baseline_path`
- `migration_notes`

`parameter_notes` should name the knobs a maintainer can safely change: matrix
values, vectors, graph ranges, tracker ranges, camera angles, font choices, and
teaching intent.

`baseline_path` should point to a tracked directory containing curated preview
frames or notes describing expected baseline captures. Do not move full Manim
output directories into `baselines/`.

## IDs And Targets

Deck IDs and scene IDs use lowercase kebab-case or snake_case ASCII. Keep IDs
stable after they appear in `catalog/scenes.yaml`.

Scene targets use:

```text
<deck_id>/<scene_id>
```

Examples:

```bash
studio validate examples/square_to_circle
studio render losses/binary_cross_entropy --profile draft
```

Deck targets use only:

```text
<deck_id>
```

Example:

```bash
studio build examples --profile review
```

## Validation

Validate the whole catalog:

```bash
studio catalog validate
```

Require stricter metadata:

```bash
studio catalog validate --strict-metadata
```

Validate one target:

```bash
studio validate matrix_work/vectors_ab_to_v
```
