"""Pure layout math for the landscape canvas: where the artwork, text, and
buttons go. No pygame dependency, so geometry is unit-testable; actual
drawing lives in renderer.py.
"""

from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[int, int, int, int]  # (x, y, width, height)

BUTTON_NAMES = ("skip_backward", "play", "pause", "skip_forward", "eject")

_MARGIN = 40
_BUTTON_ROW_HEIGHT = 140
_BUTTON_GAP = 24


@dataclass(frozen=True)
class Layout:
    artwork_rect: Rect
    text_rect: Rect
    buttons: dict[str, Rect]  # name -> rect, keys are BUTTON_NAMES


def compute_layout(canvas_size: tuple[int, int]) -> Layout:
    width, height = canvas_size

    button_row_y = height - _MARGIN - _BUTTON_ROW_HEIGHT
    button_area_width = width - 2 * _MARGIN
    button_width = (button_area_width - _BUTTON_GAP * (len(BUTTON_NAMES) - 1)) // len(
        BUTTON_NAMES
    )

    buttons: dict[str, Rect] = {}
    x = _MARGIN
    for name in BUTTON_NAMES:
        buttons[name] = (x, button_row_y, button_width, _BUTTON_ROW_HEIGHT)
        x += button_width + _BUTTON_GAP

    artwork_size = button_row_y - 2 * _MARGIN
    artwork_rect = (_MARGIN, _MARGIN, artwork_size, artwork_size)

    text_x = _MARGIN * 2 + artwork_size
    text_rect = (text_x, _MARGIN, width - text_x - _MARGIN, button_row_y - 2 * _MARGIN)

    return Layout(artwork_rect=artwork_rect, text_rect=text_rect, buttons=buttons)


def button_at(layout: Layout, point: tuple[int, int]) -> str | None:
    px, py = point
    for name, (x, y, w, h) in layout.buttons.items():
        if x <= px < x + w and y <= py < y + h:
            return name
    return None
