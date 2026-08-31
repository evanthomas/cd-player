"""Central configuration for the CD player appliance.

All values are read from command-line arguments so the same code runs
unmodified across dev machines and the deployed Pi; defaults target a
typical single-drive, single-speaker Pi setup.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    sonos_speaker_name: str
    cd_device_path: str
    db_path: str
    stream_cache_dir: str
    artwork_cache_dir: str
    bind_host: str
    bind_port: int
    stream_base_url: str
    sonos_poll_interval_seconds: float
    auto_play: bool = False


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cd-player", description="CD player appliance that streams to a Sonos speaker"
    )
    parser.add_argument(
        "--speaker-name",
        required=True,
        help="Room/player name of the target Sonos speaker, as shown in the Sonos app "
        "(e.g. 'Study'). Discovered on the network at startup -- the speaker must be "
        "powered on and reachable.",
    )
    parser.add_argument(
        "--advertise-host",
        required=True,
        help=(
            "This Pi's LAN IP, reachable by the Sonos speaker (used to build stream "
            "URLs). Deliberately separate from --bind-host, which may be 0.0.0.0: "
            "Sonos needs a concrete, routable address to pull audio from."
        ),
    )
    parser.add_argument(
        "--device-path",
        default="/dev/disk/by-id/usb-cd0",
        help="Path to the optical drive. Use a stable /dev/disk/by-id/... symlink, "
        "not /dev/sr0, since drive enumeration order isn't guaranteed (default: %(default)s)",
    )
    parser.add_argument(
        "--db-path",
        default="/var/lib/cd-player/cache.db",
        help="SQLite metadata cache path (default: %(default)s)",
    )
    parser.add_argument(
        "--stream-dir",
        default="/dev/shm/cd-player",
        help="Where in-progress rips are written. Keep this on tmpfs (default: %(default)s)",
    )
    parser.add_argument(
        "--artwork-dir",
        default="/var/lib/cd-player/artwork",
        help="Cached cover art directory (default: %(default)s)",
    )
    parser.add_argument(
        "--bind-host",
        default="0.0.0.0",
        help="Interface the REST/streaming server binds to (default: %(default)s)",
    )
    parser.add_argument(
        "--bind-port",
        type=int,
        default=8080,
        help="Port for the REST/streaming server (default: %(default)s)",
    )
    parser.add_argument(
        "--sonos-poll-interval",
        type=float,
        default=1.5,
        help="Seconds between polls of Sonos's own transport state, used to detect "
        "play/pause triggered from the Sonos app itself (default: %(default)s)",
    )
    parser.add_argument(
        "--auto-play",
        action="store_true",
        help="Start playback automatically as soon as a disc is identified, instead of "
        "requiring an explicit play command. Off by default.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        sonos_speaker_name=args.speaker_name,
        cd_device_path=args.device_path,
        db_path=args.db_path,
        stream_cache_dir=args.stream_dir,
        artwork_cache_dir=args.artwork_dir,
        bind_host=args.bind_host,
        bind_port=args.bind_port,
        stream_base_url=f"http://{args.advertise_host}:{args.bind_port}",
        sonos_poll_interval_seconds=args.sonos_poll_interval,
        auto_play=args.auto_play,
    )


def load_config(argv: list[str] | None = None) -> Config:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return config_from_args(args)
