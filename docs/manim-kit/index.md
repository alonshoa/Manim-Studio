# Manim Kit

`manim_kit` is the small shared component layer for presentation scenes. It is
for recurring visual defaults and difficult Manim behavior, not a declarative
replacement for ordinary scene code.

## Stable Imports

Current stable imports:

- `DEFAULT_THEME`, `StudioTheme`
- `hebrew_text`, `rtl_column`
- `RTLWrite`
- `explanation_panel`, `code_panel`
- `StudioSlide`, `HebrewSlide`
- `Beat`, `BeatMixin`

## Basic Use

Use theme values when a scene needs a shared font, scale, or panel style:

```python
from manim import FadeIn
from manim_kit import DEFAULT_THEME, HebrewSlide, hebrew_text


class Intro(HebrewSlide):
    def construct(self):
        title = hebrew_text("...", scale=DEFAULT_THEME.title_scale)
        self.play(FadeIn(title))
```

## Contribution Rule

Extract helpers only when they recur across scenes or isolate behavior that is
easy to get wrong, such as Hebrew font setup, RTL alignment, slide base behavior,
or review-panel framing.

Keep scene-specific diagrams, constants, and teaching steps in the scene until
at least two scenes need the same pattern.

Keep `manim_kit` independent from `manim_studio`, CLI services, build metadata,
MCP modules, and generated artifacts.
