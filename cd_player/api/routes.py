from __future__ import annotations

from flask import Blueprint, jsonify, request
from soco.exceptions import SoCoException

from cd_player.state import PlayerStateMachine


def build_api_blueprint(player: PlayerStateMachine) -> Blueprint:
    bp = Blueprint("api", __name__)

    def _guarded(action):
        try:
            action()
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except SoCoException as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(status=player.status())

    @bp.route("/play", methods=["POST"])
    def play():
        return _guarded(player.play)

    @bp.route("/pause", methods=["POST"])
    def pause():
        return _guarded(player.pause)

    @bp.route("/stop", methods=["POST"])
    def stop():
        return _guarded(player.stop)

    @bp.route("/skip-forward", methods=["POST"])
    def skip_forward():
        return _guarded(player.skip_forward)

    @bp.route("/skip-backward", methods=["POST"])
    def skip_backward():
        return _guarded(player.skip_backward)

    @bp.route("/eject", methods=["POST"])
    def eject():
        return _guarded(player.eject)

    @bp.route("/status", methods=["GET"])
    def status():
        return jsonify(status=player.status())

    @bp.route("/speakers", methods=["GET"])
    def list_speakers():
        return jsonify(available=player.list_available_speakers())

    @bp.route("/speakers", methods=["POST"])
    def set_speakers():
        body = request.get_json(silent=True) or {}
        names = body.get("names")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return jsonify(error="'names' must be a list of strings"), 400
        return _guarded(lambda: player.set_selected_speakers(names))

    @bp.route("/volume", methods=["POST"])
    def set_volume():
        body = request.get_json(silent=True) or {}
        level = body.get("volume")
        if not isinstance(level, int) or isinstance(level, bool):
            return jsonify(error="'volume' must be an integer"), 400
        return _guarded(lambda: player.set_volume(level))

    return bp
