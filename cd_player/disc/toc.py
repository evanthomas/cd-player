"""Disc table-of-contents reading and CDDA byte-length math.

Track lengths in sectors come straight from libdiscid, which already
resolves CD pregap/offset semantics correctly -- so we use them directly
rather than re-deriving lengths from raw offset differences. Sector counts
are exact, so the PCM byte length of a track (and therefore the WAV
Content-Length we'll advertise over HTTP) is known before a single byte
of audio has been ripped.
"""

from __future__ import annotations

from dataclasses import dataclass

CDDA_BYTES_PER_SECTOR = 2352
CDDA_SECTORS_PER_SECOND = 75


@dataclass(frozen=True)
class TrackInfo:
    number: int
    offset_sectors: int
    length_sectors: int

    @property
    def pcm_byte_length(self) -> int:
        return self.length_sectors * CDDA_BYTES_PER_SECTOR


@dataclass(frozen=True)
class DiscToc:
    disc_id: str
    tracks: list[TrackInfo]

    def track(self, number: int) -> TrackInfo:
        for t in self.tracks:
            if t.number == number:
                return t
        raise ValueError(f"no such track: {number}")

    @property
    def first_track(self) -> int:
        return self.tracks[0].number

    @property
    def last_track(self) -> int:
        return self.tracks[-1].number


def read_toc(device_path: str) -> DiscToc:
    import discid  # deferred: needs libdiscid.so, only present on the real Pi

    disc = discid.read(device_path)
    tracks = [
        TrackInfo(number=t.number, offset_sectors=t.offset, length_sectors=t.sectors)
        for t in disc.tracks
    ]
    return DiscToc(disc_id=disc.id, tracks=tracks)
