"""Thin REST client for the touchscreen UI -- talks to the same POST/GET
endpoints as curl or the Sonos app, nothing player-internal. Runs in a
separate process from cd-player itself (see CLAUDE.md), so a UI crash
never touches the audio-critical ripping/streaming code.
"""

from __future__ import annotations

import requests


class PlayerClient:
    def __init__(self, base_url: str, timeout: float = 3.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_status(self) -> dict:
        resp = requests.get(f"{self._base_url}/status", timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()["status"]

    def play(self) -> None:
        self._post("/play")

    def pause(self) -> None:
        self._post("/pause")

    def skip_forward(self) -> None:
        self._post("/skip-forward")

    def skip_backward(self) -> None:
        self._post("/skip-backward")

    def eject(self) -> None:
        self._post("/eject")

    def _post(self, path: str) -> None:
        resp = requests.post(f"{self._base_url}{path}", timeout=self._timeout)
        resp.raise_for_status()
