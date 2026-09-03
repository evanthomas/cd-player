from cd_player.ui.screen_blank import ScreenBlankTracker


def test_does_not_blank_before_timeout():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=299, is_playing=False) is False


def test_blanks_after_timeout_when_not_playing():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=300, is_playing=False) is True


def test_does_not_blank_while_playing():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=10_000, is_playing=True) is False


def test_blanks_with_no_disc_loaded_too():
    # is_playing is all that matters -- an idle empty player should power
    # its screen down the same as an idle loaded one.
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=300, is_playing=False) is True


def test_touch_activity_resets_timer():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, is_playing=False) is True

    tracker.note_activity(now=301)

    assert tracker.update(now=305, is_playing=False) is False


def test_unblanks_immediately_once_playing_starts():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, is_playing=False) is True

    assert tracker.update(now=301, is_playing=True) is False


def test_stays_blanked_across_repeated_updates_with_no_new_activity():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, is_playing=False) is True

    assert tracker.update(now=1000, is_playing=False) is True
