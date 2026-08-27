from pathlib import Path

from cd_player.metadata.cache import DiscMetadata, MetadataCache, TrackMetadata


def make_metadata(disc_id="disc-1") -> DiscMetadata:
    return DiscMetadata(
        disc_id=disc_id,
        mb_release_id="mb-release-1",
        title="Some Album",
        artist="Some Artist",
        artwork_path="/tmp/art.jpg",
        tracks=[TrackMetadata(number=1, title="One"), TrackMetadata(number=2, title="Two")],
    )


def test_get_returns_none_for_unknown_disc(tmp_path):
    cache = MetadataCache(str(tmp_path / "cache.db"))

    assert cache.get("unknown") is None


def test_put_then_get_round_trip(tmp_path):
    cache = MetadataCache(str(tmp_path / "cache.db"))
    metadata = make_metadata()

    cache.put(metadata)

    assert cache.get("disc-1") == metadata


def test_put_replaces_existing_entry(tmp_path):
    cache = MetadataCache(str(tmp_path / "cache.db"))
    cache.put(make_metadata())

    updated = make_metadata()
    updated = DiscMetadata(
        disc_id=updated.disc_id,
        mb_release_id=updated.mb_release_id,
        title="New Title",
        artist=updated.artist,
        artwork_path=updated.artwork_path,
        tracks=[TrackMetadata(number=1, title="Only Track")],
    )
    cache.put(updated)

    assert cache.get("disc-1") == updated


def test_garbage_file_is_recovered_and_cache_still_works(tmp_path):
    db_path = tmp_path / "cache.db"
    db_path.write_bytes(b"not a sqlite database at all" * 50)

    cache = MetadataCache(str(db_path))  # must not raise
    cache.put(make_metadata())

    assert cache.get("disc-1") == make_metadata()


def test_garbage_file_is_quarantined_not_deleted(tmp_path):
    db_path = tmp_path / "cache.db"
    db_path.write_bytes(b"not a sqlite database at all" * 50)

    MetadataCache(str(db_path))

    quarantined = list(tmp_path.glob("cache.db.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"not a sqlite database at all" * 50


def test_truncated_database_is_recovered(tmp_path):
    db_path = tmp_path / "cache.db"
    # Build a real, valid database, then truncate it mid-page to simulate a
    # torn write from an abrupt power-off -- more realistic than pure
    # garbage bytes, and SQLite reports a different error for it
    # ("database disk image is malformed" vs "file is not a database").
    cache = MetadataCache(str(db_path))
    cache.put(make_metadata())
    del cache

    size = db_path.stat().st_size
    with open(db_path, "r+b") as f:
        f.truncate(size // 2)

    recovered = MetadataCache(str(db_path))  # must not raise
    assert recovered.get("disc-1") is None  # old data is gone, but cache is usable
    recovered.put(make_metadata("disc-2"))
    assert recovered.get("disc-2") == make_metadata("disc-2")


def test_fresh_db_path_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "cache.db"

    MetadataCache(str(db_path))

    assert Path(db_path).exists()
