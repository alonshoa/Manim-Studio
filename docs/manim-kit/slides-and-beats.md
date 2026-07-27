# Slides And Beats

`StudioSlide` and `HebrewSlide` preserve the `BeatMixin` workflow for Manim
Slides.

## Slide Bases

Use `StudioSlide` for shared slide behavior and `HebrewSlide` when the scene
needs the default Hebrew-capable text path.

```python
from manim_kit import HebrewSlide


class Intro(HebrewSlide):
    def construct(self):
        ...
```

## BeatMixin

Use `BeatMixin` when a scene should expose named conceptual checkpoints:

```python
from manim_kit import BeatMixin
from manim_slides import Slide


class VectorScene(BeatMixin, Slide):
    def construct(self):
        self.beat("intro", label="Title")
        self.beat("resultant", label="Reveal resultant vector")
```

For slide scenes, `beat()` preserves ordinary `next_slide()` boundaries after
the first beat. For regular Manim scenes, it maps to named Manim sections.

List discovered beats:

```bash
studio beats matrix_work/vectors_ab_to_v
```

Render one beat:

```bash
studio render matrix_work/vectors_ab_to_v --profile draft --beat resultant
```
