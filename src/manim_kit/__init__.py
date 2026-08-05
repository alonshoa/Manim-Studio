"""Reusable presentation components for Manim Studio scenes."""

from manim_kit.beats import Beat, BeatMixin

__all__ = [
    "Beat",
    "BeatMixin",
    "DEFAULT_THEME",
    "HebrewSlide",
    "RTLWrite",
    "StudioSlide",
    "StudioTheme",
    "code_panel",
    "explanation_panel",
    "hebrew_text",
    "rtl_column",
]


def __getattr__(name: str):
    if name in {"DEFAULT_THEME", "StudioTheme"}:
        from manim_kit.theme import DEFAULT_THEME, StudioTheme

        return {"DEFAULT_THEME": DEFAULT_THEME, "StudioTheme": StudioTheme}[name]

    if name in {"hebrew_text", "rtl_column"}:
        from manim_kit.text import hebrew_text, rtl_column

        return {"hebrew_text": hebrew_text, "rtl_column": rtl_column}[name]

    if name == "RTLWrite":
        from manim_kit.animations import RTLWrite

        return RTLWrite

    if name in {"code_panel", "explanation_panel"}:
        from manim_kit.panels import code_panel, explanation_panel

        return {
            "code_panel": code_panel,
            "explanation_panel": explanation_panel,
        }[name]

    if name in {"HebrewSlide", "StudioSlide"}:
        from manim_kit.slides import HebrewSlide, StudioSlide

        return {"HebrewSlide": HebrewSlide, "StudioSlide": StudioSlide}[name]

    raise AttributeError(f"module 'manim_kit' has no attribute {name!r}")
