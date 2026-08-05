from __future__ import annotations

from collections.abc import Callable
from statistics import median
from typing import Any

from manim import Mobject, Write, linear


class RTLWrite(Write):
    """Write a mobject in visual right-to-left order.

    This keeps Manim's ``Write`` drawing behavior while changing the lag order
    for text whose natural reveal direction is RTL.
    """

    def __init__(
        self,
        vmobject: Mobject,
        rate_func: Callable[[float], float] = linear,
        *,
        row_tolerance: float | None = None,
        **kwargs: Any,
    ) -> None:
        self.row_tolerance = row_tolerance
        self._original_submobjects: list[Mobject] | None = None
        kwargs.pop("reverse", None)
        super().__init__(vmobject, rate_func=rate_func, reverse=False, **kwargs)

    def begin(self) -> None:
        self._original_submobjects = list(self.mobject.submobjects)
        self.mobject.submobjects = _rtl_visual_order(
            self.mobject.submobjects,
            row_tolerance=self.row_tolerance,
        )
        super().begin()

    def finish(self) -> None:
        super().finish()
        if self._original_submobjects is not None:
            self.mobject.submobjects = self._original_submobjects
            self._original_submobjects = None


def _rtl_visual_order(
    submobjects: list[Mobject],
    *,
    row_tolerance: float | None = None,
) -> list[Mobject]:
    if len(submobjects) < 2:
        return list(submobjects)

    tolerance = _row_tolerance(submobjects, row_tolerance)
    rows: list[list[Mobject]] = []
    row_centers: list[float] = []

    for submobject in sorted(submobjects, key=lambda mobject: -mobject.get_center()[1]):
        y = submobject.get_center()[1]
        row_index = _matching_row(row_centers, y, tolerance)
        if row_index is None:
            rows.append([submobject])
            row_centers.append(y)
        else:
            rows[row_index].append(submobject)
            row_centers[row_index] = _average_y(rows[row_index])

    ordered: list[Mobject] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda mobject: -mobject.get_center()[0]))
    return ordered


def _row_tolerance(
    submobjects: list[Mobject],
    configured_tolerance: float | None,
) -> float:
    if configured_tolerance is not None:
        return configured_tolerance

    heights = [submobject.height for submobject in submobjects if submobject.height > 0]
    if not heights:
        return 1e-6
    return max(float(median(heights)) * 0.5, 1e-6)


def _matching_row(
    row_centers: list[float],
    y: float,
    tolerance: float,
) -> int | None:
    for index, row_y in enumerate(row_centers):
        if abs(row_y - y) <= tolerance:
            return index
    return None


def _average_y(row: list[Mobject]) -> float:
    return sum(submobject.get_center()[1] for submobject in row) / len(row)
