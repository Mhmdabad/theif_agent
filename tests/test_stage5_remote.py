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

from thief_agent.domain.outcome import TechnicalLoss
from thief_agent.infra.handshake import ADDRESS_KEY, Greeting, Peering
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import OPPONENT_URL_ENV, ClientSettings, OpponentClient
from thief_agent.runtime.orchestrator import PROTOCOL_VERSION, MatchAborted, Orchestrator

THIEF_URL = "https://thief-c3d4.ngrok-free.app/mcp"
COP_URL = "https://cop-a1b2.ngrok-free.app/mcp"
MOVED_COP_URL = "https://cop-e5f6.ngrok-free.app/mcp"
MOVED_THIEF_URL = "https://thief-9z8y.ngrok-free.app/mcp"
TURN = {
    "step": 1,
    "sender": "police",
    "hint": "heading for the water",
    "smell_grid": {"3,3": 0.9},
    "commit": "a" * 64,
    "timestamp": "2026-08-04T09:00:00+00:00",
    "game_uid": "series-123",
    "sub_game": 1,
}


def unbind(payload: dict[str, Any]) -> Any:  # noqa: ANN401 - whatever the tool takes
    """The body FastMCP would pass, from the payload the client sent.

    Every tool in this protocol takes exactly one argument, so the body is the
    single value. Anything else is a payload a real server would refuse, and
    refusing it here is the point.
    """
    if len(payload) != 1:
        raise TypeError(f"a tool takes one argument; got {sorted(payload)}")
    return next(iter(payload.values()))


class Internet:
    """Routes calls to whichever peer is listening on a URL.

    The whole point of stage 5: a message is addressed, not handed over. A URL
    nobody is serving raises :class:`ConnectionError`, which is what a dead
    tunnel looks like from the other side.

    **It unbinds the tool argument, because the real server does.** FastMCP
    binds the payload's single key to a named parameter and hands the handler
    only the body. A double that passed the whole payload through would accept
    calls a real peer rejects — and did: it was why the announcement could go
    out under the wrong argument name for four stages without a red test.
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
        return self.hosts[url].handle_inbound(tool, unbind(payload))


def peer(net: Internet, role: str, ours: str, theirs: str) -> Orchestrator:
    settings = ClientSettings.from_config({"opponent_url": theirs}, environ={})
    orchestrator = Orchestrator(
        PeerInboxes(game_uid="series-123", sub_game=1),
        OpponentClient(net, settings),
        role=role,
    )
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

        peering = thief.open_series(ours, tmp_path, "uoh26-s82kma9e")
        assert peering.sub_game == 1
        written = json.loads((tmp_path / "declaration_uoh26-s82kma9e.json").read_text())
        assert written[ADDRESS_KEY]["thief"]["public_url"] == THIEF_URL
        assert written[ADDRESS_KEY]["police"]["public_url"] == COP_URL
        assert all(entry["reachable"] for entry in written[ADDRESS_KEY].values())

    def test_a_turn_crosses_the_network_and_lands_in_the_mailbox(
        self, wired: tuple[Internet, Orchestrator, Orchestrator]
    ) -> None:
        net, thief, cop = wired
        assert cop.call_opponent("receive_turn", {"message": TURN})["ok"] is True
        assert net.delivered == [(THIEF_URL, "receive_turn")]
        assert thief.inboxes.turns.get_nowait().hint == "heading for the water"

    def test_a_full_round_completes_with_no_loopback_traffic(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        """The stage 5 milestone: handshake, then turns, over public addresses."""
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")

        for step in range(1, 6):
            assert (
                cop.call_opponent("receive_turn", {"message": {**TURN, "step": step}})["ok"] is True
            )
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
            thief.call_opponent("receive_turn", {"message": TURN})


class TestSurvivingATunnelRestartMidSeries:
    """The stage 5 milestone: a new URL between sub-games, no restart."""

    def test_the_series_continues_at_the_new_address(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        first = thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")
        assert thief.call_opponent("receive_turn", {"message": TURN})["ok"] is True

        # The cop's free-tier tunnel is recycled between sub-games.
        del net.hosts[COP_URL]
        net.listen(MOVED_COP_URL, cop)
        cop.announce(cop.greeting(MOVED_COP_URL, "them"))

        second = thief.rehandshake(first, thief.greeting(THIEF_URL, "s82kma9e"), 2, tmp_path, "g1")
        assert second.theirs.public_url == MOVED_COP_URL
        assert thief.call_opponent("receive_turn", {"message": {**TURN, "step": 2}})["ok"] is True
        assert net.delivered[-1] == (MOVED_COP_URL, "receive_turn")

    def test_without_the_re_handshake_the_old_address_is_dead(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        """What the re-handshake is worth: the whole series, not one sub-game.

        A technical loss scores zero for **both** sides, so a tunnel recycled
        partway through destroys sub-games already won on the board.
        """
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")

        del net.hosts[COP_URL]
        net.listen(MOVED_COP_URL, cop)
        with pytest.raises(MatchAborted):
            thief.call_opponent("receive_turn", {"message": TURN})

    def test_our_own_tunnel_moving_is_survivable_the_other_way_round(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        """The mirror case, and the reason the first announcement is still made.

        If *we* moved, they cannot reach us and announcing is the only way they
        ever learn where we went. Listening first would deadlock — they are
        waiting for a greeting they have no address to ask for.

        Both sides run the same ``rehandshake``; this drives them in the order
        a real pair would fall into, since only one of the two can speak first.
        """
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        first = thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")
        theirs = Peering(
            cop.greeting(COP_URL, "them"),
            Greeting("thief", "s82kma9e", THIEF_URL, PROTOCOL_VERSION),
            sub_game=1,
        )

        # Our tunnel is recycled. Their address still works, so we can still
        # reach them — they cannot reach us until they hear it from us.
        del net.hosts[THIEF_URL]
        net.listen(MOVED_THIEF_URL, thief)
        moved = thief.greeting(MOVED_THIEF_URL, "s82kma9e")
        assert thief.try_announce(moved) is True

        cop.rehandshake(theirs, cop.greeting(COP_URL, "them"), 2, tmp_path, "g2")
        assert cop.client.opponent_url == MOVED_THIEF_URL
        assert "announce-failed" in cop.heartbeats

        second = thief.rehandshake(first, moved, 2, tmp_path, "g1")
        assert second.ours.public_url == MOVED_THIEF_URL

    def test_both_tunnels_rotating_at_once_is_a_clean_timeout(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        """Genuinely unrecoverable — there is no in-band channel left.

        What matters is that it ends as a named ``TIMEOUT`` rather than a hang.
        Pretending to recover would only replace a clean technical loss with a
        match that never finishes.
        """
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        first = thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")

        net.hosts.clear()
        with pytest.raises(MatchAborted) as excinfo:
            thief.rehandshake(
                first, thief.greeting(MOVED_THIEF_URL, "s82kma9e"), 2, tmp_path, "g1", timeout=0.0
            )
        assert excinfo.value.cause is TechnicalLoss.TIMEOUT
        assert "announce-failed" in thief.heartbeats

    def test_the_declaration_says_which_sub_game_the_move_took_effect(
        self, wired: tuple[Internet, Orchestrator, Orchestrator], tmp_path: Path
    ) -> None:
        net, thief, cop = wired
        cop.announce(cop.greeting(COP_URL, "them"))
        first = thief.open_series(thief.greeting(THIEF_URL, "s82kma9e"), tmp_path, "g1")
        net.listen(MOVED_COP_URL, cop)
        cop.announce(cop.greeting(MOVED_COP_URL, "them"))
        thief.rehandshake(first, thief.greeting(THIEF_URL, "s82kma9e"), 2, tmp_path, "g1")

        written = json.loads((tmp_path / "declaration_g1.json").read_text())
        assert written[ADDRESS_KEY]["police"]["since_sub_game"] == 2
        assert written[ADDRESS_KEY]["thief"]["public_url"] == THIEF_URL


class TestConfiguringTheRemotePeer:
    def test_the_committed_config_is_overridden_for_league_play(self) -> None:
        """One exported variable turns a local run into a remote one."""
        local = ClientSettings.from_config({"opponent_url": "http://127.0.0.1:8802/mcp"}, {})
        remote = ClientSettings.from_config(
            {"opponent_url": "http://127.0.0.1:8802/mcp"}, {OPPONENT_URL_ENV: COP_URL}
        )
        assert local.opponent_url == "http://127.0.0.1:8802/mcp"
        assert remote.opponent_url == COP_URL
