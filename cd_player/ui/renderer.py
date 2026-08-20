"""Draws one frame onto the landscape canvas from a ViewState + Layout.
pygame-dependent (like icons.py), so not unit-tested -- verify visually.
"""

from __future__ import annotations

import logging

import pygame

from cd_player.ui.icons import DRAW_FUNCS
from cd_player.ui.layout import Layout
from cd_player.ui.view_model import ViewState, is_button_enabled

logger = logging.getLogger(__name__)

BLACK = (0, 0, 0)
WHITE = (235, 235, 235)
DIM = (150, 150, 150)
BUTTON_BG = (45, 45, 45)
BUTTON_BG_PRESSED = (95, 95, 95)
BUTTON_BG_DISABLED = (24, 24, 24)
ICON_DISABLED = (65, 65, 65)
ARTWORK_PLACEHOLDER = (30, 30, 30)

_TEXT_LINE_GAP = 22


class Renderer:
    def __init__(self) -> None:
        pygame.font.init()
        self._title_font = pygame.font.Font(None, 64)
        self._artist_font = pygame.font.Font(None, 42)
        self._track_font = pygame.font.Font(None, 52)
        self._artwork_cache: dict[str, pygame.Surface | None] = {}

    def render(
        self,
        canvas: pygame.Surface,
        view: ViewState,
        layout: Layout,
        pressed_button: str | None = None,
    ) -> None:
        canvas.fill(BLACK)
        if not view.has_disc:
            return

        self._draw_artwork(canvas, view, layout)
        self._draw_text(canvas, view, layout)
        self._draw_buttons(canvas, view, layout, pressed_button)

    def _draw_artwork(self, canvas: pygame.Surface, view: ViewState, layout: Layout) -> None:
        x, y, w, h = layout.artwork_rect
        image = None
        if view.artwork_path is not None:
            image = self._load_artwork(view.artwork_path, (w, h))
        if image is None:
            pygame.draw.rect(canvas, ARTWORK_PLACEHOLDER, (x, y, w, h), border_radius=12)
        else:
            canvas.blit(image, (x, y))

    def _load_artwork(self, path: str, size: tuple[int, int]) -> pygame.Surface | None:
        if path not in self._artwork_cache:
            try:
                loaded = pygame.image.load(path).convert()
                self._artwork_cache[path] = pygame.transform.smoothscale(loaded, size)
            except (pygame.error, FileNotFoundError):
                logger.exception("failed to load artwork %s", path)
                self._artwork_cache[path] = None
        return self._artwork_cache[path]

    def _draw_text(self, canvas: pygame.Surface, view: ViewState, layout: Layout) -> None:
        x, y, w, h = layout.text_rect
        prev_clip = canvas.get_clip()
        canvas.set_clip(pygame.Rect(x, y, w, h))

        cursor_y = y
        for text, font, color, centered in (
            (view.disc_title, self._title_font, WHITE, True),
            (view.disc_artist, self._artist_font, DIM, True),
            (view.current_track_title, self._track_font, WHITE, False),
        ):
            if not text:
                continue
            surf = font.render(text, True, color)
            line_x = x + (w - surf.get_width()) // 2 if centered else x
            canvas.blit(surf, (line_x, cursor_y))
            cursor_y += surf.get_height() + _TEXT_LINE_GAP

        canvas.set_clip(prev_clip)

    def _draw_buttons(
        self,
        canvas: pygame.Surface,
        view: ViewState,
        layout: Layout,
        pressed_button: str | None,
    ) -> None:
        for name, rect in layout.buttons.items():
            enabled = is_button_enabled(view, name)
            if not enabled:
                bg, icon_color = BUTTON_BG_DISABLED, ICON_DISABLED
            elif name == pressed_button:
                bg, icon_color = BUTTON_BG_PRESSED, WHITE
            else:
                bg, icon_color = BUTTON_BG, WHITE
            pygame.draw.rect(canvas, bg, rect, border_radius=16)
            DRAW_FUNCS[name](canvas, rect, icon_color)
