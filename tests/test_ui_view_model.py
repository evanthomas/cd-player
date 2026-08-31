from cd_player.ui.view_model import is_button_enabled, view_state_from_status


def test_no_disc_is_black_screen_state():
    status = {"state": "stopped", "has_disc": False, "current_track_number": None, "disc": None}

    view = view_state_from_status(status)

    assert view.has_disc is False
    assert view.disc_title is None
    assert view.artwork_path is None
    assert view.current_track_title is None


def test_is_identifying_maps_from_status():
    status = {
        "state": "stopped",
        "has_disc": False,
        "is_identifying": True,
        "current_track_number": None,
        "disc": None,
    }

    view = view_state_from_status(status)

    assert view.is_identifying is True


def test_is_identifying_defaults_false_when_missing():
    status = {"state": "stopped", "has_disc": False, "current_track_number": None, "disc": None}

    view = view_state_from_status(status)

    assert view.is_identifying is False


def test_disc_with_metadata_resolves_current_track_title():
    status = {
        "state": "playing",
        "has_disc": True,
        "current_track_number": 2,
        "first_track": 1,
        "last_track": 2,
        "disc": {
            "disc_id": "abc",
            "title": "Album",
            "artist": "Artist",
            "artwork_path": "/tmp/art.jpg",
            "tracks": [{"number": 1, "title": "One"}, {"number": 2, "title": "Two"}],
        },
    }

    view = view_state_from_status(status)

    assert view.has_disc is True
    assert view.disc_title == "Album"
    assert view.disc_artist == "Artist"
    assert view.artwork_path == "/tmp/art.jpg"
    assert view.current_track_title == "2. Two"


def test_disc_without_metadata_falls_back_to_track_number():
    # e.g. no MusicBrainz match -- state.py's _track_title has the same
    # "Track N" fallback for what it hands to Sonos.
    status = {"state": "playing", "has_disc": True, "current_track_number": 3, "disc": None}

    view = view_state_from_status(status)

    assert view.has_disc is True
    assert view.disc_title is None
    assert view.current_track_title == "Track 3"


def test_no_current_track_has_no_track_title():
    status = {"state": "stopped", "has_disc": True, "current_track_number": None, "disc": None}

    view = view_state_from_status(status)

    assert view.current_track_title is None


def test_track_title_includes_elapsed_and_total_time():
    status = {
        "state": "playing",
        "has_disc": True,
        "current_track_number": 2,
        "elapsed_seconds": 83,
        "track_duration_seconds": 296,
        "disc": {
            "disc_id": "abc",
            "title": "Album",
            "artist": "Artist",
            "artwork_path": "/tmp/art.jpg",
            "tracks": [{"number": 1, "title": "One"}, {"number": 2, "title": "Two"}],
        },
    }

    view = view_state_from_status(status)

    assert view.current_track_title == "2. Two   1:23 / 4:56"


def test_track_title_with_no_metadata_still_includes_time():
    status = {
        "state": "playing",
        "has_disc": True,
        "current_track_number": 3,
        "elapsed_seconds": 5,
        "track_duration_seconds": 65,
        "disc": None,
    }

    view = view_state_from_status(status)

    assert view.current_track_title == "Track 3   0:05 / 1:05"


def test_track_title_omits_time_when_duration_unknown():
    status = {
        "state": "stopped",
        "has_disc": True,
        "current_track_number": None,
        "elapsed_seconds": 0.0,
        "track_duration_seconds": None,
        "disc": None,
    }

    view = view_state_from_status(status)

    assert view.current_track_title is None


def _status(player_state, current_track_number, first_track=1, last_track=3, has_disc=True):
    return {
        "state": player_state,
        "has_disc": has_disc,
        "current_track_number": current_track_number,
        "first_track": first_track,
        "last_track": last_track,
        "disc": None,
    }


def test_play_disabled_with_no_disc():
    view = view_state_from_status(_status("stopped", None, has_disc=False))
    assert view.can_play is False


def test_play_enabled_when_stopped_or_paused_with_disc():
    assert view_state_from_status(_status("stopped", None)).can_play is True
    assert view_state_from_status(_status("paused", 1)).can_play is True


def test_play_disabled_when_already_playing():
    assert view_state_from_status(_status("playing", 1)).can_play is False


def test_pause_enabled_only_when_playing():
    assert view_state_from_status(_status("playing", 1)).can_pause is True
    assert view_state_from_status(_status("paused", 1)).can_pause is False
    assert view_state_from_status(_status("stopped", None)).can_pause is False


def test_skip_backward_disabled_at_first_track():
    view = view_state_from_status(_status("playing", 1, first_track=1, last_track=3))
    assert view.can_skip_backward is False


def test_skip_backward_enabled_past_first_track():
    view = view_state_from_status(_status("playing", 2, first_track=1, last_track=3))
    assert view.can_skip_backward is True


def test_skip_forward_disabled_at_last_track():
    view = view_state_from_status(_status("playing", 3, first_track=1, last_track=3))
    assert view.can_skip_forward is False


def test_skip_forward_enabled_before_last_track():
    view = view_state_from_status(_status("playing", 2, first_track=1, last_track=3))
    assert view.can_skip_forward is True


def test_skip_disabled_when_stopped():
    view = view_state_from_status(_status("stopped", None))
    assert view.can_skip_backward is False
    assert view.can_skip_forward is False


def test_skip_forward_disabled_when_track_bounds_unknown():
    # e.g. no MusicBrainz match hasn't happened to matter here -- bounds
    # come from the TOC regardless, but defend against a missing field.
    view = view_state_from_status(_status("playing", 2, first_track=None, last_track=None))
    assert view.can_skip_forward is False
    assert view.can_skip_backward is False


def test_eject_is_always_enabled():
    assert is_button_enabled(view_state_from_status(_status("stopped", None)), "eject") is True
    assert is_button_enabled(view_state_from_status(_status("playing", 1)), "eject") is True


def test_is_button_enabled_delegates_to_view_properties():
    view = view_state_from_status(_status("playing", 1, first_track=1, last_track=3))
    assert is_button_enabled(view, "play") == view.can_play
    assert is_button_enabled(view, "pause") == view.can_pause
    assert is_button_enabled(view, "skip_forward") == view.can_skip_forward
    assert is_button_enabled(view, "skip_backward") == view.can_skip_backward


def test_settings_is_always_enabled():
    assert is_button_enabled(view_state_from_status(_status("stopped", None)), "settings") is True
    assert is_button_enabled(view_state_from_status(_status("playing", 1)), "settings") is True


def test_selected_speakers_and_volume_map_from_status():
    status = _status("playing", 1)
    status["selected_speakers"] = ["Study", "Kitchen"]
    status["volume"] = 37

    view = view_state_from_status(status)

    assert view.selected_speaker_names == ["Study", "Kitchen"]
    assert view.volume == 37


def test_selected_speakers_and_volume_default_when_missing():
    view = view_state_from_status(_status("stopped", None))

    assert view.selected_speaker_names == []
    assert view.volume is None
