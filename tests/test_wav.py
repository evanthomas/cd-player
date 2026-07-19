import struct

from cd_player.streaming.wav import WAV_HEADER_SIZE, build_wav_header


def test_header_is_exactly_44_bytes():
    header = build_wav_header(1000)
    assert len(header) == WAV_HEADER_SIZE == 44


def test_header_markers_and_sizes():
    pcm_len = 12345
    header = build_wav_header(pcm_len)

    assert header[0:4] == b"RIFF"
    assert header[8:12] == b"WAVE"
    assert header[12:16] == b"fmt "
    assert header[36:40] == b"data"

    riff_size = struct.unpack("<I", header[4:8])[0]
    assert riff_size == 36 + pcm_len

    data_size = struct.unpack("<I", header[40:44])[0]
    assert data_size == pcm_len

    channels = struct.unpack("<H", header[22:24])[0]
    sample_rate = struct.unpack("<I", header[24:28])[0]
    bits_per_sample = struct.unpack("<H", header[34:36])[0]
    assert channels == 2
    assert sample_rate == 44_100
    assert bits_per_sample == 16
