from __future__ import annotations

from flask import Blueprint, jsonify

from cd_player.state import PlayerStateMachine


def build_api_blueprint(player: PlayerStateMachine) -> Blueprint:
    bp = Blueprint("api", __name__)

    @bp.route("/play", methods=["POST"])
    def play():
        try:
            player.play()
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(status=player.status())

    @bp.route("/pause", methods=["POST"])
    def pause():
        player.pause()
        return jsonify(status=player.status())

    @bp.route("/stop", methods=["POST"])
    def stop():
        player.stop()
        return jsonify(status=player.status())

    @bp.route("/skip-forward", methods=["POST"])
    def skip_forward():
        player.skip_forward()
        return jsonify(status=player.status())

    @bp.route("/skip-backward", methods=["POST"])
    def skip_backward():
        player.skip_backward()
        return jsonify(status=player.status())

    @bp.route("/eject", methods=["POST"])
    def eject():
        player.eject()
        return jsonify(status=player.status())

    @bp.route("/status", methods=["GET"])
    def status():
        return jsonify(status=player.status())

    return bp
