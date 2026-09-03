"""Touchscreen UI entry point. Renders directly to the DRM/KMS framebuffer
via SDL2's kmsdrm video driver -- no X11/Wayland compositor, so nothing to
wait on at boot. Runs as its own process against the REST API (see
CLAUDE.md), so a rendering crash never touches the audio-critical
ripping/streaming code in cd-player itself.
"""

from __future__ import annotations

import argparse
import enum
import logging
import os
import threading
import time
from pathlib import Path

from cd_player.ui.no_disc_message import NoDiscMessageTracker
from cd_player.ui.screen_blank import ScreenBlankTracker

logger = logging.getLogger(__name__)


class Backlight:
    """Wraps the touchscreen's sysfs backlight brightness file so the
    screen can be physically blanked/woken, not just rendered black --
    see CLAUDE.md's screen-blanking note for why (it's a real power-off,
    and the existing has_disc=False rendering already draws black without
    this). Remembers whatever brightness was already configured at
    startup so waking restores it exactly, rather than assuming a fixed
    value.

    If brightness reads 0 at startup, the previous process died while
    blanked (this service runs with Restart=on-failure) -- adopting 0 as
    "normal" would make wake() a no-op and leave the screen dark forever,
    so fall back to half of max_brightness instead (the panel's stock
    default on this hardware).
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._normal_brightness = self._read(self._path)
        if self._normal_brightness is None:
            logger.warning(
                "could not read backlight brightness at %s -- screen blanking disabled", path
            )
        elif self._normal_brightness == 0:
            max_brightness = self._read(self._path.parent / "max_brightness")
            self._normal_brightness = max(1, (max_brightness or 2) // 2)
            logger.warning(
                "backlight was 0 at startup (previous process likely died while "
                "blanked) -- using %d as normal brightness and waking now",
                self._normal_brightness,
            )
            self.wake()

    @property
    def available(self) -> bool:
        return self._normal_brightness is not None

    @staticmethod
    def _read(path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return None

    def _write(self, value: int) -> bool:
        try:
            self._path.write_text(str(value))
        except OSError:
            logger.exception("failed to set backlight brightness at %s", self._path)
            return False
        return True

    def blank(self) -> bool:
        """Returns whether the write actually happened -- the caller must
        not consider the screen blanked (and start swallowing touches) if
        it didn't, or app state desyncs from the physical panel until the
        next transition."""
        return self.available and self._write(0)

    def wake(self) -> bool:
        return self.available and self._write(self._normal_brightness)


class Screen(enum.Enum):
    NOW_PLAYING = "now_playing"
    SETTINGS = "settings"


class VolumeSender:
    """Coalesces rapid volume-slider drag updates into throttled POST
    /volume calls rather than sending on every drag event -- a drag can
    generate ~30 events/sec, and each send takes PlayerStateMachine's lock
    across a real UPnP call to the group coordinator (see CLAUDE.md's
    rapid-command gotcha). Only the latest value during a drag is kept;
    the value passed to end_drag() is always sent, even if nothing was
    flushed during the drag itself.
    """

    def __init__(self, client, interval_seconds: float = 0.2):
        self._client = client
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._pending: int | None = None
        self._last_sent: int | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start_drag(self) -> None:
        self._stop_event.clear()
        self._pending = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, level: int) -> None:
        with self._lock:
            self._pending = level

    def end_drag(self, level: int) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        self._send_if_changed(level)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._flush_pending()

    def _flush_pending(self) -> None:
        with self._lock:
            level, self._pending = self._pending, None
        if level is not None:
            self._send_if_changed(level)

    def _send_if_changed(self, level: int) -> None:
        if level == self._last_sent:
            return
        try:
            self._client.set_volume(level)
        except Exception:
            logger.exception("set_volume failed")
        else:
            self._last_sent = level


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cd-player-ui", description="Touchscreen UI for the CD player appliance"
    )
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8080",
        help="Base URL of the cd-player REST API (default: %(default)s)",
    )
    parser.add_argument(
        "--rotate",
        type=int,
        choices=(0, 90, 180, 270),
        default=270,
        help=(
            "Degrees to rotate the rendered landscape UI onto the physical panel "
            "(counterclockwise, pygame's convention). Depends on the physical mounting "
            "orientation, not just the panel's reported DRM mode -- verify against the "
            "real screen and adjust if taps land on the wrong button (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between GET /status polls (default: %(default)s)",
    )
    parser.add_argument(
        "--screen-blank-seconds",
        type=float,
        default=300.0,
        help="Seconds of no touch activity before blanking the screen whenever nothing "
        "is playing (no disc, or a disc sitting stopped/paused). Wakes on a touch, a new "
        "disc being loaded, or playback starting (default: %(default)s)",
    )
    parser.add_argument(
        "--backlight-path",
        default="/sys/class/backlight/panel_backlight@1/brightness",
        help="sysfs brightness file for the touchscreen backlight, used to blank/wake the "
        "screen. Depends on the specific panel/driver -- verify against the real hardware "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--no-disc-message-seconds",
        type=float,
        default=5.0,
        help="Seconds to show a 'Please load a CD' message after a touch while no disc is "
        "loaded (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

    import pygame

    from cd_player.ui.client import PlayerClient
    from cd_player.ui.layout import (
        button_at,
        compute_layout,
        compute_settings_layout,
        settings_hit_at,
        volume_from_slider_x,
    )
    from cd_player.ui.poller import StatusPoller
    from cd_player.ui.renderer import Renderer
    from cd_player.ui.rotation import canvas_size_for_physical, physical_to_canvas
    from cd_player.ui.view_model import is_button_enabled

    pygame.display.init()
    pygame.font.init()
    pygame.mouse.set_visible(False)

    display = pygame.display.set_mode((0, 0))
    physical_size = display.get_size()
    canvas_size = canvas_size_for_physical(physical_size, args.rotate)
    canvas = pygame.Surface(canvas_size)
    layout = compute_layout(canvas_size)

    client = PlayerClient(args.api_base_url)
    poller = StatusPoller(client, args.poll_interval)
    poller.start()
    volume_sender = VolumeSender(client)

    renderer = Renderer()
    clock = pygame.time.Clock()

    backlight = Backlight(args.backlight_path)
    blank_tracker = ScreenBlankTracker(args.screen_blank_seconds)
    blank_tracker.note_activity(time.monotonic())
    is_blanked = False
    no_disc_message = NoDiscMessageTracker(args.no_disc_message_seconds)

    actions = {
        "play": client.play,
        "pause": client.pause,
        "skip_forward": client.skip_forward,
        "skip_backward": client.skip_backward,
        "eject": client.eject,
    }

    pressed_button: str | None = None
    current_screen = Screen.NOW_PLAYING
    available_speakers: list[str] | None = None
    scanning = False
    settings_layout = compute_settings_layout(canvas_size, 0)
    dragging_slider = False

    def run_in_background(fn) -> None:
        # Off the render thread -- REST calls can take a while under lock
        # contention (see CLAUDE.md Gotchas), and the render loop should
        # never stall waiting on one.
        threading.Thread(target=fn, daemon=True).start()

    def enter_settings() -> None:
        nonlocal current_screen, scanning
        current_screen = Screen.SETTINGS
        scanning = True

        def fetch() -> None:
            nonlocal available_speakers, scanning, settings_layout
            try:
                speakers = client.get_available_speakers()
            except Exception:
                logger.exception("fetching available speakers failed")
                speakers = []
            available_speakers = speakers
            settings_layout = compute_settings_layout(canvas_size, len(speakers))
            scanning = False

        run_in_background(fetch)

    def toggle_speaker(index: int) -> None:
        if available_speakers is None or index >= len(available_speakers):
            return
        name = available_speakers[index]
        desired = set(poller.view.selected_speaker_names)
        if name in desired:
            desired.discard(name)
        else:
            desired.add(name)
        run_in_background(lambda: client.set_selected_speakers(sorted(desired)))

    def handle_press(physical_point: tuple[int, int]) -> None:
        nonlocal pressed_button, current_screen, dragging_slider
        canvas_point = physical_to_canvas(physical_point, canvas_size, args.rotate)

        if current_screen == Screen.NOW_PLAYING:
            name = button_at(layout, canvas_point)
            if name == "settings":
                enter_settings()
                return
            if name is None or not is_button_enabled(poller.view, name):
                return
            pressed_button = name

            def run_action() -> None:
                try:
                    actions[name]()
                except Exception:
                    logger.exception("action %s failed", name)

            # "Pressed" highlight should show up on the very next frame,
            # not after the call returns.
            run_in_background(run_action)
            return

        hit = settings_hit_at(settings_layout, canvas_point)
        if hit is None:
            return
        kind, index = hit
        if kind == "back":
            current_screen = Screen.NOW_PLAYING
        elif kind == "speaker_toggle":
            toggle_speaker(index)
        elif kind == "volume_slider":
            dragging_slider = True
            level = volume_from_slider_x(settings_layout.volume_slider_rect, canvas_point[0])
            volume_sender.start_drag()
            volume_sender.update(level)

    def handle_motion(physical_point: tuple[int, int]) -> None:
        if not dragging_slider:
            return
        canvas_point = physical_to_canvas(physical_point, canvas_size, args.rotate)
        level = volume_from_slider_x(settings_layout.volume_slider_rect, canvas_point[0])
        volume_sender.update(level)

    def handle_release(physical_point: tuple[int, int]) -> None:
        nonlocal pressed_button, dragging_slider
        pressed_button = None
        if dragging_slider:
            dragging_slider = False
            canvas_point = physical_to_canvas(physical_point, canvas_size, args.rotate)
            level = volume_from_slider_x(settings_layout.volume_slider_rect, canvas_point[0])
            volume_sender.end_drag(level)

    touch_event_types = (
        pygame.MOUSEBUTTONDOWN,
        pygame.MOUSEBUTTONUP,
        pygame.MOUSEMOTION,
        pygame.FINGERDOWN,
        pygame.FINGERUP,
        pygame.FINGERMOTION,
    )
    had_disc = poller.view.has_disc

    running = True
    try:
        while running:
            now = time.monotonic()

            # A new disc counts as activity even with no touch involved
            # (e.g. auto-play), so the screen doesn't stay blanked through
            # a fresh insert.
            if poller.view.has_disc and not had_disc:
                blank_tracker.note_activity(now)
            had_disc = poller.view.has_disc

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type in touch_event_types:
                    blank_tracker.note_activity(now)
                    no_disc_message.note_touch(now, poller.view.has_disc)
                    if is_blanked:
                        # First touch after blanking just wakes the screen
                        # -- don't act on a button the user couldn't see.
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        handle_press(event.pos)
                    elif event.type == pygame.MOUSEBUTTONUP:
                        handle_release(event.pos)
                    elif event.type == pygame.MOUSEMOTION:
                        handle_motion(event.pos)
                    elif event.type == pygame.FINGERDOWN:
                        handle_press(
                            (int(event.x * physical_size[0]), int(event.y * physical_size[1]))
                        )
                    elif event.type == pygame.FINGERUP:
                        handle_release(
                            (int(event.x * physical_size[0]), int(event.y * physical_size[1]))
                        )
                    elif event.type == pygame.FINGERMOTION:
                        handle_motion(
                            (int(event.x * physical_size[0]), int(event.y * physical_size[1]))
                        )

            should_blank = blank_tracker.update(now, poller.view.player_state == "playing")
            if should_blank != is_blanked:
                # Only adopt the new state if the hardware write actually
                # succeeded -- otherwise retry next frame, rather than app
                # state desyncing from the physical panel (a "blanked" flag
                # on a still-lit screen swallows touches; an "awake" flag on
                # a dark screen sends the first tap to an invisible button).
                written = backlight.blank() if should_blank else backlight.wake()
                if written:
                    is_blanked = should_blank

            if not is_blanked:
                if current_screen == Screen.NOW_PLAYING:
                    show_no_disc_message = no_disc_message.should_show(now, poller.view.has_disc)
                    renderer.render(
                        canvas, poller.view, layout, pressed_button, show_no_disc_message
                    )
                else:
                    renderer.render_settings(
                        canvas, poller.view, settings_layout, available_speakers, scanning
                    )
                rotated = pygame.transform.rotate(canvas, args.rotate)
                display.blit(rotated, (0, 0))
                pygame.display.flip()
            clock.tick(30)
    finally:
        poller.stop()
        pygame.display.quit()


if __name__ == "__main__":
    main()
