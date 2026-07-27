# Hebrew And RTL

Manim Studio includes helpers for Hebrew text and short right-aligned text
stacks.

## Fonts

The supported runtime installs DejaVu and Noto Hebrew fonts. Verify font
availability with:

```bash
studio doctor
```

Hebrew text should use `hebrew_text` or an explicit Hebrew-capable font.

## Hebrew Text

```python
from manim import FadeIn
from manim_kit import DEFAULT_THEME, hebrew_text

title = hebrew_text("...", scale=DEFAULT_THEME.title_scale)
self.play(FadeIn(title))
```

## RTL Columns

Use `rtl_column` for short right-aligned Hebrew text stacks:

```python
from manim_kit import DEFAULT_THEME, hebrew_text, rtl_column

items = rtl_column(
    hebrew_text("First step", scale=DEFAULT_THEME.subtitle_scale),
    hebrew_text("Short explanation", scale=DEFAULT_THEME.caption_scale),
)
```

The helper is intended for compact teaching labels and explanatory text, not for
full document layout.
