"""Thin wrapper around SoCo, managing a group of speakers playing in sync.

The group always has one coordinator -- `self._selected[0]` -- which every
transport/volume/seek call targets; any other selected speakers are joined
to it as members. The coordinator is "sticky": it only changes identity when
it's actually deselected, so adding/removing other speakers never disturbs
ongoing playback.
"""

from __future__ import annotations

import logging
import threading
from xml.sax.saxutils import escape

import soco
from soco.discovery import by_name, discover

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _parse_duration(value: str) -> float:
    """Inverse of _format_duration -- SoCo reports elapsed/total position
    as 'H:MM:SS' strings (e.g. from GetPositionInfo)."""
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _build_track_metadata(title: str, uri: str, duration_seconds: float) -> str:
    """DIDL-Lite for a normal seekable track.

    Deliberately hand-built rather than using SoCo's play_uri(title=...)
    shortcut, which classifies content as `object.item.audioItem.
    audioBroadcast` (radio) -- that made Sonos treat our finite, seekable
    WAV stream as a live radio feed: it never reported playback position
    and eventually gave up. `musicTrack` plus an explicit `res` duration
    is what gets normal track transport behavior (position, seek).
    """
    duration = _format_duration(duration_seconds)
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="1" parentID="0" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f'<res protocolInfo="http-get:*:audio/wav:*" duration="{duration}">'
        f"{escape(uri)}</res>"
        "</item></DIDL-Lite>"
    )


class SonosController:
    def __init__(self, speaker_name: str):
        device = by_name(speaker_name)
        if device is None:
            raise RuntimeError(
                f"no Sonos speaker named {speaker_name!r} found on the network"
            )
        device.unjoin()  # start every boot from a clean standalone baseline
        self._selected: list[soco.SoCo] = [device]
        self._names: dict[str, str] = {device.uid: device.player_name}
        # SonosPoller reads has_selection()/get_transport_state()/etc. from
        # its own thread, unsynchronized with REST-triggered
        # set_selected_speakers() calls -- unlike the old single fixed
        # self._device (set once, never reassigned), self._selected is now
        # mutated at runtime, so every read/write of it must go through this
        # lock or a selection change mid-poll can flip has_selection() out
        # from under an in-flight read (observed directly: a poll tick's
        # get_position_seconds() raised "no speakers selected" seconds after
        # its own has_selection() check passed).
        self._lock = threading.RLock()

    # -- speaker selection --------------------------------------------------

    def list_available_speakers(self) -> list[str]:
        return sorted(z.player_name for z in (discover(timeout=4.0) or []))

    def get_selected_speaker_names(self) -> list[str]:
        with self._lock:
            return [self._names[s.uid] for s in self._selected]

    def has_selection(self) -> bool:
        with self._lock:
            return bool(self._selected)

    def set_selected_speakers(self, names: list[str]) -> bool:
        """Reform the group to exactly the speakers named in `names` (a name
        that isn't currently discoverable is silently dropped). The
        coordinator is "sticky": it stays `self._selected[0]` if that speaker
        is still selected, and only otherwise picks the alphabetically-first
        remaining speaker -- so adding/removing other speakers never forces
        a handoff. Returns True iff the coordinator identity changed.
        """
        zones = {z.player_name: z for z in (discover(timeout=4.0) or [])}
        seen: set[str] = set()
        resolved: list[soco.SoCo] = []
        for name in names:
            zone = zones.get(name)
            if zone is not None and zone.uid not in seen:
                seen.add(zone.uid)
                resolved.append(zone)
        resolved.sort(key=lambda z: z.player_name)
        resolved_uids = {z.uid for z in resolved}

        with self._lock:
            old_coordinator = self._selected[0] if self._selected else None
            old_member_uids = {s.uid for s in self._selected[1:]}
            currently_selected = list(self._selected)

            # Hard-stop and unjoin every currently-selected speaker being
            # fully dropped, before touching group topology -- otherwise a
            # deselected speaker keeps playing the live stream forever
            # (unjoin() alone only changes group membership, it doesn't
            # silence anything, same as UPnP Stop alone not clearing
            # CurrentURI -- see _hard_stop).
            for speaker in currently_selected:
                if speaker.uid not in resolved_uids:
                    self._hard_stop(speaker)
                    speaker.unjoin()

            if not resolved:
                self._selected = []
                self._names = {}
                return old_coordinator is not None

            if old_coordinator is not None and old_coordinator.uid in resolved_uids:
                new_coordinator = old_coordinator
            else:
                new_coordinator = resolved[0]
            coordinator_changed = (
                old_coordinator is None or new_coordinator.uid != old_coordinator.uid
            )
            if coordinator_changed:
                new_coordinator.unjoin()  # must be standalone before others can join it

            final: list[soco.SoCo] = [new_coordinator]
            for member in resolved:
                if member.uid == new_coordinator.uid:
                    continue
                if not coordinator_changed and member.uid in old_member_uids:
                    final.append(member)  # already correctly joined -- no call needed
                    continue
                try:
                    member.join(new_coordinator)
                except Exception:
                    logger.exception("failed to join %s to the group", member.player_name)
                    continue
                final.append(member)

            self._selected = final
            self._names = {z.uid: z.player_name for z in final}
            return coordinator_changed

    def _hard_stop(self, speaker: soco.SoCo) -> None:
        speaker.stop()
        # UPnP Stop halts playback but leaves the last URI loaded, so the
        # Sonos app still shows our track as the current source even
        # though nothing is playing -- clearing CurrentURI is what makes
        # "stop" actually read as disconnected rather than just paused.
        speaker.avTransport.SetAVTransportURI(
            [("InstanceID", 0), ("CurrentURI", ""), ("CurrentURIMetaData", "")]
        )

    # -- volume ---------------------------------------------------------------

    def get_volume(self) -> int | None:
        with self._lock:
            if not self._selected:
                return None
            coordinator = self._selected[0]
        return coordinator.group.volume

    def set_volume(self, level: int) -> None:
        coordinator = self._require_coordinator()
        coordinator.group.volume = level

    def seek(self, seconds: float) -> None:
        coordinator = self._require_coordinator()
        coordinator.seek(position=_format_duration(seconds))

    # -- transport (all target the group coordinator, self._selected[0]) ------

    def play_uri(self, url: str, title: str = "", duration_seconds: float = 0.0) -> None:
        coordinator, members = self._snapshot_selection()
        self._ensure_members_joined(coordinator, members)
        meta = _build_track_metadata(title, url, duration_seconds)
        coordinator.play_uri(url, meta=meta)

    def _ensure_members_joined(
        self, coordinator: soco.SoCo, members: list[soco.SoCo]
    ) -> None:
        """Re-form the group before starting fresh playback -- stop()
        releases grouped members so a stopped appliance doesn't keep
        holding speakers, so play must join them back. Checking each
        member's actual current group (rather than trusting our own
        bookkeeping) also heals a member pulled out of the group
        externally, e.g. regrouped from the Sonos app."""
        for member in members:
            try:
                if member.group.coordinator.uid != coordinator.uid:
                    member.join(coordinator)
            except Exception:
                logger.exception("failed to join %s to the group", member.player_name)

    def play(self) -> None:
        self._require_coordinator().play()

    def pause(self) -> None:
        self._require_coordinator().pause()

    def stop(self) -> None:
        """Hard-stop the coordinator and release any other grouped members
        back to standalone -- 'stopped' for this appliance means the
        speakers are free again (for the Sonos app, or a home-theatre
        speaker's TV input), not just silent. play_uri() re-forms the
        group on the next playback."""
        coordinator, members = self._snapshot_selection()
        self._hard_stop(coordinator)
        for member in members:
            try:
                member.unjoin()
            except Exception:
                logger.exception("failed to unjoin %s", member.player_name)

    def get_transport_state(self) -> str:
        """One of 'PLAYING', 'PAUSED_PLAYBACK', 'STOPPED', 'TRANSITIONING', ..."""
        coordinator = self._require_coordinator()
        return coordinator.get_current_transport_info()["current_transport_state"]

    def get_position_seconds(self) -> float | None:
        """Elapsed playback position within the current track, per Sonos --
        we only know the track's total length ourselves (from the disc
        TOC); how far into it Sonos actually is requires asking Sonos.

        Returns None when the coordinator is playing non-track content
        (e.g. a home-theatre speaker's TV/SPDIF input), which reports
        position as 'NOT_IMPLEMENTED' rather than 'H:MM:SS'."""
        coordinator = self._require_coordinator()
        position = coordinator.get_current_track_info()["position"]
        if ":" not in position:
            return None
        return _parse_duration(position)

    def _require_coordinator(self) -> soco.SoCo:
        # Snapshot the coordinator reference under the lock, then release it
        # before the (possibly slow) UPnP call -- holding this lock only
        # protects self._selected's own consistency, not the outgoing
        # network call, so there's no reason to hold it across the latter.
        with self._lock:
            if not self._selected:
                raise RuntimeError("no speakers selected")
            return self._selected[0]

    def _snapshot_selection(self) -> tuple[soco.SoCo, list[soco.SoCo]]:
        """(coordinator, other members) -- same locking pattern as
        _require_coordinator, for callers that touch the whole group."""
        with self._lock:
            if not self._selected:
                raise RuntimeError("no speakers selected")
            return self._selected[0], list(self._selected[1:])
