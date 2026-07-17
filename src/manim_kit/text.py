from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from manim import DOWN, RIGHT, Mobject, Text, VGroup

from manim_kit.theme import DEFAULT_THEME, StudioTheme


def hebrew_text(
    text: str,
    *,
    theme: StudioTheme = DEFAULT_THEME,
    font: str | None = None,
    scale: float | None = None,
    **kwargs: Any,
):
    """Create Hebrew-capable Manim text using the shared theme defaults."""

    kwargs.setdefault("font", font or theme.hebrew_font)
    mobject = Text(text, **kwargs)
    mobject.scale(theme.body_scale if scale is None else scale)
    return mobject


def rtl_column(
    *items,
    theme: StudioTheme = DEFAULT_THEME,
    buff: float | None = None,
    aligned_edge=RIGHT,
):
    """Arrange mobjects vertically with right-edge alignment for RTL layouts."""

    content = _normalize_items(items)
    column = VGroup(*content)
    if content:
        column.arrange(
            DOWN,
            aligned_edge=aligned_edge,
            buff=theme.rtl_column_buff if buff is None else buff,
        )
    return column


def _normalize_items(items: tuple) -> list:
    if len(items) == 1 and _is_item_collection(items[0]):
        return list(items[0])
    return list(items)


def _is_item_collection(value) -> bool:
    if isinstance(value, Mobject):
        return False
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))
