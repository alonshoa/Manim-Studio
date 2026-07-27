# Pilot Scenes

These notes explain how to safely modify the migrated pilot scenes. The catalog
stores durable metadata; this page adds implementation intent.

## VectorsABtoV

Source:

```text
decks/matrix_work/vecs_slides.py
```

Purpose: verify Hebrew text, RTL font handling, `Slide` checkpoints, vector
construction, and tail-to-head animation.

Main knobs:

- `VECTOR_A`, `VECTOR_B`, and `VECTOR_V` control the plotted vectors.
- `manim_kit.DEFAULT_THEME.hebrew_font` controls Hebrew text rendering through
  the shared `hebrew_text` helper.
- The algebra panel text must stay consistent with the vector constants.

Named beats:

- `intro`
- `axes`
- `components`
- `algebra_panel`
- `tail_to_head`
- `resultant`
- `emphasis_loop`

Safe extensions: add more slide checkpoints, add more vector decomposition
steps, or extract a helper only after two scenes share the same pattern or the
helper isolates difficult behavior.

## BinaryCrossEntropyLoss

Source:

```text
decks/losses/cross_entropy.py
```

Purpose: verify a graph-heavy 2D scene with `Axes`, plotted curves, `MathTex`,
moving dots, and `always_redraw` labels.

Main knobs:

- `DOT_RUN_TIME` controls the moving probability marker pacing.
- Axis ranges define the visible probability and loss domain.
- Curve lambdas define the loss functions.

Safe extensions: add more highlighted probabilities or split the scene into
named beats later. Keep the first migrated version focused on renderability.

## ParametricCurve3D

Source:

```text
decks/matrix_work/parametric_curve_3d.py
```

Purpose: replace the mixed legacy `book_shelf.py` scratch file with one clear
3D pilot scene that has explicit parameters and no absolute-path assets.

Main knobs:

- `RADIUS` and `Z_SCALE` define the helix shape.
- `START_U`, `INITIAL_END_U`, and `END_U` define the reveal range.
- `CAMERA_PHI` and `CAMERA_THETA` define the camera orientation.

Safe extensions: add labels, show a second curve, or expose a different
parametric function. Do not reintroduce unrelated tutorial classes or
absolute-path image dependencies from `book_shelf.py`.
