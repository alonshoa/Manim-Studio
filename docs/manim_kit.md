# Manim Kit

`manim_kit` is the small shared component layer for presentation scenes. It is
for recurring visual defaults and difficult Manim behavior, not a declarative
replacement for ordinary scene code.

## Public API

Use theme values when a scene needs a shared font, scale, or panel style:

```python
from manim import FadeIn
from manim_kit import DEFAULT_THEME, HebrewSlide, hebrew_text


class Intro(HebrewSlide):
    def construct(self):
        title = hebrew_text("...", scale=DEFAULT_THEME.title_scale)
        self.play(FadeIn(title))
```

Use `explanation_panel` when a grouped explanation needs the standard framed
layout:

```python
from manim import DOWN, LEFT, MathTex, VGroup
from manim_kit import explanation_panel

content = VGroup(
    MathTex(r"\vec a+\vec b=\vec v"),
    MathTex(r"\vec v=\begin{pmatrix}1\\3\end{pmatrix}"),
).arrange(DOWN, aligned_edge=LEFT)
panel = explanation_panel(content)
```

Use `rtl_column` for short right-aligned Hebrew text stacks:

```python
from manim_kit import DEFAULT_THEME, hebrew_text, rtl_column

items = rtl_column(
    hebrew_text("שלב ראשון", scale=DEFAULT_THEME.subtitle_scale),
    hebrew_text("הסבר קצר", scale=DEFAULT_THEME.caption_scale),
)
```

Current stable imports:

- `DEFAULT_THEME`, `StudioTheme`
- `hebrew_text`, `rtl_column`
- `explanation_panel`, `code_panel`
- `StudioSlide`, `HebrewSlide`
- `Beat`, `BeatMixin`

## Contribution Rules

- Extract only helpers that recur across scenes or isolate behavior that is easy
  to get wrong, such as Hebrew font setup, RTL alignment, slide bases, or panel
  framing.
- Keep scene-specific diagrams, constants, and teaching steps in the scene until
  at least two scenes need the same pattern.
- Keep the kit independent from `manim_studio`, CLI services, build metadata,
  MCP modules, and generated artifacts.
- Prefer ordinary Manim mobjects and Python functions over custom frameworks.

## Renderer Notes

- Hebrew text should use `hebrew_text` or an explicit Hebrew-capable font. The
  supported devcontainer installs DejaVu and Noto Hebrew fonts; verify with
  `studio doctor`.
- Cairo is the default renderer for the current pilot scenes. Treat OpenGL as a
  scene-specific opt-in until a render has been checked visually.
- `StudioSlide` and `HebrewSlide` preserve the `BeatMixin` workflow for
  `manim-slides`; use `self.beat(...)` for named conceptual slide boundaries.
- Panel helpers return `VGroup(frame, content)`, so scenes may animate the frame
  and content independently.
