"""Mapping data values onto SVG pixels.

A class rather than a pair of closures because closures inside a chart function cannot be
tested on their own, and the axis arithmetic is the part of a chart most worth testing:
every off-by-one in a plot is in here, and none of it is visible by looking at the
finished picture.
"""

from __future__ import annotations

import math


class Scale:
    """Data coordinates to pixel coordinates for one chart."""

    def __init__(
        self,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        width: int,
        height: int,
        pad_left: int,
        pad_right: int,
        pad_top: int,
        pad_bottom: int,
        integral: bool = False,
    ) -> None:
        # A flat series has an empty range, which would divide by zero. Widening by one
        # puts the line halfway up its own panel, which reads correctly as "unchanging".
        self.x_min = x_min
        self.x_max = x_max if x_max > x_min else x_min + 1
        self.y_min = y_min
        self.y_max = y_max if y_max > y_min else y_min + 1
        self._width = width
        self._height = height
        self._pad_left = pad_left
        self._pad_right = pad_right
        self._pad_top = pad_top
        self._pad_bottom = pad_bottom
        # Counts cannot take a fractional tick. Half of these charts are counts of
        # stations, vehicles or actions, and a range of 0 to 2 was getting ticks every
        # 0.5, which the label formatter then rounded, printing "2" twice.
        self._integral = integral

    def x(self, value: float) -> float:
        span = self._width - self._pad_left - self._pad_right
        return self._pad_left + (value - self.x_min) / (self.x_max - self.x_min) * span

    def y(self, value: float) -> float:
        span = self._height - self._pad_top - self._pad_bottom
        return (
            self._height
            - self._pad_bottom
            - (value - self.y_min) / (self.y_max - self.y_min) * span
        )

    def ticks(self, count: int) -> list[float]:
        """Round y values covering the range, snapped to a 1, 2 or 5 multiple.

        Snapping matters for the small ranges this dashboard is full of. A rating between
        28 and 31 wants ticks at 28, 29, 30, 31 rather than at 28.4 and 30.7.
        """
        low, high = self.y_min, self.y_max
        if high <= low:
            return [low]
        raw = (high - low) / max(1, count)
        if raw <= 0:
            return [low, high]
        magnitude = 10.0 ** math.floor(math.log10(raw))
        normalised = raw / magnitude
        if normalised < 1.5:
            step = magnitude
        elif normalised < 3:
            step = 2 * magnitude
        elif normalised < 7:
            step = 5 * magnitude
        else:
            step = 10 * magnitude
        if self._integral:
            step = max(1.0, round(step))
        out: list[float] = []
        value = math.floor(low / step) * step
        while value <= high + step * 1e-9:
            if value >= low - step * 1e-9:
                out.append(round(value, 10))
            value += step
        return out or [low, high]
