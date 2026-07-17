from __future__ import annotations

from typing import Any

from manim import SurroundingRectangle, Text, VGroup

from manim_kit.theme import DEFAULT_THEME, StudioTheme


def explanation_panel(
    content,
    *,
    theme: StudioTheme = DEFAULT_THEME,
    max_width: float | None = None,
    buff: float | None = None,
    stroke_color: str | None = None,
    stroke_opacity: float | None = None,
    corner_radius: float | None = None,
):
    """Wrap explanatory content in the shared Manim Studio panel frame."""

    width_limit = theme.panel_max_width if max_width is None else max_width
    if width_limit and content.width > width_limit:
        content.set_width(width_limit)

    frame = SurroundingRectangle(
        content,
        color=theme.panel_stroke_color if stroke_color is None else stroke_color,
        stroke_opacity=(
            theme.panel_stroke_opacity
            if stroke_opacity is None
            else stroke_opacity
        ),
        corner_radius=(
            theme.panel_corner_radius
            if corner_radius is None
            else corner_radius
        ),
        buff=theme.panel_buff if buff is None else buff,
    )
    return VGroup(frame, content)


def code_panel(
    content: str | Any,
    *,
    theme: StudioTheme = DEFAULT_THEME,
    max_width: float | None = None,
    **text_kwargs: Any,
):
    """Create a simple monospaced code block inside a shared panel frame."""

    if isinstance(content, str):
        text_kwargs.setdefault("font", theme.code_font)
        text_kwargs.setdefault("font_size", theme.code_font_size)
        content = Text(content, **text_kwargs)
    return explanation_panel(content, theme=theme, max_width=max_width)
