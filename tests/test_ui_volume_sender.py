from cd_player.ui.app import VolumeSender


class FakeClient:
    def __init__(self):
        self.calls: list[int] = []

    def set_volume(self, level):
        self.calls.append(level)


def test_update_does_not_send_immediately():
    sender = VolumeSender(FakeClient())

    sender.update(50)

    assert sender._client.calls == []


def test_flush_pending_sends_latest_coalesced_value():
    client = FakeClient()
    sender = VolumeSender(client)

    sender.update(30)
    sender.update(50)  # only the latest matters -- 30 is coalesced away
    sender._flush_pending()

    assert client.calls == [50]


def test_flush_pending_is_noop_with_nothing_pending():
    client = FakeClient()
    sender = VolumeSender(client)

    sender._flush_pending()

    assert client.calls == []


def test_flush_pending_does_not_resend_unchanged_value():
    client = FakeClient()
    sender = VolumeSender(client)

    sender.update(50)
    sender._flush_pending()
    sender.update(50)
    sender._flush_pending()

    assert client.calls == [50]


def test_end_drag_sends_final_value_even_if_never_flushed():
    client = FakeClient()
    sender = VolumeSender(client)

    sender.update(50)  # never flushed before the drag ends

    sender.end_drag(50)

    assert client.calls == [50]


def test_end_drag_does_not_resend_same_value_as_last_sent():
    client = FakeClient()
    sender = VolumeSender(client)

    sender.update(50)
    sender._flush_pending()
    sender.end_drag(50)

    assert client.calls == [50]


def test_end_drag_sends_a_different_final_value():
    client = FakeClient()
    sender = VolumeSender(client)

    sender.update(50)
    sender._flush_pending()
    sender.end_drag(70)

    assert client.calls == [50, 70]


def test_send_failure_is_swallowed_and_does_not_update_last_sent():
    class FailingClient:
        def set_volume(self, level):
            raise ConnectionError("boom")

    sender = VolumeSender(FailingClient())

    sender.update(50)
    sender._flush_pending()  # must not raise

    # last_sent was never updated since the send failed -- a retry of the
    # same value should still be attempted next time.
    assert sender._last_sent is None
