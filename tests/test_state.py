import pytest

from cd_player.config import Config
from cd_player.disc.ripper import RipSessionRegistry
from cd_player.disc.toc import DiscToc, TrackInfo
from cd_player.metadata.cache import DiscMetadata
from cd_player.state import PlayerState, PlayerStateMachine


class FakeRipSession:
    """Stands in for the real RipSession -- no cdparanoia subprocess, no
    tmpfs file. Starts out "instantly complete" so pre-rip logic can be
    exercised without needing real timing.
    """

    def __init__(self, session_id, device_path, track, cache_dir):
        self.session_id = session_id
        self.track = track
        self.started = False
        self.stopped = False
        self._complete = True

    def start(self):
        self.started = True

    @property
    def is_complete(self):
        return self._complete

    def stop(self):
        self.stopped = True


class FakeSonosController:
    """Mirrors the real SonosController's group semantics (sticky
    coordinator, empty-selection guard) with plain name-list bookkeeping --
    no network -- so tests exercise the same observable policy as
    production, not canned return values."""

    _DISCOVERABLE = ("Study", "Kitchen", "Bedroom")

    def __init__(self):
        self.calls: list[tuple] = []
        self._selected: list[str] = ["Study"]
        self._volume: int | None = None

    def _require_selection(self):
        if not self._selected:
            raise RuntimeError("no speakers selected")

    def play_uri(self, url, title="", duration_seconds=0.0):
        self._require_selection()
        self.calls.append(("play_uri", url))

    def play(self):
        self._require_selection()
        self.calls.append(("play",))

    def pause(self):
        self._require_selection()
        self.calls.append(("pause",))

    def stop(self):
        self._require_selection()
        self.calls.append(("stop",))

    def has_selection(self) -> bool:
        return bool(self._selected)

    def get_selected_speaker_names(self) -> list[str]:
        return list(self._selected)

    def list_available_speakers(self) -> list[str]:
        return list(self._DISCOVERABLE)

    def set_selected_speakers(self, names: list[str]) -> bool:
        resolved = sorted({n for n in names if n in self._DISCOVERABLE})
        old_coordinator = self._selected[0] if self._selected else None
        if not resolved:
            self._selected = []
            self.calls.append(("set_selected_speakers", []))
            return old_coordinator is not None
        if old_coordinator in resolved:
            new_coordinator = old_coordinator
        else:
            new_coordinator = resolved[0]
        coordinator_changed = new_coordinator != old_coordinator
        self._selected = [new_coordinator] + [n for n in resolved if n != new_coordinator]
        self.calls.append(("set_selected_speakers", list(self._selected)))
        return coordinator_changed

    def get_volume(self) -> int | None:
        return self._volume if self._selected else None

    def set_volume(self, level: int) -> None:
        self._require_selection()
        self._volume = level
        self.calls.append(("set_volume", level))

    def seek(self, seconds: float) -> None:
        self._require_selection()
        self.calls.append(("seek", seconds))


@pytest.fixture(autouse=True)
def fake_rip_session(monkeypatch):
    monkeypatch.setattr("cd_player.state.RipSession", FakeRipSession)


@pytest.fixture(autouse=True)
def fake_eject_tray(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("cd_player.state.eject_tray", lambda device_path: calls.append(device_path))
    return calls


def make_toc(num_tracks=3) -> DiscToc:
    tracks = [
        TrackInfo(number=i, offset_sectors=i * 1000, length_sectors=1000)
        for i in range(1, num_tracks + 1)
    ]
    return DiscToc(disc_id="fake-disc", tracks=tracks)


def make_player() -> tuple[PlayerStateMachine, FakeSonosController]:
    config = Config(
        sonos_speaker_name="Study",
        cd_device_path="/dev/fake-cd",
        db_path="/tmp/fake.db",
        stream_cache_dir="/tmp/fake-stream",
        artwork_cache_dir="/tmp/fake-artwork",
        bind_host="0.0.0.0",
        bind_port=8080,
        stream_base_url="http://10.0.0.9:8080",
        sonos_poll_interval_seconds=1.5,
    )
    sonos = FakeSonosController()
    registry = RipSessionRegistry()
    player = PlayerStateMachine(config, sonos, registry)
    return player, sonos


def test_play_without_disc_raises():
    player, _sonos = make_player()
    with pytest.raises(RuntimeError):
        player.play()


def test_play_starts_track_one():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)

    player.play()

    assert player.status()["state"] == "playing"
    assert player.status()["current_track_number"] == 1
    assert sonos.calls[-1][0] == "play_uri"


def test_pause_then_play_resumes_without_new_uri():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    sonos.calls.clear()

    player.pause()
    assert player.status()["state"] == "paused"
    assert sonos.calls == [("pause",)]

    player.play()
    assert player.status()["state"] == "playing"
    assert sonos.calls[-1] == ("play",)  # resumed, no new play_uri


def test_stop_then_play_always_restarts_at_track_one():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.skip_forward()
    assert player.status()["current_track_number"] == 2

    player.stop()
    assert player.status()["state"] == "stopped"

    player.play()
    assert player.status()["current_track_number"] == 1


def test_skip_forward_and_backward():
    player, _sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()

    player.skip_forward()
    assert player.status()["current_track_number"] == 2

    player.skip_backward()
    assert player.status()["current_track_number"] == 1


def test_skip_backward_at_first_track_is_noop():
    player, sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()
    sonos.calls.clear()

    player.skip_backward()

    assert player.status()["current_track_number"] == 1
    assert sonos.calls == []


def test_skip_forward_at_last_track_is_noop():
    player, sonos = make_player()
    player.set_disc(make_toc(2), None)
    player.play()
    player.skip_forward()
    sonos.calls.clear()

    player.skip_forward()

    assert player.status()["current_track_number"] == 2
    assert sonos.calls == []


def test_prerip_and_gapless_auto_advance():
    player, sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()

    # Drive is now free (FakeRipSession starts "complete"); the poller
    # would call this periodically.
    player.maybe_start_prerip()
    prerip_session = player._next_session
    assert prerip_session is not None
    assert prerip_session.started

    # Sonos reports STOPPED -- our single-track URI ran out -- should
    # auto-advance and reuse the pre-ripped session rather than starting
    # a fresh rip. Two consecutive STOPPED polls are required (see
    # test_single_stopped_report_does_not_auto_advance) so a real
    # end-of-track needs two calls here, not one.
    player.on_sonos_state("STOPPED")
    player.on_sonos_state("STOPPED")

    assert player.status()["current_track_number"] == 2
    assert player.status()["state"] == "playing"
    assert player._current_session is prerip_session


def test_auto_advance_stops_at_end_of_disc():
    player, _sonos = make_player()
    player.set_disc(make_toc(2), None)
    player.play()
    player.skip_forward()
    assert player.status()["current_track_number"] == 2

    player.on_sonos_state("STOPPED")
    player.on_sonos_state("STOPPED")

    assert player.status()["state"] == "stopped"
    assert player.status()["current_track_number"] is None


def test_single_stopped_report_does_not_auto_advance():
    # Sonos can report one spurious STOPPED tick right after a fresh
    # play_uri() while it's still spinning up (a UPnP handshake blip, not
    # real end-of-track) -- a single report must not skip the track.
    player, sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()
    sonos.calls.clear()

    player.on_sonos_state("STOPPED")

    assert player.status()["current_track_number"] == 1
    assert player.status()["state"] == "playing"
    assert sonos.calls == []


def test_stopped_report_followed_by_playing_resets_debounce():
    player, sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()

    player.on_sonos_state("STOPPED")
    player.on_sonos_state("PLAYING")  # blip resolved -- not a real stop
    sonos.calls.clear()
    player.on_sonos_state("STOPPED")  # only the first of a fresh pair

    assert player.status()["current_track_number"] == 1
    assert sonos.calls == []


def test_eject_while_stopped_opens_tray_without_touching_sonos():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)

    player.eject()

    assert player.status()["has_disc"] is False
    assert player.status()["state"] == "stopped"
    assert sonos.calls == []


def test_eject_while_playing_stops_first_then_opens_tray(fake_eject_tray):
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    session = player._current_session

    player.eject()

    assert sonos.calls[-1] == ("stop",)
    assert session.stopped
    assert player.status() == {
        "state": "stopped",
        "has_disc": False,
        "is_identifying": False,
        "current_track_number": None,
        "elapsed_seconds": 0.0,
        "track_duration_seconds": None,
        "first_track": None,
        "last_track": None,
        "selected_speakers": ["Study"],
        "volume": None,
        "disc": None,
    }
    assert fake_eject_tray == ["/dev/fake-cd"]


def test_eject_with_no_disc_still_opens_tray(fake_eject_tray):
    player, _sonos = make_player()

    player.eject()

    assert fake_eject_tray == ["/dev/fake-cd"]


def test_sonos_paused_event_updates_state_without_calling_pause():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    sonos.calls.clear()

    player.on_sonos_state("PAUSED_PLAYBACK")

    assert player.status()["state"] == "paused"
    assert sonos.calls == []  # learned, not re-issued


def test_play_sets_track_duration_and_resets_elapsed():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)

    player.play()

    status = player.status()
    assert status["track_duration_seconds"] == pytest.approx(1000 / 75)
    assert status["elapsed_seconds"] == 0.0


def test_on_sonos_position_updates_elapsed_seconds():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()

    player.on_sonos_position(5.5)

    assert player.status()["elapsed_seconds"] == 5.5


def test_skip_resets_elapsed_seconds():
    player, _sonos = make_player()
    player.set_disc(make_toc(3), None)
    player.play()
    player.on_sonos_position(9.0)

    player.skip_forward()

    assert player.status()["elapsed_seconds"] == 0.0


def test_stop_clears_elapsed_and_duration():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.on_sonos_position(5.5)

    player.stop()

    status = player.status()
    assert status["elapsed_seconds"] == 0.0
    assert status["track_duration_seconds"] is None


# -- multi-speaker selection and volume --------------------------------------
#
# FakeSonosController mirrors the real SonosController's group semantics
# (sticky coordinator, empty-selection guard) but NOT real Sonos hardware
# behavior. Per CLAUDE.md, actual grouping/seek/pause-ordering and whether
# unjoin() alone silences a dropped speaker (vs needing the same
# SetAVTransportURI("") clear as stop()) must be verified on a real
# multi-speaker Sonos setup regardless of these tests passing.


def test_selecting_additional_speaker_while_stopped_does_not_reissue():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)

    player.set_selected_speakers(["Study", "Kitchen"])

    assert sonos.get_selected_speaker_names() == ["Study", "Kitchen"]
    assert [c[0] for c in sonos.calls] == ["set_selected_speakers"]


def test_deselecting_current_coordinator_while_playing_reissues_and_seeks():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.on_sonos_position(12.5)
    sonos.calls.clear()

    player.set_selected_speakers(["Kitchen"])

    assert sonos.get_selected_speaker_names() == ["Kitchen"]
    assert player.status()["state"] == "playing"
    names = [c[0] for c in sonos.calls]
    assert "play_uri" in names
    assert ("seek", 12.5) in sonos.calls
    assert "pause" not in names


def test_deselecting_current_coordinator_while_paused_reissues_and_repauses():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.pause()
    sonos.calls.clear()

    player.set_selected_speakers(["Kitchen"])

    assert player.status()["state"] == "paused"
    names = [c[0] for c in sonos.calls]
    assert "play_uri" in names
    assert "pause" in names
    assert names.index("play_uri") < names.index("pause") < names.index("seek")


def test_selecting_zero_speakers_while_playing_acts_like_stop():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    session = player._current_session

    player.set_selected_speakers([])

    assert player.status()["state"] == "stopped"
    assert player.status()["current_track_number"] is None
    assert session.stopped


def test_play_with_zero_speakers_selected_raises():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.set_selected_speakers([])

    with pytest.raises(RuntimeError):
        player.play()


def test_on_sonos_state_ignored_when_no_selection():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.set_selected_speakers([])
    assert player.status()["state"] == "stopped"

    player.on_sonos_state("PLAYING")

    assert player.status()["state"] == "stopped"


def test_volume_passthrough():
    player, sonos = make_player()

    player.set_volume(42)

    assert ("set_volume", 42) in sonos.calls
    assert player.get_volume() is None  # not yet polled/cached

    player.on_sonos_volume(42)

    assert player.get_volume() == 42


def test_selecting_zero_speakers_clears_cached_volume():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    player.on_sonos_volume(42)
    assert player.get_volume() == 42

    player.set_selected_speakers([])

    assert player.get_volume() is None


def test_status_includes_selected_speakers_and_volume():
    player, _sonos = make_player()
    player.on_sonos_volume(55)

    status = player.status()

    assert status["selected_speakers"] == ["Study"]
    assert status["volume"] == 55


def test_update_metadata_fills_in_title_after_placeholder_insert():
    player, _sonos = make_player()
    toc = make_toc()
    player.set_disc(toc, None)
    assert player.status()["has_disc"] is True
    assert player.status()["disc"] is None  # placeholder: no metadata yet

    metadata = DiscMetadata(
        disc_id=toc.disc_id, mb_release_id="mb-1", title="Album", artist="Artist", artwork_path=None
    )
    player.update_metadata(toc.disc_id, metadata)

    assert player.status()["disc"]["title"] == "Album"


def test_update_metadata_ignored_if_disc_changed_since():
    player, _sonos = make_player()
    old_toc = make_toc()
    other_toc = DiscToc(disc_id="other-disc", tracks=old_toc.tracks)
    player.set_disc(old_toc, None)
    player.set_disc(other_toc, None)  # a different disc was inserted meanwhile

    stale_metadata = DiscMetadata(
        disc_id=old_toc.disc_id, mb_release_id="mb-1", title="Stale", artist="Artist", artwork_path=None
    )
    player.update_metadata(old_toc.disc_id, stale_metadata)

    assert player.status()["disc"] is None


def test_begin_identifying_sets_flag_when_no_disc_loaded():
    player, _sonos = make_player()

    player.begin_identifying()

    assert player.status()["is_identifying"] is True
    assert player.has_disc() is False


def test_begin_identifying_ignored_when_disc_already_loaded():
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)

    player.begin_identifying()

    assert player.status()["is_identifying"] is False
    assert player.has_disc() is True


def test_set_disc_clears_identifying_flag():
    player, _sonos = make_player()
    player.begin_identifying()

    player.set_disc(make_toc(), None)

    assert player.status()["is_identifying"] is False


def test_eject_clears_identifying_flag(fake_eject_tray):
    player, _sonos = make_player()
    player.set_disc(make_toc(), None)
    player.begin_identifying()  # shouldn't set it (disc already loaded), but exercise eject anyway

    player.eject()

    assert player.status()["is_identifying"] is False


def test_update_metadata_does_not_disturb_playback():
    player, sonos = make_player()
    toc = make_toc()
    player.set_disc(toc, None)
    player.play()
    assert player.status()["state"] == "playing"
    calls_before = list(sonos.calls)

    metadata = DiscMetadata(
        disc_id=toc.disc_id, mb_release_id="mb-1", title="Album", artist="Artist", artwork_path=None
    )
    player.update_metadata(toc.disc_id, metadata)

    assert player.status()["state"] == "playing"
    assert player.status()["disc"]["title"] == "Album"
    assert sonos.calls == calls_before  # no extra stop()/play_uri() from filling in metadata
