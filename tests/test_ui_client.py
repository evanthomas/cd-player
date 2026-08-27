from unittest.mock import Mock, patch

from cd_player.ui.client import PlayerClient


def make_response(json_body=None, status_code=200):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def test_get_status_hits_status_endpoint_and_unwraps():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.get") as get:
        get.return_value = make_response({"status": {"state": "stopped"}})

        status = client.get_status()

        get.assert_called_once_with("http://localhost:8080/status", timeout=3.0)
        assert status == {"state": "stopped"}


def test_base_url_trailing_slash_is_stripped():
    client = PlayerClient("http://localhost:8080/")
    with patch("cd_player.ui.client.requests.get") as get:
        get.return_value = make_response({"status": {}})
        client.get_status()
        get.assert_called_once_with("http://localhost:8080/status", timeout=3.0)


def test_eject_posts_to_eject_endpoint():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.post") as post:
        post.return_value = make_response()
        client.eject()
        post.assert_called_once_with("http://localhost:8080/eject", json=None, timeout=3.0)


def test_play_pause_skip_post_expected_endpoints():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.post") as post:
        post.return_value = make_response()

        client.play()
        client.pause()
        client.skip_forward()
        client.skip_backward()

        paths = [call.args[0] for call in post.call_args_list]
        assert paths == [
            "http://localhost:8080/play",
            "http://localhost:8080/pause",
            "http://localhost:8080/skip-forward",
            "http://localhost:8080/skip-backward",
        ]


def test_get_available_speakers_hits_speakers_endpoint_with_longer_timeout():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.get") as get:
        get.return_value = make_response({"available": ["Study", "Kitchen"]})

        speakers = client.get_available_speakers()

        get.assert_called_once_with("http://localhost:8080/speakers", timeout=8.0)
        assert speakers == ["Study", "Kitchen"]


def test_set_selected_speakers_posts_names_with_longer_timeout():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.post") as post:
        post.return_value = make_response()

        client.set_selected_speakers(["Study", "Kitchen"])

        post.assert_called_once_with(
            "http://localhost:8080/speakers",
            json={"names": ["Study", "Kitchen"]},
            timeout=8.0,
        )


def test_set_volume_posts_volume():
    client = PlayerClient("http://localhost:8080")
    with patch("cd_player.ui.client.requests.post") as post:
        post.return_value = make_response()

        client.set_volume(42)

        post.assert_called_once_with(
            "http://localhost:8080/volume", json={"volume": 42}, timeout=3.0
        )
