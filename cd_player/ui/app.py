"""Touchscreen UI entry point. Renders directly to the DRM/KMS framebuffer
via SDL2's kmsdrm video driver -- no X11/Wayland compositor, so nothing to
wait on at boot. Runs as its own process against the REST API (see
CLAUDE.md), so a rendering crash never touches the audio-critical
ripping/streaming code in cd-player itself.
"""

from __future__ import annotations

import argparse
import logging
import os
import threading

logger = logging.getLogger(__name__)


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
        default=90,
        help=(
            "Degrees to rotate the rendered landscape UI onto the physical panel "
            "(counterclockwise, pygame's convention). The Pi Touch Display 2 reports "
            "a native portrait mode, so this defaults to 90 -- verify against the "
            "real screen and adjust if taps land on the wrong button (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between GET /status polls (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

    import pygame

    from cd_player.ui.client import PlayerClient
    from cd_player.ui.layout import button_at, compute_layout
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

    renderer = Renderer()
    clock = pygame.time.Clock()

    actions = {
        "play": client.play,
        "pause": client.pause,
        "skip_forward": client.skip_forward,
        "skip_backward": client.skip_backward,
        "eject": client.eject,
    }

    pressed_button: str | None = None

    def handle_press(physical_point: tuple[int, int]) -> None:
        nonlocal pressed_button
        canvas_point = physical_to_canvas(physical_point, canvas_size, args.rotate)
        name = button_at(layout, canvas_point)
        if name is None or not is_button_enabled(poller.view, name):
            return
        pressed_button = name

        def run_action() -> None:
            try:
                actions[name]()
            except Exception:
                logger.exception("action %s failed", name)

        # Off the render thread -- REST calls can take a while under lock
        # contention (see CLAUDE.md Gotchas), and the "pressed" highlight
        # should show up on the very next frame, not after the call returns.
        threading.Thread(target=run_action, daemon=True).start()

    def handle_release() -> None:
        nonlocal pressed_button
        pressed_button = None

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    handle_press(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP:
                    handle_release()
                elif event.type == pygame.FINGERDOWN:
                    handle_press(
                        (int(event.x * physical_size[0]), int(event.y * physical_size[1]))
                    )
                elif event.type == pygame.FINGERUP:
                    handle_release()

            renderer.render(canvas, poller.view, layout, pressed_button)
            rotated = pygame.transform.rotate(canvas, args.rotate)
            display.blit(rotated, (0, 0))
            pygame.display.flip()
            clock.tick(30)
    finally:
        poller.stop()
        pygame.display.quit()


if __name__ == "__main__":
    main()
