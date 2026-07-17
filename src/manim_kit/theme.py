from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudioTheme:
    """Shared visual defaults for lightweight Manim Studio components."""

    body_font: str = "DejaVu Sans"
    hebrew_font: str = "DejaVu Sans"
    code_font: str = "DejaVu Sans Mono"
    title_scale: float = 1.2
    subtitle_scale: float = 0.45
    caption_scale: float = 0.4
    body_scale: float = 1.0
    code_font_size: int = 24
    rtl_column_buff: float = 0.28
    panel_buff: float = 0.25
    panel_corner_radius: float = 0.1
    panel_max_width: float = 4.6
    panel_stroke_color: str = "#888888"
    panel_stroke_opacity: float = 0.6
    neutral_text_color: str = "#FFFFFF"
    muted_text_color: str = "#888888"


DEFAULT_THEME = StudioTheme()
