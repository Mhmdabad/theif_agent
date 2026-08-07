"""The peer's own decisions, without a socket.

`test_localhost_match` proves the mapping works over the wire. This covers what
it does when the wire behaves badly — a silent opponent, an answer with no
digest, records arriving in the wrong order.
"""

from typing import Any

import pytest

from thief_agent.infra.ceremony import Commitment, FinalReveal, Reveal
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.infra.mcp_client import ClientSettings, OpponentClient
from thief_agent.infra.protocol import AuditPayload
from thief_agent.runtime.peer import UNDECIDED, McpPeer, PeerTimeout

WHEN = "2026-08-05T11:00:00+00:00"
DIGEST = "a" * 64
OTHER = "b" * 64


class Recording:
    """A transport that answers whatever it is told to, and remembers the calls."""

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.answer = answer if answer is not None else {"ok": True}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((tool, payload))
        return self.answer


def a_peer(
    answer: dict[str, Any] | None = None, timeout: float = 0.05
) -> tuple[McpPeer, Recording, PeerInboxes]:
    transport = Recording(answer)
    inboxes = PeerInboxes()
    peer = McpPeer(
        role="thief",
        client=OpponentClient(
            transport=transport,
            settings=ClientSettings(opponent_url="http://127.0.0.1:1/mcp"),
        ),
        inboxes=inboxes,
        now=WHEN,
        timeout=timeout,
        game_uid="series-123",
        sub_game=2,
    )
    return peer, transport, inboxes


def a_commitment(step: int = 1) -> Commitment:
    return Commitment(step=step, sender="thief", commit=DIGEST, timestamp=WHEN)


class TestTheAcknowledgementIsTheResponse:
    def test_a_digest_in_the_answer_is_taken_as_theirs(self) -> None:
        """Against another agent running this code, the ack proves what they hold."""
        peer, _, _ = a_peer({"ok": True, "acknowledges": OTHER})
        peer.send_commit(a_commitment())
        assert peer.await_ack(1).acknowledges == OTHER
        assert peer.reference_acks == []

    def test_a_bare_ok_falls_back_to_what_we_sent(self) -> None:
        """A reference opponent answers {"ok": true}. Recorded, not assumed away."""
        peer, _, _ = a_peer({"ok": True})
        peer.send_commit(a_commitment())
        assert peer.await_ack(1).acknowledges == DIGEST
        assert peer.reference_acks == [1]

    def test_the_acknowledgement_is_attributed_to_them(self) -> None:
        peer, _, _ = a_peer()
        peer.send_commit(a_commitment())
        assert peer.await_ack(1).sender == "police"

    def test_nothing_extra_crosses_the_wire_for_an_ack(self) -> None:
        """The phase costs no message, which is why it is interop-safe."""
        peer, transport, _ = a_peer()
        peer.send_commit(a_commitment())
        peer.send_ack(peer.await_ack(1))
        assert [tool for tool, _ in transport.calls] == ["receive_turn"]

    def test_an_ack_for_an_unsent_step_is_a_timeout(self) -> None:
        """Nothing has locked, so the reveal must not go out."""
        peer, _, _ = a_peer()
        with pytest.raises(PeerTimeout, match="never answered our commitment"):
            peer.await_ack(7)


class TestWhatCrossesTheWire:
    def test_a_commit_goes_as_a_turn_message(self) -> None:
        peer, transport, _ = a_peer()
        peer.send_commit(a_commitment())
        tool, payload = transport.calls[0]
        assert tool == "receive_turn"
        assert payload["message"]["commit"] == DIGEST

    def test_a_reveal_goes_as_an_audit_record(self) -> None:
        peer, transport, _ = a_peer()
        peer.send_reveal(
            Reveal(step=1, sender="thief", move="N", intent="truth", hint="h", timestamp=WHEN)
        )
        tool, payload = transport.calls[0]
        assert tool == "submit_audit"
        assert payload["payload"]["records"][0]["move"] == "N"

    def test_a_mid_game_reveal_claims_nothing_yet(self) -> None:
        """Empty would be refused outright, and both sides would wait forever."""
        peer, transport, _ = a_peer()
        peer.send_reveal(
            Reveal(step=1, sender="thief", move="N", intent="truth", hint="h", timestamp=WHEN)
        )
        assert transport.calls[0][1]["payload"]["result_claim"] == UNDECIDED

    def test_the_final_reveal_carries_our_claim(self) -> None:
        peer, transport, _ = a_peer()
        peer.result_claim = "captured"
        peer.send_final(FinalReveal(sender="thief", nonces={1: "0" * 32}, timestamp=WHEN))
        assert transport.calls[0][1]["payload"]["result_claim"] == "captured"

    def test_a_final_reveal_with_no_claim_still_says_something(self) -> None:
        peer, transport, _ = a_peer()
        peer.send_final(FinalReveal(sender="thief", nonces={1: "0" * 32}, timestamp=WHEN))
        assert transport.calls[0][1]["payload"]["result_claim"] == UNDECIDED


class TestRecordsArriveOutOfOrder:
    def test_stale_reveal_cannot_mask_current_reveal_in_same_payload(self) -> None:
        peer, _, inboxes = a_peer()
        stale = Reveal(
            step=1, sender="police", move="S", intent="truth", hint="old", timestamp=WHEN
        )
        current = Reveal(
            step=2, sender="police", move="N", intent="truth", hint="now", timestamp=WHEN
        )
        inboxes.audits.put(
            AuditPayload(
                sender="police",
                records=[stale.to_dict(), current.to_dict()],
                result_claim=UNDECIDED,
                game_uid="series-123",
                sub_game=2,
            )
        )

        assert peer.await_reveal(2) == current
        assert stale.to_dict() not in peer._held

    def test_a_record_we_are_not_waiting_for_is_kept(self) -> None:
        """A discarded message is a deadlock nobody can diagnose."""
        peer, _, inboxes = a_peer()
        early = FinalReveal(sender="police", nonces={1: "0" * 32}, timestamp=WHEN)
        wanted = Reveal(step=1, sender="police", move="S", intent="truth", hint="t", timestamp=WHEN)
        inboxes.audits.put(
            AuditPayload(
                sender="police",
                records=[early.to_dict(), wanted.to_dict()],
                result_claim=UNDECIDED,
                game_uid="series-123",
                sub_game=2,
            )
        )
        assert peer.await_reveal(1).move == "S"
        assert peer.await_final().nonces == {1: "0" * 32}, "the early one was thrown away"

    def test_a_held_record_is_found_without_another_wait(self) -> None:
        peer, _, inboxes = a_peer()
        first = Reveal(step=1, sender="police", move="S", intent="truth", hint="t", timestamp=WHEN)
        second = Reveal(step=2, sender="police", move="N", intent="truth", hint="t", timestamp=WHEN)
        inboxes.audits.put(
            AuditPayload(
                sender="police",
                records=[second.to_dict(), first.to_dict()],
                result_claim=UNDECIDED,
                game_uid="series-123",
                sub_game=2,
            )
        )
        assert peer.await_reveal(1).move == "S"
        assert peer.await_reveal(2).move == "N", "step 2 arrived first and was dropped"


class TestASilentOpponent:
    def test_a_missing_commitment_is_a_timeout(self) -> None:
        peer, _, _ = a_peer()
        with pytest.raises(PeerTimeout, match="commitment for step 1"):
            peer.await_commit(1)

    def test_a_missing_reveal_is_a_timeout(self) -> None:
        peer, _, _ = a_peer()
        with pytest.raises(PeerTimeout, match="audit record"):
            peer.await_reveal(1)

    def test_a_missing_final_reveal_is_a_timeout(self) -> None:
        peer, _, _ = a_peer()
        with pytest.raises(PeerTimeout, match="audit record"):
            peer.await_final()

    def test_the_message_says_what_a_silence_costs(self) -> None:
        """A peer that stops answering is a technical loss: zero for both sides."""
        peer, _, _ = a_peer()
        with pytest.raises(PeerTimeout, match="zero for both sides"):
            peer.await_commit(1)


class TestReceivingACommitment:
    def test_a_turn_becomes_a_commitment(self) -> None:
        from thief_agent.infra.protocol import TurnMessage

        peer, _, inboxes = a_peer()
        inboxes.turns.put(
            TurnMessage(
                step=1,
                sender="police",
                hint="",
                smell_grid={},
                commit=OTHER,
                timestamp=WHEN,
            )
        )
        received = peer.await_commit(1)
        assert received.commit == OTHER
        assert received.sender == "police"

    def test_the_opponent_of_the_thief_is_the_police(self) -> None:
        peer, _, _ = a_peer()
        peer.role = "police"
        assert peer.opponent == "thief"

    def test_it_waits_again_when_a_payload_holds_nothing_wanted(self) -> None:
        """Two arrivals, and what we want is in the second."""
        peer, _, inboxes = a_peer(timeout=2.0)
        other = Reveal(step=9, sender="police", move="E", intent="truth", hint="t", timestamp=WHEN)
        wanted = Reveal(step=1, sender="police", move="S", intent="truth", hint="t", timestamp=WHEN)
        spare = Reveal(step=8, sender="police", move="W", intent="truth", hint="t", timestamp=WHEN)
        inboxes.audits.put(
            AuditPayload(
                sender="police",
                records=[other.to_dict(), spare.to_dict()],
                result_claim=UNDECIDED,
                game_uid="series-123",
                sub_game=2,
            )
        )
        inboxes.audits.put(
            AuditPayload(
                sender="police",
                records=[wanted.to_dict()],
                result_claim=UNDECIDED,
                game_uid="series-123",
                sub_game=2,
            )
        )
        assert peer.await_reveal(1).move == "S"
        assert peer.await_reveal(8).move == "W", "held records are searched, not just the first"
        assert peer.await_reveal(9).move == "E", "the first payload was not kept"
