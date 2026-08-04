"""Stage 5 acceptance: a full round between two peers on public addresses.

The unit tests prove each piece. This proves the milestone the rulebook states
for stage 5 — *an agent on a remote machine connects through a tunnel and plays
a full round against the local agent* — end to end, with nothing pointing at
loopback.

The opponent here is a second :class:`Orchestrator` constructed with the other
role. It stands in for a remote peer, and it is a **stand-in, not a shortcut**:
the two objects share no state, exchange only serialised dictionaries, and
reach each other exclusively through a transport that routes by URL. If either
side reached into the other, the routing table below would never be consulted
and the test would still pass — which is why the routing is asserted on
directly.

Being able to build both roles in one process is not a separation breach. The
rule forbids the thief and cop *implementations* sharing memory, and this file
imports nothing from the sibling package; ``Orchestrator(role=...)`` is our own
code playing a part.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from thief_agent.infra.handshake import ADDRESS_KEY
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import OPPONENT_URL_ENV, ClientSettings, OpponentClient
from thief_agent.runtime.orchestrator import MatchAborted, Orchestrator

THIEF_URL = "https://thief-c3d4.ngrok-free.app/mcp"
COP_URL = "https://cop-a1b2.ngrok-free.app/mcp"
TURN = {
    "step": 1,
    "sender": "police",
    "hint": "heading for the water",
    "smell_grid": {"3,3": 0.9},
    "commit": "a" * 64,
    "timestamp": "2026-08-04T09:00:00+00:00",
}


class Internet:
    """Routes calls to whichever peer is listening on a URL.

    The whole point of stage 5: a message is addressed, not handed over. A URL
    nobody is serving raises :class:`ConnectionError`, which is what a dead
    tunnel looks like from the other side.
    """

    def __init__(self) -> None:
        self.hosts: dict[str, Orchestrator] = {}
        self.delivered: list[tuple[str, str]] = []

    def listen(self, url: str, peer: Orchestrator) -> None:
        self.hosts[url] = peer

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        del timeout
        if url not in self.hosts:
            raise ConnectionError(f"nothing answers at {url}")
        self.delivered.append((url, tool))
        return self.hosts[url].handle_inbound(tool, payload)


def peer(net: Internet, role: str, ours: str, theirs: str) -> Orchestrator:
    settings = ClientSettings.from_config({"opponent_url": theirs}, environ={})
    orchestrator = Orchestrator(PeerInboxes(), OpponentClient(net, settings), role=role)
    net.listen(ours, orchestrator)
    return orchestrator


@pytest.fixture
def wired() -> tuple[Internet, Orchestrator, Orchestrator]:
    net = Internet()
    thief = peer(net, "thief", THIEF_URL, COP_URL)
    cop = peer(net, "police", COP_URL, THIEF_URL)
    return net, thief, cop


class TestAFullRoundOverPublicAddresses:
    def test_both_peers_are_addressed_by_a_public_url(
        self, wired: tuple[Internet, Orchestrator, Orchestrator]
    ) -> None:
        """Nothing in the wiring points at loopback."""
        net, _, _ = wired
        assert set(net.hosts) == {THIEF_URL, COP_URL}
        assert not any("127.0.0.1" in url or "localhost" in url for url in net.hosts)

    def test_the_handshake_completes_and_the_declaration_names_both(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        net, thief, cop = wired
        ours, theirs = thief.greeting(THIEF_URL, "s82kma9e"), cop.greeting(COP_URL, "them")
        thief.announce(ours)
        cop.announce(theirs)

        book = thief.exchange_addresses(ours, tmp_path, "uoh26-s82kma9e")
        assert book.complete
        written = json.loads((tmp_path / "declaration_uoh26-s82kma9e.json").read_text())
        assert written[ADDRESS_KEY]["thief"]["public_url"] == THIEF_URL
        assert written[ADDRESS_KEY]["police"]["public_url"] == COP_URL
        assert all(entry["reachable"] for entry in written[ADDRESS_KEY].values())

    def test_a_turn_crosses_the_network_and_lands_in_the_mailbox(
        self, wired: tuple[Internet, Orchestrator, Orchestrator]
    ) -> None:
        net, thief, cop = wired
        assert cop.call_opponent("receive_turn", TURN)["ok"] is True
        assert net.delivered == [(THIEF_URL, "receive_turn")]
        assert thief.inboxes.turns.get_nowait().hint == "heading for the water"

    def test_a_full_round_completes_with_no_loopback_traffic(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        """The stage 5 milestone: handshake, then turns, over public addresses."""
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        thief.exchange_addresses(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")

        for step in range(1, 6):
            assert cop.call_opponent("receive_turn", {**TURN, "step": step})["ok"] is True
            assert thief.inboxes.turns.get_nowait().step == step

        assert [url for url, _ in net.delivered] == [THIEF_URL, COP_URL] + [THIEF_URL] * 5

    def test_a_dropped_tunnel_is_a_recorded_abort_rather_than_a_hang(
        self, wired: tuple[Internet, Orchestrator, Orchestrator]
    ) -> None:
        """A URL nobody serves is exactly what a dead tunnel looks like.

        The retry budget is spent and the result is a named cause. A technical
        loss scores zero for both sides, but only a *named* one can be agreed
        and reported — and agreement is required before either team may send
        its result.
        """
        net, thief, _ = wired
        del net.hosts[COP_URL]
        with pytest.raises(MatchAborted, match="nothing answers|after 4 attempts"):
            thief.call_opponent("receive_turn", TURN)


class TestConfiguringTheRemotePeer:
    def test_the_committed_config_is_overridden_for_league_play(self) -> None:
        """One exported variable turns a local run into a remote one."""
        local = ClientSettings.from_config({"opponent_url": "http://127.0.0.1:8802/mcp"}, {})
        remote = ClientSettings.from_config(
            {"opponent_url": "http://127.0.0.1:8802/mcp"}, {OPPONENT_URL_ENV: COP_URL}
        )
        assert local.opponent_url == "http://127.0.0.1:8802/mcp"
        assert remote.opponent_url == COP_URL
