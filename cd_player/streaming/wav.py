"""Builds a canonical 44-byte WAV header for CD-audio PCM (44.1kHz/16-bit/stereo).

The header is built once, from the exact PCM byte length computed from
the disc TOC, so it (and therefore the HTTP Content-Length) is correct
before any audio has actually been ripped.
"""

from __future__ import annotations

import struct

SAMPLE_RATE = 44_100
BITS_PER_SAMPLE = 16
CHANNELS = 2
WAV_HEADER_SIZE = 44


def build_wav_header(pcm_byte_length: int) -> bytes:
    byte_rate = SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE // 8
    block_align = CHANNELS * BITS_PER_SAMPLE // 8
    riff_chunk_size = 36 + pcm_byte_length

    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", riff_chunk_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),  # fmt chunk size (PCM)
            struct.pack("<H", 1),  # audio format: PCM
            struct.pack("<H", CHANNELS),
            struct.pack("<I", SAMPLE_RATE),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", BITS_PER_SAMPLE),
            b"data",
            struct.pack("<I", pcm_byte_length),
        ]
    )
