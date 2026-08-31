from cd_player.ui.screen_blank import ScreenBlankTracker


def test_does_not_blank_before_timeout():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=299, has_disc=True, is_playing=False) is False


def test_blanks_after_timeout_when_loaded_and_not_playing():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=300, has_disc=True, is_playing=False) is True


def test_does_not_blank_while_playing():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=10_000, has_disc=True, is_playing=True) is False


def test_does_not_blank_with_no_disc():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)

    assert tracker.update(now=10_000, has_disc=False, is_playing=False) is False


def test_touch_activity_resets_timer():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, has_disc=True, is_playing=False) is True

    tracker.note_activity(now=301)

    assert tracker.update(now=305, has_disc=True, is_playing=False) is False


def test_unblanks_immediately_once_playing_starts():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, has_disc=True, is_playing=False) is True

    assert tracker.update(now=301, has_disc=True, is_playing=True) is False


def test_unblanks_immediately_once_disc_ejected():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, has_disc=True, is_playing=False) is True

    assert tracker.update(now=301, has_disc=False, is_playing=False) is False


def test_stays_blanked_across_repeated_updates_with_no_new_activity():
    tracker = ScreenBlankTracker(timeout_seconds=300)
    tracker.note_activity(now=0)
    assert tracker.update(now=300, has_disc=True, is_playing=False) is True

    assert tracker.update(now=1000, has_disc=True, is_playing=False) is True
