"""SQLite cache of disc metadata, keyed by MusicBrainz disc ID, so
re-inserting a known disc doesn't need network access.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS discs (
    disc_id TEXT PRIMARY KEY,
    mb_release_id TEXT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    artwork_path TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    disc_id TEXT NOT NULL REFERENCES discs(disc_id),
    track_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (disc_id, track_number)
);
"""


@dataclass(frozen=True)
class TrackMetadata:
    number: int
    title: str


@dataclass(frozen=True)
class DiscMetadata:
    disc_id: str
    mb_release_id: str | None
    title: str
    artist: str
    artwork_path: str | None
    tracks: list[TrackMetadata] = field(default_factory=list)


class MetadataCache:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open(db_path)

    def _open(self, db_path: str) -> sqlite3.Connection:
        # This is just a cache -- every row is cheaply re-derivable from
        # MusicBrainz/the Cover Art Archive on the next disc insert -- so a
        # corrupt file (e.g. a torn write from this appliance being power-
        # cycled rather than shut down cleanly) must never prevent the app
        # from starting. Move the bad file aside (for later inspection, not
        # silently discarded) and start over with a fresh one.
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        except sqlite3.DatabaseError:
            logger.exception("metadata cache at %s is corrupt -- recreating it", db_path)
            conn.close()
            self._quarantine(db_path)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.executescript(SCHEMA)
            conn.commit()
        return conn

    @staticmethod
    def _quarantine(db_path: str) -> None:
        suffix = f".corrupt-{int(time.time())}"
        for path in [Path(db_path), *Path(db_path).parent.glob(Path(db_path).name + "-*")]:
            if path.exists():
                path.rename(path.with_name(path.name + suffix))

    def get(self, disc_id: str) -> DiscMetadata | None:
        cur = self._conn.execute(
            "SELECT mb_release_id, title, artist, artwork_path FROM discs WHERE disc_id = ?",
            (disc_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        mb_release_id, title, artist, artwork_path = row
        tracks = [
            TrackMetadata(number=n, title=t)
            for n, t in self._conn.execute(
                "SELECT track_number, title FROM tracks WHERE disc_id = ? ORDER BY track_number",
                (disc_id,),
            )
        ]
        return DiscMetadata(
            disc_id=disc_id,
            mb_release_id=mb_release_id,
            title=title,
            artist=artist,
            artwork_path=artwork_path,
            tracks=tracks,
        )

    def put(self, metadata: DiscMetadata) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO discs
                   (disc_id, mb_release_id, title, artist, artwork_path)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    metadata.disc_id,
                    metadata.mb_release_id,
                    metadata.title,
                    metadata.artist,
                    metadata.artwork_path,
                ),
            )
            self._conn.execute("DELETE FROM tracks WHERE disc_id = ?", (metadata.disc_id,))
            self._conn.executemany(
                "INSERT INTO tracks (disc_id, track_number, title) VALUES (?, ?, ?)",
                [(metadata.disc_id, t.number, t.title) for t in metadata.tracks],
            )
