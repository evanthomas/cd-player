"""Pure decision logic for blanking the touchscreen after inactivity
whenever nothing is playing (no disc, or a disc sitting stopped/paused).
No pygame/hardware dependency -- the actual backlight I/O lives in
ui/app.py and is verified against the real screen instead, same split as
view_model.py vs renderer.py.
"""

from __future__ import annotations


class ScreenBlankTracker:
    def __init__(self, timeout_seconds: float):
        self._timeout_seconds = timeout_seconds
        self._last_activity: float = 0.0
        self._blanked = False

    def note_activity(self, now: float) -> None:
        self._last_activity = now

    def update(self, now: float, is_playing: bool) -> bool:
        """Call once per tick with the current view state and a monotonic
        clock reading. Returns whether the screen should be blanked now.
        """
        if is_playing:
            # Never blank while actively playing -- unblanks immediately
            # if playback starts, regardless of how long it's been since
            # the last touch.
            self._blanked = False
            return False
        self._blanked = (now - self._last_activity) >= self._timeout_seconds
        return self._blanked
