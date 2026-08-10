from __future__ import annotations

import logging

from flask import Flask
from waitress import serve

from cd_player.api.routes import build_api_blueprint
from cd_player.config import Config, load_config
from cd_player.disc.monitor import DiscMonitor
from cd_player.disc.ripper import RipSessionRegistry
from cd_player.metadata.cache import MetadataCache
from cd_player.sonos.controller import SonosController
from cd_player.sonos.poller import SonosPoller
from cd_player.state import PlayerStateMachine
from cd_player.streaming.stream_server import build_stream_blueprint


def create_app(argv: list[str] | None = None) -> tuple[Flask, SonosPoller, DiscMonitor, Config]:
    config = load_config(argv)

    registry = RipSessionRegistry()
    sonos = SonosController(config.sonos_speaker_name)
    player = PlayerStateMachine(config, sonos, registry)
    cache = MetadataCache(config.db_path)

    monitor = DiscMonitor(
        device_path=config.cd_device_path,
        artwork_cache_dir=config.artwork_cache_dir,
        cache=cache,
        player=player,
    )
    poller = SonosPoller(sonos, player, config.sonos_poll_interval_seconds)

    app = Flask(__name__)
    app.register_blueprint(build_api_blueprint(player))
    app.register_blueprint(build_stream_blueprint(registry))

    monitor.start()
    poller.start()

    return app, poller, monitor, config


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app, _poller, _monitor, config = create_app()
    serve(app, host=config.bind_host, port=config.bind_port, threads=8)


if __name__ == "__main__":
    main()
