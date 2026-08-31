"""Background thread polling GET /status so the render loop never blocks
on network I/O. Mirrors sonos/poller.py's poll-not-push design; keeps the
last known view on a failed poll rather than flashing to a black screen
for one transient hiccup.
"""

from __future__ import annotations

import logging
import threading

from cd_player.ui.client import PlayerClient
from cd_player.ui.view_model import ViewState, view_state_from_status

logger = logging.getLogger(__name__)

NO_DISC = ViewState(
    has_disc=False,
    player_state="stopped",
    disc_title=None,
    disc_artist=None,
    artwork_path=None,
    current_track_number=None,
    current_track_label=None,
    current_track_scroll_text=None,
    first_track=None,
    last_track=None,
    selected_speaker_names=[],
    volume=None,
)


class StatusPoller:
    def __init__(self, client: PlayerClient, interval_seconds: float):
        self._client = client
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._view = NO_DISC
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    @property
    def view(self) -> ViewState:
        with self._lock:
            return self._view

    def _run(self) -> None:
        while True:
            self._poll_once()
            if self._stop_event.wait(self._interval):
                return

    def _poll_once(self) -> None:
        try:
            status = self._client.get_status()
            view = view_state_from_status(status)
        except Exception:
            logger.exception("status poll failed")
            return
        with self._lock:
            self._view = view
