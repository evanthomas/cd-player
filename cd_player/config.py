"""Central configuration for the CD player appliance.

All values are read from environment variables so the same code runs
unmodified across dev machines and the deployed Pi; defaults target a
typical single-drive, single-speaker Pi setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    sonos_speaker_ip: str
    cd_device_path: str
    db_path: str
    stream_cache_dir: str
    artwork_cache_dir: str
    bind_host: str
    bind_port: int
    stream_base_url: str
    sonos_poll_interval_seconds: float


def load_config() -> Config:
    sonos_speaker_ip = os.environ.get("CD_PLAYER_SONOS_IP")
    if not sonos_speaker_ip:
        raise RuntimeError(
            "CD_PLAYER_SONOS_IP must be set to the fixed target Sonos speaker's IP address"
        )

    bind_host = os.environ.get("CD_PLAYER_BIND_HOST", "0.0.0.0")
    bind_port = int(os.environ.get("CD_PLAYER_BIND_PORT", "8080"))

    # Sonos must be able to reach this host:port over the LAN to pull the
    # audio stream; it is deliberately separate from bind_host (which may be
    # 0.0.0.0) since Sonos needs a concrete, routable address.
    stream_advertise_host = os.environ.get("CD_PLAYER_ADVERTISE_HOST")
    if not stream_advertise_host:
        raise RuntimeError(
            "CD_PLAYER_ADVERTISE_HOST must be set to this Pi's LAN IP, "
            "reachable by the Sonos speaker"
        )

    return Config(
        sonos_speaker_ip=sonos_speaker_ip,
        cd_device_path=os.environ.get(
            "CD_PLAYER_DEVICE_PATH", "/dev/disk/by-id/usb-cd0"
        ),
        db_path=os.environ.get("CD_PLAYER_DB_PATH", "/var/lib/cd-player/cache.db"),
        stream_cache_dir=os.environ.get("CD_PLAYER_STREAM_DIR", "/dev/shm/cd-player"),
        artwork_cache_dir=os.environ.get(
            "CD_PLAYER_ARTWORK_DIR", "/var/lib/cd-player/artwork"
        ),
        bind_host=bind_host,
        bind_port=bind_port,
        stream_base_url=f"http://{stream_advertise_host}:{bind_port}",
        sonos_poll_interval_seconds=float(
            os.environ.get("CD_PLAYER_SONOS_POLL_INTERVAL", "1.5")
        ),
    )
