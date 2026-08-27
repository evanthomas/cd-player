"""Pure layout math for the landscape canvas: where the artwork, text, and
buttons go. No pygame dependency, so geometry is unit-testable; actual
drawing lives in renderer.py.
"""

from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[int, int, int, int]  # (x, y, width, height)

BUTTON_NAMES = ("skip_backward", "play", "pause", "skip_forward", "eject", "settings")

_MARGIN = 40
_BUTTON_ROW_HEIGHT = 140
_BUTTON_GAP = 24

MAX_SETTINGS_SPEAKER_ROWS = 8  # non-scrolling -- more than covers a typical home

_SETTINGS_BACK_HEIGHT = 70
_SETTINGS_ROW_HEIGHT = 50
_SETTINGS_ROW_GAP = 12
_SETTINGS_CHECKBOX_SIZE = 40
_SETTINGS_SLIDER_HEIGHT = 50


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


@dataclass(frozen=True)
class SettingsLayout:
    back_rect: Rect
    speaker_rows: list[tuple[Rect, Rect]]  # (checkbox_rect, label_rect), index-aligned to the speaker list
    volume_slider_rect: Rect


def compute_settings_layout(canvas_size: tuple[int, int], speaker_count: int) -> SettingsLayout:
    """Non-scrolling: only the first MAX_SETTINGS_SPEAKER_ROWS speakers get a
    row. Callers must index their speaker list the same way (row i <->
    speaker i)."""
    width, height = canvas_size
    speaker_count = min(speaker_count, MAX_SETTINGS_SPEAKER_ROWS)

    back_rect = (_MARGIN, _MARGIN, 160, _SETTINGS_BACK_HEIGHT)

    list_top = _MARGIN + _SETTINGS_BACK_HEIGHT + _SETTINGS_ROW_GAP
    row_pitch = _SETTINGS_ROW_HEIGHT + _SETTINGS_ROW_GAP
    checkbox_x = _MARGIN
    label_x = checkbox_x + _SETTINGS_CHECKBOX_SIZE + _SETTINGS_ROW_GAP
    label_width = width - label_x - _MARGIN

    speaker_rows: list[tuple[Rect, Rect]] = []
    for i in range(speaker_count):
        row_y = list_top + i * row_pitch
        checkbox_y = row_y + (_SETTINGS_ROW_HEIGHT - _SETTINGS_CHECKBOX_SIZE) // 2
        checkbox_rect = (checkbox_x, checkbox_y, _SETTINGS_CHECKBOX_SIZE, _SETTINGS_CHECKBOX_SIZE)
        label_rect = (label_x, row_y, label_width, _SETTINGS_ROW_HEIGHT)
        speaker_rows.append((checkbox_rect, label_rect))

    slider_y = height - _MARGIN - _SETTINGS_SLIDER_HEIGHT
    volume_slider_rect = (_MARGIN, slider_y, width - 2 * _MARGIN, _SETTINGS_SLIDER_HEIGHT)

    return SettingsLayout(
        back_rect=back_rect, speaker_rows=speaker_rows, volume_slider_rect=volume_slider_rect
    )


# ("back", None) | ("speaker_toggle", index) | ("volume_slider", None)
SettingsHit = tuple[str, int | None]


def settings_hit_at(layout: SettingsLayout, point: tuple[int, int]) -> SettingsHit | None:
    px, py = point

    x, y, w, h = layout.back_rect
    if x <= px < x + w and y <= py < y + h:
        return ("back", None)

    for i, (checkbox_rect, label_rect) in enumerate(layout.speaker_rows):
        for rx, ry, rw, rh in (checkbox_rect, label_rect):
            if rx <= px < rx + rw and ry <= py < ry + rh:
                return ("speaker_toggle", i)

    x, y, w, h = layout.volume_slider_rect
    if x <= px < x + w and y <= py < y + h:
        return ("volume_slider", None)

    return None


def volume_from_slider_x(rect: Rect, x: int) -> int:
    """Maps a touch/drag x-coordinate onto a 0-100 volume level, clamped to
    the slider's own bounds."""
    sx, _sy, sw, _sh = rect
    if sw <= 0:
        return 0
    fraction = max(0.0, min(1.0, (x - sx) / sw))
    return round(fraction * 100)
