from cd_player.ui.no_disc_message import NoDiscMessageTracker


def test_hidden_before_any_touch():
    tracker = NoDiscMessageTracker(display_seconds=5)

    assert tracker.should_show(now=0, has_disc=False) is False


def test_shows_after_touch_with_no_disc():
    tracker = NoDiscMessageTracker(display_seconds=5)
    tracker.note_touch(now=0, has_disc=False)

    assert tracker.should_show(now=4.9, has_disc=False) is True


def test_hides_after_display_seconds_elapse():
    tracker = NoDiscMessageTracker(display_seconds=5)
    tracker.note_touch(now=0, has_disc=False)

    assert tracker.should_show(now=5, has_disc=False) is False


def test_touch_with_disc_loaded_does_not_show_message():
    tracker = NoDiscMessageTracker(display_seconds=5)
    tracker.note_touch(now=0, has_disc=True)

    assert tracker.should_show(now=1, has_disc=True) is False


def test_repeated_touch_extends_display():
    tracker = NoDiscMessageTracker(display_seconds=5)
    tracker.note_touch(now=0, has_disc=False)

    tracker.note_touch(now=4, has_disc=False)

    assert tracker.should_show(now=8, has_disc=False) is True
    assert tracker.should_show(now=9, has_disc=False) is False


def test_disc_loading_hides_message_immediately():
    tracker = NoDiscMessageTracker(display_seconds=5)
    tracker.note_touch(now=0, has_disc=False)
    assert tracker.should_show(now=1, has_disc=False) is True

    assert tracker.should_show(now=2, has_disc=True) is False
    # And it doesn't reappear on its own if the disc is ejected again
    # without a fresh touch.
    assert tracker.should_show(now=3, has_disc=False) is False
