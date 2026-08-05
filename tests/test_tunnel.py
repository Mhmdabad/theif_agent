"""What the tunnel module has to get right before another team can reach us."""

import json
import urllib.request
from typing import Any

import pytest

from thief_agent.infra.tunnel import (
    MCP_PATH,
    NGROK_API,
    PUBLIC_URL_ENV,
    NotPublicError,
    PublicEndpoint,
    discover,
    from_ngrok,
    host_is_public,
    normalise,
    read_ngrok_api,
    rehearsal_url,
)

PUBLIC = "https://a1b2c3d4.ngrok-free.app"


def ngrok_body(*urls: str) -> str:
    return json.dumps({"tunnels": [{"public_url": u, "proto": u.split(":")[0]} for u in urls]})


class TestWhatCountsAsPublic:
    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "127.1.2.3",
            "::1",
            "localhost",
            "LOCALHOST",
            "agent.localhost",
            "printer.local",
            "svc.internal",
            "10.0.0.7",
            "192.168.1.10",
            "172.16.5.4",
            "169.254.10.1",
            "0.0.0.0",
            "",
            "fe80::1",
            "[::1]",
        ],
    )
    def test_it_refuses_everything_an_opponent_cannot_route_to(self, host: str) -> None:
        assert not host_is_public(host)

    @pytest.mark.parametrize(
        "host",
        ["a1b2.ngrok-free.app", "tunnel.localtonet.com", "8.8.8.8", "2606:4700::1111", "1.1.1.1"],
    )
    def test_it_accepts_addresses_that_route(self, host: str) -> None:
        assert host_is_public(host)

    def test_an_unresolvable_name_is_trusted_rather_than_looked_up(self) -> None:
        """Deciding a name properly needs DNS, and DNS would make this impure.

        The bias is deliberate: a legitimate tunnel host refused because
        resolution was slow costs a match, while an odd name let through is
        caught by the first call that fails.
        """
        assert host_is_public("no-such-host-anywhere.invalid")


class TestNormalising:
    def test_it_appends_the_mcp_path_a_tunnel_never_prints(self) -> None:
        assert normalise(PUBLIC) == f"{PUBLIC}{MCP_PATH}"

    def test_it_keeps_a_path_that_is_already_there(self) -> None:
        assert normalise(f"{PUBLIC}/custom") == f"{PUBLIC}/custom"

    def test_it_drops_a_trailing_slash_so_two_peers_agree_on_one_string(self) -> None:
        assert normalise(f"{PUBLIC}/") == f"{PUBLIC}{MCP_PATH}"

    def test_it_strips_query_and_fragment(self) -> None:
        assert normalise(f"{PUBLIC}/mcp?token=x#frag") == f"{PUBLIC}{MCP_PATH}"

    def test_it_tolerates_the_whitespace_a_copy_paste_brings(self) -> None:
        assert normalise(f"  {PUBLIC}\n") == f"{PUBLIC}{MCP_PATH}"

    @pytest.mark.parametrize("raw", ["ftp://x.example", "a1b2.ngrok-free.app", "ws://x.example"])
    def test_it_refuses_a_scheme_fastmcp_does_not_serve(self, raw: str) -> None:
        with pytest.raises(NotPublicError):
            normalise(raw)

    def test_it_refuses_a_url_with_no_host(self) -> None:
        with pytest.raises(NotPublicError, match="no host"):
            normalise("https:///mcp")


class TestPublicEndpoint:
    def test_it_normalises_on_construction(self) -> None:
        assert PublicEndpoint(f"{PUBLIC}/").url == f"{PUBLIC}{MCP_PATH}"

    def test_it_reports_host_and_tls(self) -> None:
        endpoint = PublicEndpoint(PUBLIC)
        assert endpoint.host == "a1b2c3d4.ngrok-free.app"
        assert endpoint.secure

    def test_http_is_recorded_not_refused(self) -> None:
        """The rulebook requires a public address, not a secure one.

        Localtonet's free tier serves HTTP; refusing it would rule out a
        tunnel the rulebook names by name.
        """
        assert not PublicEndpoint("http://tunnel.localtonet.com").secure

    def test_it_refuses_the_loopback_address_we_developed_against(self) -> None:
        """The whole reason the module exists.

        An opponent handed this cannot reach us; every call times out, the
        deadline converts that into a technical loss, and a technical loss
        scores zero for *both* sides. Catching it at startup costs nothing.
        """
        with pytest.raises(NotPublicError, match="not reachable from another machine"):
            PublicEndpoint("http://127.0.0.1:8801/mcp")

    def test_it_refuses_a_lan_address_that_only_works_on_one_desk(self) -> None:
        with pytest.raises(NotPublicError):
            PublicEndpoint("http://192.168.1.10:8801/mcp")

    def test_it_is_frozen_so_an_advertised_address_cannot_be_edited_later(self) -> None:
        endpoint = PublicEndpoint(PUBLIC)
        with pytest.raises(AttributeError):
            endpoint.url = "http://127.0.0.1:8801/mcp"  # type: ignore[misc]


class TestReadingTheNgrokAgent:
    def test_it_prefers_https_when_the_agent_publishes_both(self) -> None:
        """Free-tier ngrok publishes both for one port.

        Picking arbitrarily would make the address we advertise depend on
        dictionary order, so the same command would hand out different URLs on
        different runs.
        """
        assert from_ngrok(ngrok_body("http://x.ngrok.io", "https://x.ngrok.io")) == (
            "https://x.ngrok.io"
        )

    def test_it_falls_back_to_http(self) -> None:
        assert from_ngrok(ngrok_body("http://x.ngrok.io")) == "http://x.ngrok.io"

    def test_it_accepts_bytes_as_urlopen_returns_them(self) -> None:
        assert from_ngrok(ngrok_body(PUBLIC).encode()) == PUBLIC

    @pytest.mark.parametrize(
        "payload",
        ['{"tunnels": []}', "{}", '{"tunnels": [{"proto": "tcp"}]}', '{"tunnels": null}', "[]"],
    )
    def test_it_refuses_a_response_with_no_usable_tunnel(self, payload: str) -> None:
        with pytest.raises(NotPublicError):
            from_ngrok(payload)

    def test_it_refuses_a_response_that_is_not_json(self) -> None:
        with pytest.raises(NotPublicError, match="no usable JSON"):
            from_ngrok("<html>ngrok is not running</html>")

    def test_it_ignores_a_tcp_tunnel_beside_a_usable_one(self) -> None:
        body = json.dumps(
            {"tunnels": [{"public_url": "tcp://0.tcp.ngrok.io:1"}, {"public_url": PUBLIC}]}
        )
        assert from_ngrok(body) == PUBLIC

    def test_it_fetches_from_the_agents_loopback_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        class Response:
            def read(self) -> bytes:
                return b'{"tunnels": []}'

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_: object) -> None:
                return None

        def fake(url: str, timeout: float) -> Response:
            seen.update(url=url, timeout=timeout)
            return Response()

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        assert read_ngrok_api() == b'{"tunnels": []}'
        assert seen == {"url": NGROK_API, "timeout": 2.0}


class TestDiscovery:
    def test_an_explicit_variable_wins_over_discovery(self) -> None:
        endpoint = discover({PUBLIC_URL_ENV: PUBLIC}, ngrok_reader=lambda: ngrok_body("https://o"))
        assert endpoint is not None
        assert endpoint.host == "a1b2c3d4.ngrok-free.app"

    def test_a_bad_explicit_variable_raises_rather_than_falling_back(self) -> None:
        """Someone who set the variable meant to expose this peer.

        Ignoring their typo and quietly playing on localhost is the outcome
        they would least want, and the one they would notice last.
        """
        with pytest.raises(NotPublicError):
            discover({PUBLIC_URL_ENV: "http://localhost:8801/mcp"}, ngrok_reader=lambda: "")

    def test_it_falls_back_to_the_ngrok_agent(self) -> None:
        endpoint = discover({}, ngrok_reader=lambda: ngrok_body(PUBLIC))
        assert endpoint is not None and endpoint.url == f"{PUBLIC}{MCP_PATH}"

    def test_no_tunnel_running_is_not_an_error(self) -> None:
        """Localhost is permitted while coding.

        An agent that refused to start without a tunnel would make the entire
        local development loop conditional on one running. The refusal belongs
        at the handshake, where an unreachable address would reach an opponent.
        """

        def refused() -> str:
            raise ConnectionRefusedError(111, "Connection refused")

        assert discover({}, ngrok_reader=refused) is None
        assert discover({PUBLIC_URL_ENV: "   "}, ngrok_reader=refused) is None

    def test_discovery_can_be_switched_off_entirely(self) -> None:
        assert discover({}, ngrok_reader=None) is None

    def test_a_running_agent_with_no_usable_tunnel_is_an_error(self) -> None:
        """Different from ngrok being absent, and worth telling apart.

        Absent means "not exposed yet"; running-but-broken means the operator
        believes they are exposed and are not.
        """
        with pytest.raises(NotPublicError):
            discover({}, ngrok_reader=lambda: '{"tunnels": []}')


class TestRehearsingAgainstOurselves:
    """Loopback is allowed only when a caller asks for it by name.

    A solo rehearsal over a public tunnel opens a fresh TLS connection per tool
    call, and a free tunnel stops accepting them well before a sub-game ends —
    so the network decides how far practice gets, not the game. Over loopback
    there is no tunnel to exhaust.
    """

    def test_loopback_is_allowed_here_and_nowhere_else(self) -> None:
        assert rehearsal_url({"PUBLIC_URL": "http://127.0.0.1:8801"}) == "http://127.0.0.1:8801/mcp"
        with pytest.raises(NotPublicError):
            PublicEndpoint("http://127.0.0.1:8801")

    def test_it_falls_back_to_this_agents_own_port(self) -> None:
        """So a rehearsal needs no environment at all."""
        assert rehearsal_url({}, 8801) == "http://127.0.0.1:8801/mcp"

    def test_the_mcp_path_is_still_appended(self) -> None:
        assert rehearsal_url({"PUBLIC_URL": "http://localhost:8802"}).endswith("/mcp")

    def test_a_typo_is_still_a_typo(self) -> None:
        """Being a rehearsal excuses a private host, not a malformed address."""
        with pytest.raises(NotPublicError):
            rehearsal_url({"PUBLIC_URL": "127.0.0.1:8801"})
