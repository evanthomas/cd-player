import pytest

from cd_player.config import Config
from cd_player.disc.ripper import RipSessionRegistry
from cd_player.disc.toc import DiscToc, TrackInfo
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
    def __init__(self):
        self.calls: list[tuple] = []

    def play_uri(self, url, title="", duration_seconds=0.0):
        self.calls.append(("play_uri", url))

    def play(self):
        self.calls.append(("play",))

    def pause(self):
        self.calls.append(("pause",))

    def stop(self):
        self.calls.append(("stop",))


@pytest.fixture(autouse=True)
def fake_rip_session(monkeypatch):
    monkeypatch.setattr("cd_player.state.RipSession", FakeRipSession)


def make_toc(num_tracks=3) -> DiscToc:
    tracks = [
        TrackInfo(number=i, offset_sectors=i * 1000, length_sectors=1000)
        for i in range(1, num_tracks + 1)
    ]
    return DiscToc(disc_id="fake-disc", tracks=tracks)


def make_player() -> tuple[PlayerStateMachine, FakeSonosController]:
    config = Config(
        sonos_speaker_ip="10.0.0.5",
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
    # a fresh rip.
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

    assert player.status()["state"] == "stopped"
    assert player.status()["current_track_number"] is None


def test_sonos_paused_event_updates_state_without_calling_pause():
    player, sonos = make_player()
    player.set_disc(make_toc(), None)
    player.play()
    sonos.calls.clear()

    player.on_sonos_state("PAUSED_PLAYBACK")

    assert player.status()["state"] == "paused"
    assert sonos.calls == []  # learned, not re-issued
