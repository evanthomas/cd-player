"""Pure mapping from a `/status` JSON response to what the touchscreen
should show, including which buttons are actionable right now. No
pygame/network dependency, so this is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

_ACTIVE_STATES = ("playing", "paused")


@dataclass(frozen=True)
class ViewState:
    has_disc: bool
    player_state: str  # "stopped" / "playing" / "paused"
    disc_title: str | None
    disc_artist: str | None
    artwork_path: str | None
    current_track_number: int | None
    current_track_title: str | None
    first_track: int | None
    last_track: int | None
    selected_speaker_names: list[str]
    volume: int | None

    @property
    def can_play(self) -> bool:
        # Mirrors PlayerStateMachine.play(): raises with no disc, no-ops if
        # already playing -- neither does anything worth tapping for.
        return self.has_disc and self.player_state != "playing"

    @property
    def can_pause(self) -> bool:
        # Mirrors PlayerStateMachine.pause(): no-ops unless PLAYING.
        return self.player_state == "playing"

    @property
    def can_skip_backward(self) -> bool:
        return (
            self.player_state in _ACTIVE_STATES
            and self.current_track_number is not None
            and self.first_track is not None
            and self.current_track_number > self.first_track
        )

    @property
    def can_skip_forward(self) -> bool:
        return (
            self.player_state in _ACTIVE_STATES
            and self.current_track_number is not None
            and self.last_track is not None
            and self.current_track_number < self.last_track
        )


def _format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


_ENABLED_ATTR_BY_BUTTON = {
    "play": "can_play",
    "pause": "can_pause",
    "skip_forward": "can_skip_forward",
    "skip_backward": "can_skip_backward",
    # eject has no disabled state -- always actionable.
}


def is_button_enabled(view: ViewState, button_name: str) -> bool:
    attr = _ENABLED_ATTR_BY_BUTTON.get(button_name)
    return True if attr is None else getattr(view, attr)


def view_state_from_status(status: dict) -> ViewState:
    disc = status.get("disc")
    track_number = status.get("current_track_number")

    track_title = None
    if disc is not None and track_number is not None:
        for track in disc["tracks"]:
            if track["number"] == track_number:
                track_title = f"{track_number}. {track['title']}"
                break
    elif track_number is not None:
        # Disc metadata unavailable (e.g. no MusicBrainz match) -- same
        # fallback PlayerStateMachine._track_title uses for Sonos.
        track_title = f"Track {track_number}"

    duration = status.get("track_duration_seconds")
    if track_title is not None and duration is not None:
        elapsed = status.get("elapsed_seconds") or 0.0
        track_title = f"{track_title}   {_format_mmss(elapsed)} / {_format_mmss(duration)}"

    return ViewState(
        has_disc=status["has_disc"],
        player_state=status["state"],
        disc_title=disc["title"] if disc is not None else None,
        disc_artist=disc["artist"] if disc is not None else None,
        artwork_path=disc["artwork_path"] if disc is not None else None,
        current_track_number=track_number,
        current_track_title=track_title,
        first_track=status.get("first_track"),
        last_track=status.get("last_track"),
        selected_speaker_names=status.get("selected_speakers") or [],
        volume=status.get("volume"),
    )
