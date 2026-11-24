# Vector distances — adapting an existing presentation

Transform an existing Hebrew PowerPoint into an animated mathematics lesson. The instructor retained the topic sequence while revising geometry, timing and algebraic emphasis.

**8 scenes · 86 teaching steps · 480p draft · Hebrew teaching content**

## Showcase

The original was a 17-slide lesson according to the recorded review. The final deck changes the initial numerical example to two-dimensional vectors to improve visibility. This is an adaptation, not a slide-for-slide conversion.

The continuous video and original and final PowerPoint files are prepared separately for publication (see [example assets](assets-publication.md)). Use the final PowerPoint in slide-show mode for teacher-controlled advancement.

## Guided walkthrough

The following selections are edited English translations of recorded Hebrew messages, not a recreated conversation. Event numbers identify captured messages. Scene names refer to final exported scenes, not historical drafts.

### 1. Start with existing material

**Instructor — event 276**

> I attached the presentation. It is about vectors and distance metrics. Keep roughly the same content flow, but use Manim Studio animations and synchronize the algebra with the animations.

**Codex — event 288**

> I reviewed the 17 slides. I suggest retaining the sequence and building each algebraic step together with its corresponding geometric action.

**Scene:** DifferenceVector.

**What to learn:** Start from existing teaching material rather than recreating the curriculum.

### 2. Review the first draft and improve the explanation

**Instructor — event 370**

> Separate u and v a little more. Try (1,1) and (3,-1). For L2, provide more context before showing the demonstration.

**Codex — event 456**

> The revised L2 scene explains that each coordinate difference creates a leg of the triangle, and then uses Pythagoras to compute the hypotenuse.

**Scene:** L2Plane.

**What to learn:** This response follows a further clarification at event 434; the final scene reflects both requests.

### 3. Reuse the example for L1

**Instructor — event 460**

> Do the same thing for L1 and adapt the formulas and explanations. Use the same points.

**Codex — event 488**

> The L1 scene uses the same points, movement along the axes synchronized with the formula, and absolute values.

**Scene:** L1Plane.

**What to learn:** Keeping the inputs fixed makes the difference between metrics visible.

### 4. Control the algebraic emphasis

**Instructor — event 498**

> Show the differences row by row. Highlight the indices of d, and the square root.

**Codex — event 536**

> L1 is on the right and L2 on the left. The calculations are revealed row by row, with the indices and the radical highlighted.

**Scene:** DistanceComparison.

**What to learn:** The teacher specifies exactly what visual emphasis should support the mathematical distinction.

### 5. Refine the geometric intuition

**Instructor — event 620**

> Show a dashed line that creates the projection, highlight it, then remove it and continue. Also give some intuition for why we use this projection.

**Codex — event 652**

> The projection isolates the part of v acting in the direction of u. The dashed perpendicular is constructed and highlighted, then removed before continuing.

**Scene:** InnerProduct.

**What to learn:** A later request (event 656) also adds numerical equivalence of component and geometric formulas.

### 6. Extend the lesson and export

**Instructor — event 697**

> Move from the dot product to cosine similarity and then cosine distance. Show a visual example that is closer by cosine but farther by L2, then summarize the three metrics.

**Codex — event 767**

> The combined presentation is ready, including cosine distance, visual comparison with L2, and a summary of all three metrics.

**Scene:** CosineVsL2.

**What to learn:** The delivered version is a 480p draft; the recorded export contained 86 teaching steps.

## Explore every scene

| Scene | Focus |
| --- | --- |
| DifferenceVector | Coordinate differences |
| L2Plane | Euclidean distance |
| L1Plane | Manhattan distance |
| DistanceComparison | Algebraic comparison |
| InnerProduct | Projection and dot product |
| CosineDistance | Cosine similarity and distance |
| CosineVsL2 | Direction versus magnitude |
| MetricsSummary | Compare all three metrics |

## Reuse the project

The prepared project archive includes sources, rendered slides and the original PowerPoint. The scene catalog and both storyboards accompany it. Use a compatible Manim Studio checkout and its [environment setup](../getting-started/installation.md). These historical exports are not independently tested standalone installers.

## Capture and validation notes

The research archive contains 15 captured user prompts and 45 model response events. The capture is incomplete; some opening turns and intermediate file versions may be missing. The walkthrough does not claim to reconstruct them.
