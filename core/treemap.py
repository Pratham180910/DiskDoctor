from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    label: str
    value: int
    x: float
    y: float
    width: float
    height: float


def layout(items: list[tuple[str, int]], width: float, height: float) -> list[Rect]:
    """Simple slice-and-dice treemap. Areas are proportional to values."""
    positive = [(label, max(0, value)) for label, value in items if value > 0]
    total = sum(value for _, value in positive)
    if not total or width <= 0 or height <= 0:
        return []
    result: list[Rect] = []
    x, y, w, h = 0.0, 0.0, width, height
    horizontal = width >= height
    for index, (label, value) in enumerate(positive):
        fraction = value / sum(v for _, v in positive[index:])
        if horizontal:
            cell_w = w * fraction
            result.append(Rect(label, value, x, y, cell_w, h))
            x += cell_w; w -= cell_w
        else:
            cell_h = h * fraction
            result.append(Rect(label, value, x, y, w, cell_h))
            y += cell_h; h -= cell_h
        horizontal = not horizontal
    return result
