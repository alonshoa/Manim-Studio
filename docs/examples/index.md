# Examples

The catalog currently registers five scenes across three decks. These examples
exercise the rendering paths Manim Studio needs to support before deeper
automation is added.

## Registered Examples

| Target | Renderer | Purpose |
| --- | --- | --- |
| `examples/square_to_circle` | `manim` | Minimal Cairo smoke scene |
| `examples/basic_slide` | `manim-slides` | Minimal Manim Slides smoke scene |
| `matrix_work/vectors_ab_to_v` | `manim-slides` | Hebrew vector addition slide scene |
| `matrix_work/parametric_curve_3d` | `manim` | 3D parametric curve pilot |
| `losses/binary_cross_entropy` | `manim` | Graph-heavy 2D loss function pilot |

List the catalog locally:

```bash
studio list
```

Render the smallest scene:

```bash
studio render examples/square_to_circle --profile draft
```

## Baselines

Curated review notes and snapshots belong under `baselines/`. Full generated
Manim output should stay in `builds/`, `media/`, or `slides/`, which are
local-only and ignored by Git.
