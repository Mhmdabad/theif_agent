"""A real call, over a real server, through the real client.

These are the only tests in the project that start a listener. They are here
because the thing under test *is* the socket: everything above it — deadlines,
retries, relocation — is already covered against the Protocol without one, and
covering this layer the same way would test nothing at all.
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import (
    ClientSettings,
    OpponentClient,
    OpponentUnreachableError,
    Transport,
)
from thief_agent.infra.mcp_server import ServerSettings, build, serve
from thief_agent.infra.mcp_transport import FastMcpTransport


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    return port


@pytest.fixture(scope="module")
def opponent() -> Iterator[tuple[str, PeerInboxes]]:
    """A real server on a real port, for the length of this module."""
    inboxes = PeerInboxes()
    port = free_port()
    host = build(inboxes, name="stand-in-opponent")
    thread = threading.Thread(
        target=serve,
        args=(host, ServerSettings(port=port, host="127.0.0.1")),
        daemon=True,
    )
    thread.start()

    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:  # pragma: no cover - only on a machine that cannot bind at all
        pytest.fail("the stand-in opponent never came up")

    yield url, inboxes


class TestARealCall:
    def test_it_reaches_the_opponents_inboxes(self, opponent: tuple[str, PeerInboxes]) -> None:
        url, _ = opponent
        answer = FastMcpTransport().call(
            url, "receive_control", {"message": {"kind": "status", "sender": "police"}}, 10.0
        )
        assert answer["ok"] is True

    def test_the_message_actually_arrives(self, opponent: tuple[str, PeerInboxes]) -> None:
        """Not just a well-formed reply — the payload lands in the queue."""
        url, inboxes = opponent
        FastMcpTransport().call(
            url, "receive_control", {"message": {"kind": "enable", "sender": "police"}}, 10.0
        )
        assert not inboxes.controls.empty()

    def test_a_refusal_comes_back_as_a_value(self, opponent: tuple[str, PeerInboxes]) -> None:
        url, _ = opponent
        answer = FastMcpTransport().call(
            url, "receive_control", {"message": {"kind": "nonsense"}}, 10.0
        )
        assert answer["ok"] is False

    def test_submit_audit_uses_payload(self, opponent: tuple[str, PeerInboxes]) -> None:
        url, _ = opponent
        answer = FastMcpTransport().call(
            url, "submit_audit", {"payload": {"sender": "police", "nonces": {}}}, 10.0
        )
        assert "ok" in answer


class TestItSatisfiesTheProtocol:
    def test_it_is_usable_as_a_transport(self) -> None:
        """Structurally, without declaring the inheritance."""
        transport: Transport = FastMcpTransport()
        assert callable(transport.call)

    def test_the_real_client_drives_it(self, opponent: tuple[str, PeerInboxes]) -> None:
        """The whole outbound path: OpponentClient policy over a real socket.

        This is the seam the project has never crossed — retries, deadlines and
        the frozen payload have only ever run against fakes.
        """
        url, _ = opponent
        client = OpponentClient(
            transport=FastMcpTransport(), settings=ClientSettings(opponent_url=url)
        )
        answer = client.call("receive_control", {"message": {"kind": "status", "sender": "police"}})
        assert answer["ok"] is True
        assert client.sent, "the transport log recorded nothing about a real call"


class TestFailuresTravelUpUntranslated:
    def test_an_unreachable_port_raises_rather_than_returning(self) -> None:
        """McpClient decides what a failure means; this layer does not guess."""
        with pytest.raises(Exception, match=r".+"):
            FastMcpTransport().call(
                f"http://127.0.0.1:{free_port()}/mcp", "receive_control", {"message": {}}, 2.0
            )

    def test_the_retry_budget_converts_it_into_unreachable(self) -> None:
        """The policy above turns a dead peer into the one failure that matters."""
        client = OpponentClient(
            transport=FastMcpTransport(),
            settings=ClientSettings(
                opponent_url=f"http://127.0.0.1:{free_port()}/mcp",
                response_timeout_sec=2.0,
                max_retries=1,
                retry_backoff_sec=0.0,
            ),
        )
        with pytest.raises(OpponentUnreachableError):
            client.call("receive_control", {"message": {}})


class TestANonMappingResultIsAProtocolViolation:
    def test_it_is_named_rather_than_coerced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A peer answering with a bare value is not speaking this protocol."""

        class Answer:
            data = "not a mapping"

        class FakeClient:
            def __init__(self, url: str) -> None:
                self.url = url

            async def __aenter__(self) -> "FakeClient":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

            async def call_tool(self, name: str, arguments: object, timeout: float) -> Answer:
                return Answer()

        monkeypatch.setattr("thief_agent.infra.mcp_transport.Client", FakeClient)
        with pytest.raises(TypeError, match="is not speaking it"):
            FastMcpTransport().call("http://x/mcp", "receive_control", {}, 1.0)

    def test_an_already_correct_exception_is_not_re_wrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only FastMCP's RuntimeError needs translating; the rest is right already.

        Wrapping an ``OSError`` in a ``ConnectionError`` would work and would
        lose the original type for no reason — the retry budget already
        understands it.
        """

        class Refusing:
            def __init__(self, url: str) -> None:
                self.url = url

            async def __aenter__(self) -> "Refusing":
                raise OSError("no route to host")

            async def __aexit__(self, *exc: object) -> None:
                return None

        monkeypatch.setattr("thief_agent.infra.mcp_transport.Client", Refusing)
        with pytest.raises(OSError, match="no route to host") as raised:
            FastMcpTransport().call("http://x/mcp", "receive_control", {}, 1.0)
        assert type(raised.value) is OSError, "an OSError became something else"
