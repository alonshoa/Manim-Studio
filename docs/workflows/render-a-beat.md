# Render A Beat

Beats are named conceptual segments inside a registered scene. They make long
slide scenes easier to review and iterate on.

## Discover Beats

```bash
studio beats matrix_work/vectors_ab_to_v
```

The current vector slide scene exposes:

- `intro`
- `axes`
- `components`
- `algebra_panel`
- `tail_to_head`
- `resultant`
- `emphasis_loop`

## Render One Beat

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```

The command validates that the beat exists before rendering. If the beat ID is
unknown, the CLI prints the available beats.

## Authoring Beats

Use `BeatMixin` and simple literal calls:

```python
from manim_kit.beats import BeatMixin
from manim_slides import Slide


class VectorScene(BeatMixin, Slide):
    def construct(self):
        self.beat("intro", label="Title")
        self.beat("resultant", label="Reveal resultant vector")
```

Beat IDs use lowercase ASCII snake_case or kebab-case and should describe
teaching intent, not implementation mechanics.

For slide scenes, `beat()` preserves ordinary `next_slide()` boundaries after
the first beat. For regular Manim scenes, it maps to named Manim sections.

Targeted rendering is section-aware. If a beat depends on earlier scene state,
render the full scene with saved sections and review the selected section
artifact.
