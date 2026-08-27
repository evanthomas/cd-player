"""Procedurally-drawn button icons -- no image assets, so nothing to load
at startup and no icon-license questions. Each function draws its icon
centered inside `rect` (x, y, w, h) using `color`. Depends on pygame, so
(like renderer.py/app.py) this isn't unit-tested -- verify visually on the
real screen.
"""

from __future__ import annotations

import math

import pygame

from cd_player.ui.layout import Rect

_PADDING_RATIO = 0.28


def _inset_square(rect: Rect) -> tuple[float, float, float]:
    x, y, w, h = rect
    size = min(w, h) * (1 - 2 * _PADDING_RATIO)
    return x + w / 2, y + h / 2, size


def draw_play(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    points = [(cx - half, cy - half), (cx - half, cy + half), (cx + half, cy)]
    pygame.draw.polygon(surface, color, points)


def draw_pause(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    bar_w = size * 0.28
    gap = size * 0.2
    left_x = cx - gap / 2 - bar_w
    right_x = cx + gap / 2
    pygame.draw.rect(surface, color, (left_x, cy - half, bar_w, size))
    pygame.draw.rect(surface, color, (right_x, cy - half, bar_w, size))


def draw_skip_forward(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    bar_w = size * 0.12
    tri_w = (size - bar_w) / 2
    x0 = cx - half
    pygame.draw.polygon(
        surface, color, [(x0, cy - half), (x0, cy + half), (x0 + tri_w, cy)]
    )
    x1 = x0 + tri_w
    pygame.draw.polygon(
        surface, color, [(x1, cy - half), (x1, cy + half), (x1 + tri_w, cy)]
    )
    pygame.draw.rect(surface, color, (cx + half - bar_w, cy - half, bar_w, size))


def draw_skip_backward(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    bar_w = size * 0.12
    tri_w = (size - bar_w) / 2
    x0 = cx + half
    pygame.draw.polygon(
        surface, color, [(x0, cy - half), (x0, cy + half), (x0 - tri_w, cy)]
    )
    x1 = x0 - tri_w
    pygame.draw.polygon(
        surface, color, [(x1, cy - half), (x1, cy + half), (x1 - tri_w, cy)]
    )
    pygame.draw.rect(surface, color, (cx - half, cy - half, bar_w, size))


def draw_eject(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    tri_h = size * 0.55
    gap = size * 0.12
    bar_h = size * 0.22
    pygame.draw.polygon(
        surface,
        color,
        [(cx, cy - half), (cx - half, cy - half + tri_h), (cx + half, cy - half + tri_h)],
    )
    bar_y = cy - half + tri_h + gap
    pygame.draw.rect(surface, color, (cx - half, bar_y, size, bar_h))


def draw_back(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    half = size / 2
    points = [(cx + half, cy - half), (cx + half, cy + half), (cx - half, cy)]
    pygame.draw.polygon(surface, color, points)


def draw_settings(surface: pygame.Surface, rect: Rect, color) -> None:
    cx, cy, size = _inset_square(rect)
    outer_r = size / 2
    inner_r = outer_r * 0.6
    tooth_count = 8
    half_width = (math.pi / tooth_count) * 0.4
    for i in range(tooth_count):
        angle = 2 * math.pi * i / tooth_count
        a0, a1 = angle - half_width, angle + half_width
        points = [
            (cx + inner_r * math.cos(a0), cy + inner_r * math.sin(a0)),
            (cx + outer_r * math.cos(a0), cy + outer_r * math.sin(a0)),
            (cx + outer_r * math.cos(a1), cy + outer_r * math.sin(a1)),
            (cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1)),
        ]
        pygame.draw.polygon(surface, color, points)
    pygame.draw.circle(surface, color, (cx, cy), inner_r)


DRAW_FUNCS = {
    "play": draw_play,
    "pause": draw_pause,
    "skip_forward": draw_skip_forward,
    "skip_backward": draw_skip_backward,
    "eject": draw_eject,
    "settings": draw_settings,
}
