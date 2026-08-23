import pytest

from thief_agent.counted_v3_wire import send_step_zero


class Tool:
    def __init__(self) -> None:
        self.calls = 0

    def call_tool(self, _name: str, _arguments: object) -> object:
        self.calls += 1
        return object()


class Client:
    def __init__(self) -> None:
        self._client = Tool()
        self._entered = True

    def _ensure_session(self) -> None:
        return None

    def _await(self, _call: object) -> None:
        raise TimeoutError("response lost after delivery")


def test_step_zero_is_never_retried_after_an_ambiguous_failure() -> None:
    client = Client()
    tool = client._client
    with pytest.raises(RuntimeError, match="response lost after delivery"):
        send_step_zero(client, {"declaration": {}, "auth": {}})
    assert tool.calls == 1
    assert client._entered is False
    assert client._client is None
