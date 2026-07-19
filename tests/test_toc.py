from cd_player.disc.toc import CDDA_BYTES_PER_SECTOR, DiscToc, TrackInfo


def make_toc() -> DiscToc:
    return DiscToc(
        disc_id="fake-disc-id",
        tracks=[
            TrackInfo(number=1, offset_sectors=150, length_sectors=13500),
            TrackInfo(number=2, offset_sectors=13650, length_sectors=9000),
            TrackInfo(number=3, offset_sectors=22650, length_sectors=15000),
        ],
    )


def test_pcm_byte_length_is_exact():
    track = TrackInfo(number=1, offset_sectors=0, length_sectors=100)
    assert track.pcm_byte_length == 100 * CDDA_BYTES_PER_SECTOR


def test_first_and_last_track():
    toc = make_toc()
    assert toc.first_track == 1
    assert toc.last_track == 3


def test_track_lookup():
    toc = make_toc()
    assert toc.track(2).length_sectors == 9000


def test_track_lookup_missing_raises():
    toc = make_toc()
    try:
        toc.track(99)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
