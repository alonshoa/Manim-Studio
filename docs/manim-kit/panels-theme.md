# Panels And Theme

The Manim Kit theme and panel helpers keep repeated explanatory layouts
consistent across scenes.

## Theme Values

Use `DEFAULT_THEME` when a scene needs shared font, scale, color, or panel style
values:

```python
from manim_kit import DEFAULT_THEME

scale = DEFAULT_THEME.title_scale
```

## Explanation Panels

Use `explanation_panel` when grouped explanation content needs the standard
framed layout:

```python
from manim import DOWN, LEFT, MathTex, VGroup
from manim_kit import explanation_panel

content = VGroup(
    MathTex(r"\vec a+\vec b=\vec v"),
    MathTex(r"\vec v=\begin{pmatrix}1\\3\end{pmatrix}"),
).arrange(DOWN, aligned_edge=LEFT)

panel = explanation_panel(content)
```

## Code Panels

Use `code_panel` for code-like content that should share the standard panel
framing.

Panel helpers return `VGroup(frame, content)`, so scenes may animate the frame
and content independently.
