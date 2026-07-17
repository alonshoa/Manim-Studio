from __future__ import annotations

import os
from dataclasses import dataclass


TARGET_BEAT_ENV = "MANIM_STUDIO_BEAT"


@dataclass(frozen=True)
class Beat:
    id: str
    label: str
    source_line: int | None = None


class BeatMixin:
    """Lightweight named-beat helper for Manim and manim-slides scenes."""

    def beat(self, beat_id: str, label: str | None = None, **slide_kwargs) -> None:
        if not isinstance(beat_id, str) or not beat_id.strip():
            raise ValueError("beat_id must be a non-empty string")

        beat_label = label or beat_id
        target_beat = os.environ.get(TARGET_BEAT_ENV)
        caller_skip = bool(slide_kwargs.pop("skip_animations", False))
        skip_animations = caller_skip or (
            target_beat is not None and target_beat != beat_id
        )
        section_name = _section_name(beat_id, beat_label)

        beats = getattr(self, "_manim_studio_beats", None)
        if beats is None:
            beats = []
            setattr(self, "_manim_studio_beats", beats)
        beats.append(Beat(id=beat_id, label=beat_label))

        has_started = bool(getattr(self, "_manim_studio_started_beats", False))
        if not has_started:
            setattr(self, "_manim_studio_started_beats", True)
            if hasattr(self, "next_section"):
                self.next_section(name=section_name, skip_animations=skip_animations)
            return

        if hasattr(self, "next_slide"):
            self.next_slide(
                name=section_name,
                skip_animations=skip_animations,
                **slide_kwargs,
            )
            return

        if hasattr(self, "next_section"):
            self.next_section(name=section_name, skip_animations=skip_animations)
            return

        raise AttributeError("beat() requires next_section() or next_slide() support")


def _section_name(beat_id: str, label: str) -> str:
    if label == beat_id:
        return beat_id
    return f"{beat_id}: {label}"
