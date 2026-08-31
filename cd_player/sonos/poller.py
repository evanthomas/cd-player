"""Polls Sonos's own transport state instead of using UPnP GENA eventing --
avoids running a callback server the speaker must reach and avoids SoCo's
known subscription-renewal flakiness, at the cost of ~1-2s detection
latency for externally-triggered changes (e.g. pausing from the Sonos app).
"""

from __future__ import annotations

import logging
import threading

from cd_player.sonos.controller import SonosController
from cd_player.state import PlayerStateMachine

logger = logging.getLogger(__name__)


class SonosPoller:
    def __init__(
        self,
        sonos: SonosController,
        player: PlayerStateMachine,
        interval_seconds: float,
        pause_timeout_seconds: float = 300.0,
    ):
        self._sonos = sonos
        self._player = player
        self._interval = interval_seconds
        self._pause_timeout_seconds = pause_timeout_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self._player.maybe_auto_stop_after_pause_timeout(self._pause_timeout_seconds)
                if not self._sonos.has_selection():
                    continue
                state = self._sonos.get_transport_state()
                self._player.on_sonos_state(state)
                if state in ("PLAYING", "PAUSED_PLAYBACK"):
                    self._player.on_sonos_position(self._sonos.get_position_seconds())
                self._player.on_sonos_volume(self._sonos.get_volume())
                self._player.maybe_start_prerip()
            except Exception:
                logger.exception("Sonos poll failed")
