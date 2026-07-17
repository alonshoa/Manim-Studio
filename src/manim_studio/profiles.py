from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderProfile:
    name: str
    quality_flag: str
    description: str
    expected_artifacts: tuple[str, ...]

    def command_args(self) -> tuple[str, ...]:
        return (self.quality_flag,)


PROFILES: dict[str, RenderProfile] = {
    "draft": RenderProfile(
        name="draft",
        quality_flag="-ql",
        description="Fast low-quality render for iteration.",
        expected_artifacts=("video", "logs", "metadata"),
    ),
    "review": RenderProfile(
        name="review",
        quality_flag="-qm",
        description="Medium-quality render for layout, pacing, and review.",
        expected_artifacts=("video", "logs", "metadata", "review-frames"),
    ),
    "final": RenderProfile(
        name="final",
        quality_flag="-qh",
        description="High-quality render for delivery artifacts.",
        expected_artifacts=("video", "logs", "metadata", "exports"),
    ),
}


def get_profile(name: str) -> RenderProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown render profile {name!r}; expected one of: {valid}") from exc


def profile_names() -> tuple[str, ...]:
    return tuple(sorted(PROFILES))
