"""MusicBrainz disc lookup. Takes the first matching release if MusicBrainz
returns more than one for a disc ID -- no disambiguation UI in v1.
"""

from __future__ import annotations

import logging

import musicbrainzngs

from cd_player.metadata.cache import DiscMetadata, TrackMetadata

logger = logging.getLogger(__name__)

musicbrainzngs.set_useragent("cd-player", "0.1.0")


def lookup_disc(disc_id: str) -> DiscMetadata | None:
    try:
        result = musicbrainzngs.get_releases_by_discid(
            disc_id, includes=["recordings", "artist-credits"]
        )
    except musicbrainzngs.ResponseError:
        logger.info("disc id %s not found in MusicBrainz", disc_id)
        return None

    releases = result.get("disc", {}).get("release-list", [])
    if not releases:
        return None
    release = releases[0]

    tracks: list[TrackMetadata] = []
    for medium in release.get("medium-list", []):
        # A multi-disc release (e.g. a box set) has one medium per physical
        # disc, each with its own track 1, 2, 3... -- only the medium whose
        # disc-list contains this disc_id corresponds to what's actually in
        # the drive; the others belong to different physical discs.
        disc_ids = {disc["id"] for disc in medium.get("disc-list", [])}
        if disc_id not in disc_ids:
            continue
        for track in medium.get("track-list", []):
            tracks.append(
                TrackMetadata(
                    number=int(track["position"]),
                    title=track["recording"]["title"],
                )
            )

    return DiscMetadata(
        disc_id=disc_id,
        mb_release_id=release.get("id"),
        title=release.get("title", "Unknown Title"),
        artist=release.get("artist-credit-phrase", "Unknown Artist"),
        artwork_path=None,
        tracks=tracks,
    )
