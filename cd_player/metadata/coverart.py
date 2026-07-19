"""Fetches and caches front cover art from the Cover Art Archive."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

COVER_ART_ARCHIVE_URL = "https://coverartarchive.org/release/{release_id}/front"


def fetch_artwork(release_id: str, cache_dir: str) -> str | None:
    os.makedirs(cache_dir, exist_ok=True)
    dest_path = os.path.join(cache_dir, f"{release_id}.jpg")
    if os.path.exists(dest_path):
        return dest_path

    try:
        response = requests.get(
            COVER_ART_ARCHIVE_URL.format(release_id=release_id), timeout=10
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.info("no cover art available for release %s", release_id)
        return None

    with open(dest_path, "wb") as f:
        f.write(response.content)
    return dest_path
