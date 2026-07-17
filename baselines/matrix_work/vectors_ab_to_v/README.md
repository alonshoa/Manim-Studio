# Vectors AB To V Baseline

Render command:

```bash
manim-slides render -ql decks/matrix_work/vecs_slides.py VectorsABtoV
```

Manual review checklist completed on 2026-07-17 in the devcontainer:

- title
- axes and vector components
- algebra panel
- tail-to-head move
- resultant reveal and emphasis loop

Review tolerance for the `manim_kit` migration: no material regression in layout,
typography, animation order, or panel framing versus the prior baseline. The
helper extraction may change implementation structure only.

Result: passed. The render produced the expected 7-slide flow, and the reviewed
frames showed no material layout, typography, animation-order, or panel-framing
regression.
