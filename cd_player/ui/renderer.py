"""Draws one frame onto the landscape canvas from a ViewState + Layout.
pygame-dependent (like icons.py), so not unit-tested -- verify visually.
"""

from __future__ import annotations

import logging
import time

import pygame

from cd_player.ui.icons import DRAW_FUNCS, draw_back
from cd_player.ui.layout import Layout, SettingsLayout
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
_TRACK_SCROLL_SECONDS = 2.0
_TRACK_SCROLL_HOLD_SECONDS = 0.5
_TRACK_SCROLL_GAP_PX = 12


class Renderer:
    def __init__(self) -> None:
        pygame.font.init()
        self._title_font = pygame.font.Font(None, 64)
        self._artist_font = pygame.font.Font(None, 42)
        self._track_font = pygame.font.Font(None, 52)
        self._artwork_cache: dict[str, pygame.Surface | None] = {}
        # Which track the scroll animation below is currently timing --
        # (number, disc title) rather than just the number, so swapping to
        # a different disc that happens to land on the same track number
        # still restarts the scroll instead of continuing an old offset.
        # Deliberately excludes the ticking elapsed/duration time that's
        # part of current_track_scroll_text itself, or the animation would
        # restart every second and never actually scroll.
        self._track_scroll_key: tuple[int | None, str | None] | None = None
        self._track_scroll_start = 0.0

    def render(
        self,
        canvas: pygame.Surface,
        view: ViewState,
        layout: Layout,
        pressed_button: str | None = None,
        show_no_disc_message: bool = False,
    ) -> None:
        canvas.fill(BLACK)
        if not view.has_disc:
            if show_no_disc_message:
                self._draw_no_disc_message(canvas, layout)
            return

        self._draw_artwork(canvas, view, layout)
        self._draw_text(canvas, view, layout)
        self._draw_buttons(canvas, view, layout, pressed_button)

    def _draw_no_disc_message(self, canvas: pygame.Surface, layout: Layout) -> None:
        # Local UI state, not from /status -- see ui/no_disc_message.py.
        x, y, w, h = layout.text_rect
        surf = self._title_font.render("Please load a CD", True, DIM)
        canvas.blit(surf, (x + (w - surf.get_width()) // 2, y + (h - surf.get_height()) // 2))

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
        ):
            if not text:
                continue
            surf = font.render(text, True, color)
            line_x = x + (w - surf.get_width()) // 2 if centered else x
            canvas.blit(surf, (line_x, cursor_y))
            cursor_y += surf.get_height() + _TEXT_LINE_GAP

        if view.current_track_label or view.current_track_scroll_text:
            self._draw_track_line(canvas, view, x, cursor_y, w)

        canvas.set_clip(prev_clip)

    def _draw_track_line(
        self, canvas: pygame.Surface, view: ViewState, x: int, y: int, available_width: int
    ) -> None:
        # Track number/label stays fixed in place; only the title+time
        # part scrolls, and only once it's actually too long to fit.
        label_width = 0
        if view.current_track_label:
            label_surf = self._track_font.render(view.current_track_label, True, WHITE)
            canvas.blit(label_surf, (x, y))
            label_width = label_surf.get_width() + _TRACK_SCROLL_GAP_PX

        if not view.current_track_scroll_text:
            return

        scroll_x = x + label_width
        scroll_width = available_width - label_width
        if scroll_width <= 0:
            return

        scroll_key = (view.current_track_number, view.disc_title)
        if scroll_key != self._track_scroll_key:
            self._track_scroll_key = scroll_key
            self._track_scroll_start = time.monotonic()

        text_surf = self._track_font.render(view.current_track_scroll_text, True, WHITE)
        max_offset = text_surf.get_width() - scroll_width

        offset = 0
        if max_offset > 0:
            cycle_seconds = _TRACK_SCROLL_SECONDS + _TRACK_SCROLL_HOLD_SECONDS
            elapsed = (time.monotonic() - self._track_scroll_start) % cycle_seconds
            if elapsed >= _TRACK_SCROLL_SECONDS:
                # Hold at the fully-scrolled position instead of jumping
                # straight back to the start -- a bare loop read as an
                # abrupt, hard-to-read jump-cut.
                offset = max_offset
            else:
                offset = int((elapsed / _TRACK_SCROLL_SECONDS) * max_offset)

        prev_clip = canvas.get_clip()
        canvas.set_clip(pygame.Rect(scroll_x, y, scroll_width, text_surf.get_height()))
        canvas.blit(text_surf, (scroll_x - offset, y))
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

    def render_settings(
        self,
        canvas: pygame.Surface,
        view: ViewState,
        layout: SettingsLayout,
        available_speakers: list[str] | None,
        scanning: bool,
    ) -> None:
        canvas.fill(BLACK)
        pygame.draw.rect(canvas, BUTTON_BG, layout.back_rect, border_radius=16)
        draw_back(canvas, layout.back_rect, WHITE)
        self._draw_speaker_rows(canvas, layout, view, available_speakers, scanning)
        self._draw_volume_slider(canvas, layout, view)

    def _draw_speaker_rows(
        self,
        canvas: pygame.Surface,
        layout: SettingsLayout,
        view: ViewState,
        available_speakers: list[str] | None,
        scanning: bool,
    ) -> None:
        if scanning or available_speakers is None:
            self._draw_centered_message(canvas, layout, "Scanning for speakers...")
            return
        if not available_speakers:
            self._draw_centered_message(canvas, layout, "No speakers found")
            return

        selected = set(view.selected_speaker_names)
        for name, (checkbox_rect, label_rect) in zip(available_speakers, layout.speaker_rows):
            self._draw_checkbox(canvas, checkbox_rect, checked=name in selected)
            label = self._track_font.render(name, True, WHITE)
            _, ly, _, lh = label_rect
            canvas.blit(label, (label_rect[0], ly + (lh - label.get_height()) // 2))

    def _draw_checkbox(self, canvas: pygame.Surface, rect, checked: bool) -> None:
        pygame.draw.rect(canvas, WHITE, rect, width=3, border_radius=6)
        if checked:
            x, y, w, h = rect
            pad = max(4, w // 5)
            pygame.draw.rect(
                canvas, WHITE, (x + pad, y + pad, w - 2 * pad, h - 2 * pad), border_radius=4
            )

    def _draw_volume_slider(
        self, canvas: pygame.Surface, layout: SettingsLayout, view: ViewState
    ) -> None:
        x, y, w, h = layout.volume_slider_rect
        pygame.draw.rect(canvas, BUTTON_BG, layout.volume_slider_rect, border_radius=h // 2)
        level = view.volume if view.volume is not None else 0
        fill_w = int(w * level / 100)
        if fill_w > 0:
            pygame.draw.rect(canvas, WHITE, (x, y, fill_w, h), border_radius=h // 2)
        label_text = "Volume: --" if view.volume is None else f"Volume: {view.volume}"
        label = self._artist_font.render(label_text, True, DIM)
        canvas.blit(label, (x, y - label.get_height() - 8))

    def _draw_centered_message(self, canvas: pygame.Surface, layout: SettingsLayout, text: str) -> None:
        # Anchored to back_rect/volume_slider_rect rather than speaker_rows,
        # since this draws precisely when speaker_rows may be empty (still
        # scanning, or genuinely zero speakers found).
        area_x = layout.back_rect[0]
        area_top = layout.back_rect[1] + layout.back_rect[3]
        area_bottom = layout.volume_slider_rect[1]
        message = self._track_font.render(text, True, DIM)
        canvas.blit(
            message, (area_x, area_top + (area_bottom - area_top - message.get_height()) // 2)
        )
