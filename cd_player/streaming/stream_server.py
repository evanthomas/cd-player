"""Range-aware HTTP GET endpoint that serves a RipSession's audio to Sonos
while it is still being ripped.

Every response -- 200 or 206 -- carries a correct Content-Length up front
(known from the disc TOC before ripping starts), since Sonos/DLNA clients
expect a normal seekable resource rather than an open-ended chunked
stream. Requests for not-yet-ripped bytes block on the session's
condition variable instead of racing the writer.
"""

from __future__ import annotations

import logging
import os
import re

from flask import Blueprint, Response, abort, request

from cd_player.disc.ripper import RipSession, RipSessionRegistry
from cd_player.streaming.wav import WAV_HEADER_SIZE

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 64 * 1024
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def build_stream_blueprint(registry: RipSessionRegistry) -> Blueprint:
    bp = Blueprint("stream", __name__)

    @bp.route("/stream/<session_id>.wav")
    def stream(session_id: str):
        # The .wav suffix isn't decorative: Sonos/SoCo infers content type
        # from the URL's file extension when auto-generating DIDL
        # metadata for play_uri(), and rejects extensionless URLs with
        # UPnP error 714 ("Illegal MIME-Type").
        session = registry.get(session_id)
        if session is None:
            abort(404)

        total_length = session.total_content_length
        start, end = 0, total_length - 1
        status = 200

        range_header = request.headers.get("Range")
        if range_header:
            match = RANGE_RE.match(range_header)
            if not match:
                abort(416)
            start_str, end_str = match.groups()
            if not start_str and end_str:
                # Suffix range ("last N bytes") -- not supported in v1,
                # since it would require knowing the final length up
                # front in a way that's ambiguous to satisfy safely.
                abort(416)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else total_length - 1
            if start >= total_length or start > end:
                response = Response(status=416)
                response.headers["Content-Range"] = f"bytes */{total_length}"
                return response
            end = min(end, total_length - 1)
            status = 206

        content_length = end - start + 1
        response = Response(
            _read_range(session, start, end), status=status, mimetype="audio/wav"
        )
        response.headers["Content-Length"] = str(content_length)
        response.headers["Accept-Ranges"] = "bytes"
        if status == 206:
            response.headers["Content-Range"] = f"bytes {start}-{end}/{total_length}"
        return response

    return bp


def _read_range(session: RipSession, start: int, end: int):
    pos = start

    if pos < WAV_HEADER_SIZE:
        header_end = min(end, WAV_HEADER_SIZE - 1)
        yield session.wav_header[pos : header_end + 1]
        pos = header_end + 1
        if pos > end:
            return

    target_pcm_offset = end - WAV_HEADER_SIZE + 1  # exclusive upper bound
    try:
        pcm_fd = os.open(session.pcm_path, os.O_RDONLY)
    except FileNotFoundError:
        logger.warning("session %s pcm file missing, aborting stream", session.session_id)
        return

    try:
        while pos <= end:
            pcm_offset = pos - WAV_HEADER_SIZE
            # Wait only for the next chunk, not the whole requested range --
            # waiting for target_pcm_offset every iteration would block the
            # entire response on the full rip finishing, which for a
            # whole-file request defeats live streaming completely (Sonos
            # would see zero bytes for as long as the rip takes and give up).
            next_chunk_end = min(pcm_offset + READ_CHUNK_SIZE, target_pcm_offset)
            try:
                session.wait_for(next_chunk_end)
            except Exception:
                logger.warning("session %s rip failed mid-stream, truncating response", session.session_id)
                return

            available = min(session.bytes_ripped, target_pcm_offset)
            chunk_size = min(READ_CHUNK_SIZE, available - pcm_offset)
            if chunk_size <= 0:
                return
            os.lseek(pcm_fd, pcm_offset, os.SEEK_SET)
            chunk = os.read(pcm_fd, chunk_size)
            if not chunk:
                return
            yield chunk
            pos += len(chunk)
    finally:
        os.close(pcm_fd)
