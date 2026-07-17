# Pilot Scene Notes

These notes explain how to safely modify the migrated pilot scenes. The catalog
stores the durable metadata; this document adds implementation intent.

## VectorsABtoV

Source: `decks/matrix_work/vecs_slides.py`

Purpose: verify Hebrew text, RTL font handling, `Slide` checkpoints, vector
construction, and tail-to-head animation.

Main knobs:

- `VECTOR_A`, `VECTOR_B`, and `VECTOR_V` control the plotted vectors.
- `HEBREW_FONT` controls Hebrew text rendering.
- The algebra panel text must be kept in sync with the vector constants.

Named beats:

- `intro`: title.
- `axes`: coordinate plane.
- `components`: show vector components.
- `algebra_panel`: introduce the algebra panel.
- `tail_to_head`: move vector `b` to the head of vector `a`.
- `resultant`: reveal vector `v`.
- `emphasis_loop`: looped emphasis on the resultant.

Safe extensions: add more slide checkpoints, add more vector decomposition
steps, or extract a helper only after two scenes share the same pattern.

## BinaryCrossEntropyLoss

Source: `decks/losses/cross_entropy.py`

Purpose: verify a graph-heavy 2D scene with `Axes`, plotted curves,
`MathTex`, moving dots, and `always_redraw` labels.

Main knobs:

- `DOT_RUN_TIME` controls the moving probability marker pacing.
- The axis ranges define the visible probability and loss domain.
- The curve lambdas define the loss functions.

Safe extensions: add more highlighted probabilities or split the scene into
named beats later. Keep the first migrated version focused on renderability.

## ParametricCurve3D

Source: `decks/matrix_work/parametric_curve_3d.py`

Purpose: replace the mixed legacy `book_shelf.py` scratch file with one clear
3D pilot scene that has explicit parameters and no absolute-path assets.

Main knobs:

- `RADIUS` and `Z_SCALE` define the helix shape.
- `START_U`, `INITIAL_END_U`, and `END_U` define the reveal range.
- `CAMERA_PHI` and `CAMERA_THETA` define the camera orientation.

Safe extensions: add labels, show a second curve, or expose a different
parametric function. Do not reintroduce unrelated tutorial classes or
absolute-path image dependencies from `book_shelf.py`.
