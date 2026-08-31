"""Pure decision logic for blanking the touchscreen after inactivity while
a disc is loaded but not playing. No pygame/hardware dependency -- the
actual backlight I/O lives in ui/app.py and is verified against the real
screen instead, same split as view_model.py vs renderer.py.
"""

from __future__ import annotations


class ScreenBlankTracker:
    def __init__(self, timeout_seconds: float):
        self._timeout_seconds = timeout_seconds
        self._last_activity: float = 0.0
        self._blanked = False

    def note_activity(self, now: float) -> None:
        self._last_activity = now

    def update(self, now: float, has_disc: bool, is_playing: bool) -> bool:
        """Call once per tick with the current view state and a monotonic
        clock reading. Returns whether the screen should be blanked now.
        """
        if not (has_disc and not is_playing):
            # Never blank with no disc loaded or while actively playing --
            # unblanks immediately if either becomes true, regardless of
            # how long it's been since the last touch.
            self._blanked = False
            return False
        self._blanked = (now - self._last_activity) >= self._timeout_seconds
        return self._blanked
