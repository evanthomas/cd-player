import os

from cd_player.ui.app import Backlight


def make_backlight_dir(tmp_path, brightness="15", max_brightness="31"):
    (tmp_path / "brightness").write_text(brightness)
    (tmp_path / "max_brightness").write_text(max_brightness)
    return tmp_path / "brightness"


def test_blank_writes_zero_and_wake_restores_startup_brightness(tmp_path):
    path = make_backlight_dir(tmp_path, brightness="15")
    backlight = Backlight(str(path))

    assert backlight.blank() is True
    assert path.read_text() == "0"
    assert backlight.wake() is True
    assert path.read_text() == "15"


def test_startup_brightness_zero_falls_back_instead_of_adopting_it(tmp_path):
    # The previous process died while blanked (service auto-restarts) --
    # adopting 0 as "normal" would make wake() a no-op forever.
    path = make_backlight_dir(tmp_path, brightness="0", max_brightness="31")

    backlight = Backlight(str(path))

    # Woken immediately at startup, to half of max_brightness.
    assert path.read_text() == "15"
    backlight.blank()
    backlight.wake()
    assert path.read_text() == "15"


def test_unreadable_path_disables_blanking(tmp_path):
    backlight = Backlight(str(tmp_path / "does-not-exist"))

    assert backlight.available is False
    assert backlight.blank() is False
    assert backlight.wake() is False


def test_failed_write_reports_failure(tmp_path):
    path = make_backlight_dir(tmp_path, brightness="15")
    backlight = Backlight(str(path))
    os.chmod(path, 0o444)
    try:
        assert backlight.blank() is False
        assert backlight.wake() is False
    finally:
        os.chmod(path, 0o644)