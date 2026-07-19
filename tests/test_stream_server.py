import os
import tempfile
import threading
import time

import pytest
from flask import Flask

from cd_player.streaming.stream_server import _read_range, build_stream_blueprint


class TrickleSession:
    """Mimics RipSession's public surface used by the stream server, but
    writes bytes on a background thread with a small delay between
    chunks -- so tests exercise the block-until-ripped behavior for real.
    """

    def __init__(self, pcm_path: str, data: bytes, chunk_size: int = 8, delay: float = 0.01):
        self.session_id = "test-session"
        self.pcm_path = pcm_path
        self.wav_header = b"H" * 44
        self.total_content_length = 44 + len(data)
        self._data = data
        self._chunk_size = chunk_size
        self._delay = delay
        self._condition = threading.Condition()
        self._bytes_ripped = 0
        self._rip_complete = False

    def start_ripping(self):
        # Mirrors RipSession.start(): the file must exist synchronously,
        # before the background thread is even scheduled, so a reader can
        # never race it and see "file does not exist".
        open(self.pcm_path, "wb").close()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        with open(self.pcm_path, "wb") as f:
            for i in range(0, len(self._data), self._chunk_size):
                chunk = self._data[i : i + self._chunk_size]
                f.write(chunk)
                f.flush()
                with self._condition:
                    self._bytes_ripped += len(chunk)
                    self._condition.notify_all()
                time.sleep(self._delay)
        with self._condition:
            self._rip_complete = True
            self._condition.notify_all()

    def wait_for(self, byte_offset, timeout=None):
        with self._condition:
            while self._bytes_ripped < byte_offset and not self._rip_complete:
                if not self._condition.wait(timeout=timeout):
                    raise TimeoutError()

    @property
    def bytes_ripped(self):
        with self._condition:
            return self._bytes_ripped


class FakeRegistry:
    def __init__(self, session):
        self._session = session

    def get(self, session_id):
        return self._session if session_id == self._session.session_id else None


@pytest.fixture
def client(tmp_path):
    data = bytes(range(256)) * 4  # 1024 bytes of deterministic PCM "audio"
    pcm_path = os.path.join(tmp_path, "track.pcm")
    session = TrickleSession(pcm_path, data)
    registry = FakeRegistry(session)

    app = Flask(__name__)
    app.register_blueprint(build_stream_blueprint(registry))

    session.start_ripping()
    with app.test_client() as c:
        yield c, session, data


def test_full_stream_blocks_until_fully_ripped(client):
    c, session, data = client
    resp = c.get(f"/stream/{session.session_id}.wav")

    assert resp.status_code == 200
    assert resp.headers["Content-Length"] == str(44 + len(data))
    assert resp.data == session.wav_header + data


def test_range_request_within_header_only(client):
    c, session, _data = client
    resp = c.get(f"/stream/{session.session_id}.wav", headers={"Range": "bytes=0-9"})

    assert resp.status_code == 206
    assert resp.data == session.wav_header[0:10]
    assert resp.headers["Content-Range"] == f"bytes 0-9/{session.total_content_length}"


def test_range_request_spanning_header_and_pcm(client):
    c, session, data = client
    resp = c.get(f"/stream/{session.session_id}.wav", headers={"Range": "bytes=40-49"})

    assert resp.status_code == 206
    expected = (session.wav_header + data)[40:50]
    assert resp.data == expected


def test_open_ended_range_request(client):
    c, session, data = client
    resp = c.get(f"/stream/{session.session_id}.wav", headers={"Range": "bytes=44-"})

    assert resp.status_code == 206
    assert resp.data == data


def test_range_start_beyond_total_length_is_416(client):
    c, session, _data = client
    resp = c.get(
        f"/stream/{session.session_id}.wav",
        headers={"Range": f"bytes={session.total_content_length + 100}-"},
    )
    assert resp.status_code == 416


def test_suffix_range_is_rejected(client):
    c, session, _data = client
    resp = c.get(f"/stream/{session.session_id}.wav", headers={"Range": "bytes=-100"})
    assert resp.status_code == 416


def test_unknown_session_is_404(client):
    c, _session, _data = client
    resp = c.get("/stream/does-not-exist.wav")
    assert resp.status_code == 404


def test_full_request_streams_incrementally_not_only_at_completion(tmp_path):
    """A whole-file (non-Range) request must start yielding PCM chunks as
    soon as they're ripped, not block until the entire track is ripped.

    Regression test for a real bug found against a live Sonos speaker:
    _read_range originally called session.wait_for(target_pcm_offset) --
    the *end* of the requested range -- on every loop iteration, so a
    full-file request waited for the whole rip before sending a single
    PCM byte past the header. Sonos saw no data for the entire rip
    duration and gave up. A Flask test-client test can't catch this: it
    buffers the whole generator into resp.data and only checks the final
    bytes, never delivery timing.
    """
    # Must be larger than the server's READ_CHUNK_SIZE (64KB) -- otherwise
    # "wait for the next chunk" and "wait for the whole file" are the same
    # thing regardless of the fix, and this test can't tell them apart.
    data = bytes(range(256)) * 800  # 204800 bytes (~3.1x READ_CHUNK_SIZE)
    chunk_size, delay = 2048, 0.01
    total_rip_seconds = (len(data) / chunk_size) * delay  # ~1.0s

    pcm_path = os.path.join(tmp_path, "track.pcm")
    session = TrickleSession(pcm_path, data, chunk_size=chunk_size, delay=delay)
    session.start_ripping()

    gen = _read_range(session, 0, session.total_content_length - 1)
    t0 = time.time()
    header_chunk = next(gen)
    assert header_chunk == session.wav_header

    first_pcm_chunk = next(gen)
    elapsed = time.time() - t0

    assert len(first_pcm_chunk) > 0
    assert elapsed < total_rip_seconds * 0.6, (
        f"first PCM chunk took {elapsed:.2f}s to arrive, expected well under "
        f"{total_rip_seconds:.2f}s (full rip time) -- looks like it waited for the full rip"
    )

    for _ in gen:  # drain so the background ripping thread can finish cleanly
        pass
