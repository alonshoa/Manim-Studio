from __future__ import annotations

from manim_slides import Slide

from manim_kit.beats import BeatMixin
from manim_kit.theme import DEFAULT_THEME, StudioTheme


class StudioSlide(BeatMixin, Slide):
    """Base class for Studio slide scenes with shared theme access."""

    theme: StudioTheme = DEFAULT_THEME


class HebrewSlide(StudioSlide):
    """Studio slide base class for Hebrew/RTL presentation scenes."""

    language = "he"
