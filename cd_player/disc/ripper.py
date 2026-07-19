"""Live CD ripping into a growing tmpfs file that the streaming server
reads from concurrently while it's still being written.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading

from cd_player.disc.toc import TrackInfo
from cd_player.streaming.wav import WAV_HEADER_SIZE, build_wav_header

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 64 * 1024


class RipSession:
    """Owns one cdparanoia subprocess ripping a single track, and the
    growing tmpfs file it writes into. `bytes_ripped` only advances after
    a chunk has been fully written and flushed, so readers never observe
    a torn write.
    """

    def __init__(self, session_id: str, device_path: str, track: TrackInfo, cache_dir: str):
        self.session_id = session_id
        self.track = track
        self.pcm_byte_length = track.pcm_byte_length
        self.wav_header = build_wav_header(self.pcm_byte_length)
        self.total_content_length = WAV_HEADER_SIZE + self.pcm_byte_length

        os.makedirs(cache_dir, exist_ok=True)
        self.pcm_path = os.path.join(cache_dir, f"{session_id}.pcm")

        self._device_path = device_path
        self._condition = threading.Condition()
        self._bytes_ripped = 0
        self._rip_complete = False
        self._error: Exception | None = None
        self._process: subprocess.Popen | None = None
        self._pump_thread: threading.Thread | None = None
        # Set by stop() before terminating the subprocess, so _pump can
        # tell an intentional shutdown apart from a genuine rip failure --
        # cdparanoia exiting via SIGTERM looks identical to it crashing.
        self._stopping = threading.Event()

    def start(self) -> None:
        # Create the file synchronously, before the pump thread exists, so
        # a reader can never race it and see "file does not exist" for a
        # session that has, from the caller's perspective, already
        # started (e.g. Sonos's first GET landing before the background
        # thread gets scheduled).
        open(self.pcm_path, "wb").close()
        self._process = subprocess.Popen(
            ["cdparanoia", "-r", "-d", self._device_path, str(self.track.number), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._pump_thread = threading.Thread(target=self._pump, daemon=True)
        self._pump_thread.start()

    def _pump(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            with open(self.pcm_path, "wb") as out:
                while True:
                    chunk = self._process.stdout.read(READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    out.flush()
                    with self._condition:
                        self._bytes_ripped += len(chunk)
                        self._condition.notify_all()
            self._process.wait()
            if self._process.returncode not in (0, None) and not self._stopping.is_set():
                stderr = self._process.stderr.read() if self._process.stderr else b""
                raise RuntimeError(
                    f"cdparanoia exited {self._process.returncode} "
                    f"ripping track {self.track.number}: {stderr.decode(errors='replace')}"
                )
        except Exception as exc:  # noqa: BLE001 - must propagate to blocked HTTP readers
            logger.exception("rip failed for session %s", self.session_id)
            with self._condition:
                self._error = exc
                self._condition.notify_all()
        finally:
            with self._condition:
                self._rip_complete = True
                self._condition.notify_all()

    def wait_for(self, byte_offset: int, timeout: float | None = None) -> None:
        """Block until at least `byte_offset` PCM bytes have been ripped."""
        with self._condition:
            while (
                self._bytes_ripped < byte_offset
                and not self._rip_complete
                and not self._error
            ):
                if not self._condition.wait(timeout=timeout):
                    raise TimeoutError(f"timed out waiting for byte offset {byte_offset}")
            if self._error is not None and self._bytes_ripped < byte_offset:
                raise self._error

    @property
    def bytes_ripped(self) -> int:
        with self._condition:
            return self._bytes_ripped

    @property
    def is_complete(self) -> bool:
        """True once the cdparanoia process has exited (successfully or
        not) and the drive is therefore free for another rip to use.
        """
        with self._condition:
            return self._rip_complete

    @property
    def error(self) -> Exception | None:
        with self._condition:
            return self._error

    def stop(self) -> None:
        """Tear down the session: kill the rip subprocess and delete the tmpfs file."""
        self._stopping.set()
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=5)
        try:
            os.remove(self.pcm_path)
        except FileNotFoundError:
            pass


class RipSessionRegistry:
    """Thread-safe lookup from stream URL session id to RipSession, so the
    streaming server's request handlers never touch player state directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, RipSession] = {}

    def add(self, session: RipSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> RipSession | None:
        with self._lock:
            return self._sessions.get(session_id)
