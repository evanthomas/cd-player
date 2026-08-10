"""Watches the optical drive for insert/eject via udev and drives metadata
lookup + player state on each event. Never starts playback itself -- that
only ever happens via an explicit REST `play` call.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import replace

import pyudev

from cd_player.disc import toc as toc_module
from cd_player.metadata import coverart, musicbrainz
from cd_player.metadata.cache import MetadataCache
from cd_player.state import PlayerStateMachine

logger = logging.getLogger(__name__)


class DiscMonitor:
    def __init__(
        self,
        device_path: str,
        artwork_cache_dir: str,
        cache: MetadataCache,
        player: PlayerStateMachine,
    ):
        self._device_path = device_path
        # udev events report the canonical /dev/srN node, never the by-id
        # symlink `device_path` is typically configured as -- resolve once
        # up front so runtime events can be matched against it.
        self._device_node = os.path.realpath(device_path)
        self._artwork_cache_dir = artwork_cache_dir
        self._cache = cache
        self._player = player
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem="block")
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._check_initial_state()
        self._thread.start()

    def _check_initial_state(self) -> None:
        try:
            device = pyudev.Devices.from_device_file(self._context, self._device_path)
        except pyudev.DeviceNotFoundByFileError:
            logger.warning("CD device %s not present at startup", self._device_path)
            return
        if device.get("ID_CDROM_MEDIA") == "1":
            self._handle_insert()

    def _run(self) -> None:
        for device in iter(self._monitor.poll, None):
            if device.device_node != self._device_node:
                continue
            if device.get("ID_CDROM_MEDIA") == "1":
                self._handle_insert()
            elif device.action == "change":
                self._handle_eject()

    def _handle_insert(self) -> None:
        logger.info("disc inserted in %s", self._device_path)
        try:
            disc_toc = toc_module.read_toc(self._device_path)
        except Exception:
            logger.exception("failed to read TOC for %s", self._device_path)
            return

        metadata = self._cache.get(disc_toc.disc_id)
        if metadata is None:
            metadata = musicbrainz.lookup_disc(disc_toc.disc_id)
            if metadata is not None:
                if metadata.mb_release_id:
                    artwork_path = coverart.fetch_artwork(
                        metadata.mb_release_id, self._artwork_cache_dir
                    )
                    metadata = replace(metadata, artwork_path=artwork_path)
                self._cache.put(metadata)

        self._player.set_disc(disc_toc, metadata)

    def _handle_eject(self) -> None:
        logger.info("disc ejected from %s", self._device_path)
        self._player.set_disc(None, None)
