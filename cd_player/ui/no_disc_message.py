"""Pure decision logic for the "please load a CD" message shown briefly
after a touch while no disc is loaded. No pygame/hardware dependency --
matches the split used by screen_blank.py/view_model.py vs. the
pygame-dependent app.py/renderer.py.
"""

from __future__ import annotations


class NoDiscMessageTracker:
    def __init__(self, display_seconds: float):
        self._display_seconds = display_seconds
        self._show_until: float | None = None

    def note_touch(self, now: float, has_disc: bool) -> None:
        if not has_disc:
            self._show_until = now + self._display_seconds

    def should_show(self, now: float, has_disc: bool) -> bool:
        if has_disc:
            # A disc showed up (even without a fresh touch, e.g. an
            # already-in-flight insert resolving) -- nothing left to
            # prompt for.
            self._show_until = None
            return False
        if self._show_until is None:
            return False
        return now < self._show_until
