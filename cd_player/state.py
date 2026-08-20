"""Central player state machine.

Every transition -- whether triggered by a REST call or learned from
polling Sonos's own transport state -- funnels through this one locked
object, so a state change *learned from* Sonos never re-issues the SoCo
command that would just echo it back.
"""

from __future__ import annotations

import enum
import logging
import threading
import uuid

from cd_player.config import Config
from cd_player.disc.drive import eject_tray
from cd_player.disc.ripper import RipSession, RipSessionRegistry
from cd_player.disc.toc import CDDA_SECTORS_PER_SECOND, DiscToc
from cd_player.metadata.cache import DiscMetadata
from cd_player.sonos.controller import SonosController

logger = logging.getLogger(__name__)


class PlayerState(enum.Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class PlayerStateMachine:
    def __init__(self, config: Config, sonos: SonosController, registry: RipSessionRegistry):
        self._config = config
        self._sonos = sonos
        self._registry = registry
        self._lock = threading.RLock()

        self._state = PlayerState.STOPPED
        self._toc: DiscToc | None = None
        self._metadata: DiscMetadata | None = None
        self._current_track_number: int | None = None
        self._current_session: RipSession | None = None

        # One track ripped ahead of playback, so auto-advance at end of
        # track is gapless. Only ever populated once the current track's
        # own rip has finished (see maybe_start_prerip) -- a single
        # optical drive can't be read by two cdparanoia processes at once.
        self._next_track_number: int | None = None
        self._next_session: RipSession | None = None

    # -- disc lifecycle ---------------------------------------------------

    def set_disc(self, toc: DiscToc | None, metadata: DiscMetadata | None) -> None:
        """Called by the disc monitor on insert/eject. Never starts
        playback -- that only ever happens via an explicit `play()` call.
        """
        with self._lock:
            if self._state != PlayerState.STOPPED:
                # Without this, Sonos keeps reporting PLAYING for the
                # stream we're about to tear down -- the next poll would
                # copy that stale state onto the freshly reset player below.
                self._sonos.stop()
            self._teardown_all_sessions()
            self._toc = toc
            self._metadata = metadata
            self._current_track_number = None
            self._state = PlayerState.STOPPED

    # -- REST-triggered commands -------------------------------------------

    def play(self) -> None:
        with self._lock:
            if self._toc is None:
                raise RuntimeError("no disc loaded")
            if self._state == PlayerState.PAUSED:
                self._sonos.play()
                self._state = PlayerState.PLAYING
                return
            if self._state == PlayerState.PLAYING:
                return
            # STOPPED -> PLAYING always starts at the beginning of the disc.
            self._start_track(self._toc.first_track)
            self._state = PlayerState.PLAYING

    def pause(self) -> None:
        with self._lock:
            if self._state != PlayerState.PLAYING:
                return
            self._sonos.pause()
            self._state = PlayerState.PAUSED

    def stop(self) -> None:
        with self._lock:
            if self._state == PlayerState.STOPPED:
                return
            self._sonos.stop()
            self._teardown_all_sessions()
            self._current_track_number = None
            self._state = PlayerState.STOPPED

    def eject(self) -> None:
        """Stop playback (if any) and open the tray. Clears disc state here
        rather than waiting for DiscMonitor's udev-driven `set_disc(None,
        None)` -- that event lands on a separate thread with no latency
        guarantee, and a client polling /status right after this call
        should already see `has_disc: false`. The later udev event is then
        a harmless no-op against already-cleared state.
        """
        with self._lock:
            if self._state != PlayerState.STOPPED:
                self._sonos.stop()
            self._teardown_all_sessions()
            self._toc = None
            self._metadata = None
            self._current_track_number = None
            self._state = PlayerState.STOPPED
            eject_tray(self._config.cd_device_path)

    def skip_forward(self) -> None:
        with self._lock:
            self._skip(+1)

    def skip_backward(self) -> None:
        with self._lock:
            self._skip(-1)

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "has_disc": self._toc is not None,
                "current_track_number": self._current_track_number,
                "disc": None
                if self._metadata is None
                else {
                    "disc_id": self._metadata.disc_id,
                    "title": self._metadata.title,
                    "artist": self._metadata.artist,
                    "artwork_path": self._metadata.artwork_path,
                    "tracks": [
                        {"number": t.number, "title": t.title} for t in self._metadata.tracks
                    ],
                },
            }

    # -- Sonos-observed transitions -----------------------------------------

    def on_sonos_state(self, sonos_state: str) -> None:
        """`sonos_state` is Sonos's own reported transport state:
        'PLAYING' / 'PAUSED_PLAYBACK' / 'STOPPED' / etc.
        """
        with self._lock:
            if self._toc is None:
                return
            if sonos_state == "PLAYING":
                self._state = PlayerState.PLAYING
            elif sonos_state == "PAUSED_PLAYBACK":
                if self._state == PlayerState.PLAYING:
                    self._state = PlayerState.PAUSED
            elif sonos_state == "STOPPED":
                if self._state != PlayerState.STOPPED:
                    self._on_stopped_externally()

    def maybe_start_prerip(self) -> None:
        """Called periodically by the Sonos poller. Once the current
        track's rip has finished (the drive is idle again) and there's a
        next track, start ripping it ahead of time so auto-advance is
        gapless.
        """
        with self._lock:
            if self._state not in (PlayerState.PLAYING, PlayerState.PAUSED):
                return
            if self._toc is None or self._current_track_number is None:
                return
            if self._current_session is None or not self._current_session.is_complete:
                return
            if self._next_session is not None:
                return
            self._start_prerip(self._current_track_number + 1)

    # -- internals ------------------------------------------------------------

    def _on_stopped_externally(self) -> None:
        """Sonos reports STOPPED while we expected PLAYING/PAUSED. Since we
        never use Sonos's native queue, this is also how natural
        end-of-track is detected -- Sonos going idle after our
        single-track URI finishes looks identical to an explicit stop.
        Auto-advance if there's a next track, otherwise treat as a real
        stop.
        """
        assert self._toc is not None and self._current_track_number is not None
        next_number = self._current_track_number + 1
        if next_number <= self._toc.last_track:
            self._start_track(next_number)
            self._state = PlayerState.PLAYING
        else:
            self._teardown_all_sessions()
            self._current_track_number = None
            self._state = PlayerState.STOPPED

    def _skip(self, direction: int) -> None:
        if self._toc is None or self._state not in (PlayerState.PLAYING, PlayerState.PAUSED):
            return
        assert self._current_track_number is not None
        target = self._current_track_number + direction
        if target < self._toc.first_track or target > self._toc.last_track:
            return  # no-op at disc boundaries
        was_paused = self._state == PlayerState.PAUSED
        self._start_track(target)
        if was_paused:
            self._sonos.pause()
            self._state = PlayerState.PAUSED
        else:
            self._state = PlayerState.PLAYING

    def _start_track(self, track_number: int) -> None:
        assert self._toc is not None

        if self._next_track_number == track_number and self._next_session is not None:
            # Already pre-ripped (gapless auto-advance case) -- promote it
            # instead of tearing down and starting over.
            self._teardown_current_session()
            session = self._next_session
            self._next_session = None
            self._next_track_number = None
        else:
            self._teardown_current_session()
            self._teardown_next_session()
            track = self._toc.track(track_number)
            session = RipSession(
                session_id=str(uuid.uuid4()),
                device_path=self._config.cd_device_path,
                track=track,
                cache_dir=self._config.stream_cache_dir,
            )
            session.start()
            self._registry.add(session)

        self._current_session = session
        self._current_track_number = track_number
        url = f"{self._config.stream_base_url}/stream/{session.session_id}.wav"
        self._sonos.play_uri(
            url,
            title=self._track_title(track_number),
            duration_seconds=session.track.length_sectors / CDDA_SECTORS_PER_SECOND,
        )

    def _track_title(self, track_number: int) -> str:
        if self._metadata is not None:
            for t in self._metadata.tracks:
                if t.number == track_number:
                    return t.title
        return f"Track {track_number}"

    def _start_prerip(self, track_number: int) -> None:
        assert self._toc is not None
        if track_number > self._toc.last_track:
            return
        track = self._toc.track(track_number)
        session = RipSession(
            session_id=str(uuid.uuid4()),
            device_path=self._config.cd_device_path,
            track=track,
            cache_dir=self._config.stream_cache_dir,
        )
        session.start()
        self._registry.add(session)
        self._next_session = session
        self._next_track_number = track_number

    def _teardown_current_session(self) -> None:
        if self._current_session is not None:
            self._registry.remove(self._current_session.session_id)
            self._current_session.stop()
            self._current_session = None

    def _teardown_next_session(self) -> None:
        if self._next_session is not None:
            self._registry.remove(self._next_session.session_id)
            self._next_session.stop()
            self._next_session = None

    def _teardown_all_sessions(self) -> None:
        self._teardown_current_session()
        self._teardown_next_session()
