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
from thief_agent.infra.mcp_transport import (
    UPSTREAM_DEAD,
    FastMcpTransport,
    from_http_client,
    upstream_status,
    why,
)


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
            url, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 10.0
        )
        assert answer["ok"] is True

    def test_the_message_actually_arrives(self, opponent: tuple[str, PeerInboxes]) -> None:
        """Not just a well-formed reply — the payload lands in the queue."""
        url, inboxes = opponent
        FastMcpTransport().call(
            url, "receive_control", {"message": {"kind": "enable", "sender": "thief"}}, 10.0
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
            url, "submit_audit", {"payload": {"sender": "thief", "nonces": {}}}, 10.0
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
        answer = client.call("receive_control", {"message": {"kind": "status", "sender": "thief"}})
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


class TestATunnelAnsweringForADeadPeer:
    """The failure that ended the first live warm-up.

    Locally an absent opponent refuses the connection and the OS says
    ``ECONNREFUSED`` — an ``OSError``, which every retry in the stack already
    understands. Through ngrok the connection *succeeds* and the tunnel answers
    ``502`` on the peer's behalf. Nothing in the retry vocabulary matched, so
    the announcement crashed instead of being retried, and the peer who started
    first always lost.
    """

    class Answering:
        """A client whose context manager fails the way httpx does."""

        status = 502

        def __init__(self, url: str) -> None:
            self.url = url

        async def __aenter__(self) -> "TestATunnelAnsweringForADeadPeer.Answering":
            raise self.error(type(self).status)

        async def __aexit__(self, *exc: object) -> None:
            return None

        @staticmethod
        def error(status: int) -> Exception:
            class Response:
                status_code = status

            class HTTPStatusError(Exception):
                response = Response()

            return HTTPStatusError(
                f"Server error '{status}' for url 'https://x.ngrok-free.app/mcp'"
            )

    def transport_raising(self, status: int, monkeypatch: pytest.MonkeyPatch) -> None:
        client = type("C", (self.Answering,), {"status": status})
        monkeypatch.setattr("thief_agent.infra.mcp_transport.Client", client)

    @pytest.mark.parametrize("status", sorted(UPSTREAM_DEAD))
    def test_a_gateway_reporting_a_dead_peer_is_an_unreachable_peer(
        self, status: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whatever layer says so, the opponent is not answering."""
        self.transport_raising(status, monkeypatch)
        with pytest.raises(ConnectionError, match=str(status)):
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "negotiate", {}, 1.0)

    def test_it_says_what_to_check_rather_than_quoting_the_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'502 Bad Gateway' describes a gateway. It does not describe the problem."""
        self.transport_raising(502, monkeypatch)
        with pytest.raises(ConnectionError) as raised:
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "negotiate", {}, 1.0)
        assert "nothing is listening behind it" in str(raised.value)
        assert "different port" in str(raised.value)

    def test_a_peer_that_answered_is_not_an_unreachable_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 404 came from something that is running. Retrying it reports the wrong failure."""
        self.transport_raising(404, monkeypatch)
        with pytest.raises(Exception) as raised:
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "negotiate", {}, 1.0)
        assert not isinstance(raised.value, ConnectionError)

    def test_an_exception_carrying_no_status_is_left_alone(self) -> None:
        assert upstream_status(ValueError("nothing http about this")) is None

    def test_a_non_numeric_status_is_not_trusted(self) -> None:
        """Read by shape, so the shape has to be checked rather than assumed."""

        class Odd(Exception):
            response = type("R", (), {"status_code": "502"})()

        assert upstream_status(Odd()) is None


class TestTheHttpClientsOwnFailures:
    """`httpx.ConnectError` matched nothing, so a turn died on an unhandled exception.

    It is not an `OSError`, not a `RuntimeError`, and carries no response — the
    three shapes this transport already translated. The retry budget never saw
    it, the transport log never recorded it, and the run ended with
    `ConnectError, which carried no message; caused by ConnectError`.

    Third variant of one mistake: every layer between us and the socket invents
    its own exception hierarchy, and `OpponentClient` classifies by type.
    """

    class Failing:
        error: BaseException = RuntimeError("replaced per test")

        def __init__(self, url: str) -> None:
            self.url = url

        async def __aenter__(self) -> "TestTheHttpClientsOwnFailures.Failing":
            raise type(self).error

        async def __aexit__(self, *exc: object) -> None:
            return None

    def raising(self, error: BaseException, monkeypatch: pytest.MonkeyPatch) -> None:
        client = type("C", (self.Failing,), {"error": error})
        monkeypatch.setattr("thief_agent.infra.mcp_transport.Client", client)

    def test_a_connect_error_becomes_the_vocabulary_the_retry_budget_knows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        self.raising(httpx.ConnectError(""), monkeypatch)
        with pytest.raises(ConnectionError, match="could not reach"):
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "receive_turn", {}, 1.0)

    def test_it_names_the_two_things_that_are_actually_wrong(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A silent ConnectError says nothing. The situation always has a cause."""
        import httpx

        self.raising(httpx.ConnectError(""), monkeypatch)
        with pytest.raises(ConnectionError) as raised:
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "receive_turn", {}, 1.0)
        assert "tunnel" in str(raised.value)
        assert "agent has" in str(raised.value)

    def test_our_own_bugs_are_not_disguised_as_unreachable_opponents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A KeyError here is ours. Retrying it three times would report the wrong thing."""
        self.raising(KeyError("a bug of ours"), monkeypatch)
        with pytest.raises(KeyError):
            FastMcpTransport().call("https://x.ngrok-free.app/mcp", "receive_turn", {}, 1.0)


class TestSayingWhyWhenTheExceptionWillNot:
    def test_the_first_thing_with_something_to_say_wins(self) -> None:
        inner = OSError("connection refused")
        outer = ValueError("")
        outer.__cause__ = inner
        assert "connection refused" in why(outer)

    def test_a_cycle_does_not_trap_it(self) -> None:
        """Same graph shape that already broke one reporter in this project."""
        first, second = ValueError(""), ValueError("")
        first.__cause__, second.__cause__ = second, first
        assert why(first) == "ValueError with no detail"

    def test_a_plain_message_is_used_directly(self) -> None:
        assert why(OSError("no route to host")).startswith("no route to host")

    def test_the_module_test_is_on_the_top_level_package(self) -> None:
        """`httpcore._exceptions.ConnectError` must count as the HTTP client too."""
        import httpcore
        import httpx

        assert from_http_client(httpx.ConnectError(""))
        assert from_http_client(httpcore.ConnectError())
        assert not from_http_client(KeyError("ours"))


class TestOneSessionForTheWholeMatch:
    """The change that makes a tunnelled match survivable.

    Opening a session per tool call means a fresh TLS handshake per call, and a
    35-step sub-game makes a few hundred of them. Free tunnels cap new
    connections, and four consecutive live matches died partway through — as
    502, as ConnectError, and as a failed `start_tls` — for that reason alone.
    """

    def test_a_second_call_reuses_the_first_session(
        self, opponent: tuple[str, PeerInboxes]
    ) -> None:
        live, _ = opponent
        transport = FastMcpTransport()
        try:
            transport.call(
                live, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 5.0
            )
            first = transport._client
            transport.call(
                live, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 5.0
            )
            assert transport._client is first, "reconnected when it did not need to"
        finally:
            transport.close()

    def test_a_new_address_reconnects(self, opponent: tuple[str, PeerInboxes]) -> None:
        """Tunnels rotate mid-series; the re-handshake exists because they do."""
        live, _ = opponent
        transport = FastMcpTransport()
        try:
            transport.call(
                live, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 5.0
            )
            first = transport._client
            transport._connected_to = "http://127.0.0.1:1/mcp"  # pretend we moved
            transport.call(
                live, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 5.0
            )
            assert transport._client is not first
        finally:
            transport.close()

    def test_a_failed_call_does_not_leave_a_broken_session_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One blip must not become a match-ending run of them."""

        class Refusing:
            def __init__(self, url: str) -> None:
                self.url = url

            async def __aenter__(self) -> "Refusing":
                raise OSError("no route to host")

            async def __aexit__(self, *exc: object) -> None:
                return None

        monkeypatch.setattr("thief_agent.infra.mcp_transport.Client", Refusing)
        transport = FastMcpTransport()
        try:
            with pytest.raises(OSError, match="no route to host"):
                transport.call("http://127.0.0.1:1/mcp", "receive_turn", {}, 1.0)
            assert transport._client is None, "kept a session that had already failed"
        finally:
            transport.close()

    def test_closing_twice_is_harmless(self, opponent: tuple[str, PeerInboxes]) -> None:
        """`close` is a courtesy; nothing should depend on calling it exactly once."""
        live, _ = opponent
        transport = FastMcpTransport()
        transport.call(
            live, "receive_control", {"message": {"kind": "status", "sender": "thief"}}, 5.0
        )
        transport.close()
        transport.close()

    def test_closing_without_ever_calling_is_harmless(self) -> None:
        FastMcpTransport().close()

    def test_a_close_that_fails_does_not_replace_the_real_error(self) -> None:
        """Tidying a broken socket must never outrank why the run was ending."""

        class Hostile:
            async def __aexit__(self, *exc: object) -> None:
                raise RuntimeError("the close itself failed")

        transport = FastMcpTransport()
        transport._running_loop()
        transport._client = Hostile()
        transport.drop()
        assert transport._client is None
        transport.close()
