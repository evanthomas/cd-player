"""Thin wrapper around SoCo, bound to one fixed, pre-configured speaker."""

from __future__ import annotations

from xml.sax.saxutils import escape

import soco
from soco.discovery import by_name


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
        self._device: soco.SoCo = device

    def play_uri(self, url: str, title: str = "", duration_seconds: float = 0.0) -> None:
        meta = _build_track_metadata(title, url, duration_seconds)
        self._device.play_uri(url, meta=meta)

    def play(self) -> None:
        self._device.play()

    def pause(self) -> None:
        self._device.pause()

    def stop(self) -> None:
        self._device.stop()
        # UPnP Stop halts playback but leaves the last URI loaded, so the
        # Sonos app still shows our track as the current source even
        # though nothing is playing -- clearing CurrentURI is what makes
        # "stop" actually read as disconnected rather than just paused.
        self._device.avTransport.SetAVTransportURI(
            [("InstanceID", 0), ("CurrentURI", ""), ("CurrentURIMetaData", "")]
        )

    def get_transport_state(self) -> str:
        """One of 'PLAYING', 'PAUSED_PLAYBACK', 'STOPPED', 'TRANSITIONING', ..."""
        return self._device.get_current_transport_info()["current_transport_state"]

    def get_position_seconds(self) -> float:
        """Elapsed playback position within the current track, per Sonos --
        we only know the track's total length ourselves (from the disc
        TOC); how far into it Sonos actually is requires asking Sonos."""
        return _parse_duration(self._device.get_current_track_info()["position"])
