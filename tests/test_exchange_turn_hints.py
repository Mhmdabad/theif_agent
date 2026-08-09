"""P0-2: verbal hints cross the existing four-phase ceremony."""

from dataclasses import dataclass
from typing import Any

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.board import Agent, BoardState, Move
from thief_agent.infra.ceremony import CeremonyError, Reveal
from thief_agent.infra.inboxes import RETRY_KEY, PeerInboxes
from thief_agent.infra.mcp_client import (
    ClientSettings,
    OpponentClient,
    OpponentUnreachableError,
    PeerNotReadyError,
)
from thief_agent.infra.validation import require_hint
from thief_agent.strategy.base import BrainBase


@dataclass
class StayingBrain(BrainBase):
    @property
    def role(self) -> Agent:
        return "thief"

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        return "STAY"


def test_default_brain_emits_one_safe_hint_even_when_staying() -> None:
    """A hint the wire will accept, on the turn that emits no movement.

    Asserted as a property rather than as one literal sentence. The hint used
    to be a constant, so the constant *was* the implementation; now it is
    composed per turn, and what has to hold is what the door checks on arrival
    — present, inside the word cap, and naming no coordinates (rule 27).
    """
    state = BoardState(cop=(0, 0), thief=(3, 3), grid_size=7)
    decision = StayingBrain().decide(state)
    assert decision.action == MoveAction("STAY")
    assert decision.intent == "truth"
    require_hint({"hint": decision.hint}, max_words=15)


def reveal(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "step": 1,
        "sender": "police",
        "move": "STAY",
        "intent": "lie",
        "hint": "I slipped south past the bridge",
        "barrier_placed": None,
        "scent": {},
        "timestamp": "2026-08-07T00:00:00Z",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    body.update(changes)
    return body


@pytest.mark.parametrize(
    "changes, detail",
    [
        ({"hint": None}, "must be a string"),
        ({"hint": ""}, "must not be empty"),
        ({"hint": "   \t"}, "must not be blank"),
        (
            {
                "hint": "one two three four five six seven eight "
                "nine ten eleven twelve thirteen fourteen fifteen sixteen"
            },
            "over 15 words",
        ),
        ({"hint": "safe\nlooking"}, "control character"),
        ({"hint": "bad\ud800text"}, "Unicode scalar"),
        ({"hint": "safe\u202elooking"}, "format character"),
        ({"hint": "I am at 3,4"}, "numeric coordinates"),
        ({"hint": "Next turn I will move north"}, "future action"),
        ({"hint": "I intend to move north next turn"}, "future action"),
        ({"hint": "I’ll move north"}, "future action"),
        ({"hint": "I'll move north"}, "future action"),
        ({"hint": "I will move north"}, "future action"),
        ({"hint": "coordinates 3 and 4"}, "numeric coordinates"),
        ({"hint": "x=3 y=4"}, "numeric coordinates"),
        ({"hint": "ROW : 3; COLUMN = 4"}, "numeric coordinates"),
    ],
)
def test_wire_refuses_malformed_or_oversized_hints(changes: dict[str, object], detail: str) -> None:
    with pytest.raises(CeremonyError, match=detail):
        Reveal.from_dict(reveal(**changes))


def test_wire_preserves_unicode_hint_exactly_and_does_not_confuse_it_with_scent() -> None:
    text = "אני ליד הגשר — maybe"
    opened = Reveal.from_dict(reveal(hint=text, scent={"3,3": 0.9}))
    assert opened.hint == text
    assert opened.intent == "lie"
    assert opened.scent == {"3,3": 0.9}


def test_wire_accepts_exactly_the_word_limit() -> None:
    text = " ".join(["שלום"] * 15)
    assert Reveal.from_dict(reveal(hint=text)).hint == text


@pytest.mark.parametrize(
    "hint",
    [
        "I moved north last turn",
        "I am nowhere near the bridge",
        "There are 3 bridges north of here",
        "My xylophone has 3 strings",
        "Rowboats and columns line the old hall",
    ],
)
def test_benign_deceptive_and_non_coordinate_hints_are_not_overblocked(hint: str) -> None:
    assert Reveal.from_dict(reveal(hint=hint)).hint == hint


def test_unbound_legacy_reveal_fails_closed() -> None:
    legacy = reveal()
    legacy.pop("game_uid")
    legacy.pop("sub_game")
    with pytest.raises(CeremonyError, match="game_uid"):
        Reveal.from_dict(legacy)


def test_rewrapped_old_reveal_is_rejected_by_its_immutable_inner_binding() -> None:
    inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
    assert (
        inboxes.receive_turn(
            {
                "step": 1,
                "sender": "police",
                "hint": "",
                "smell_grid": {},
                "commit": "a" * 64,
                "timestamp": "now",
                "game_uid": "series-123",
                "sub_game": 2,
            }
        )["ok"]
        is True
    )
    payload = {
        "sender": "police",
        "records": [reveal(sub_game=1)],
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    assert inboxes.submit_audit(payload)["ok"] is False
    assert inboxes.audits.empty()

    payload["records"] = [reveal(game_uid="other-series")]
    assert inboxes.submit_audit(payload)["ok"] is False
    assert inboxes.audits.empty()


def test_inner_binding_mutated_to_current_has_no_effect_without_current_phase_one() -> None:
    inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
    payload = {
        "sender": "police",
        "records": [reveal()],
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    answer = inboxes.submit_audit(payload)
    assert answer["ok"] is False
    assert "without a current phase-one commitment" in answer["detail"]
    assert inboxes.audits.empty()


def test_reveal_retry_is_idempotent_but_cannot_mask_a_conflicting_hint() -> None:
    inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
    committed = {
        "step": 1,
        "sender": "police",
        "hint": "",
        "smell_grid": {},
        "commit": "a" * 64,
        "timestamp": "now",
        "game_uid": "series-123",
        "sub_game": 2,
        "barrier_placed": None,
        "capture_claim": None,
        "claim_response": None,
        "win_claim": None,
    }
    assert inboxes.receive_turn(committed) == {"ok": True}
    payload = {
        "sender": "police",
        "records": [reveal()],
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    assert inboxes.submit_audit(payload) == {"ok": True}
    assert inboxes.submit_audit(payload) == {"ok": True}
    conflicting = {
        "sender": "police",
        "records": [reveal(hint="a different story")],
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    answer = inboxes.submit_audit(conflicting)
    assert answer["ok"] is False
    assert "revealed step 1 differently" in answer["detail"]
    assert inboxes.audits.qsize() == 1


def test_reveal_from_prior_sub_game_is_rejected_before_current_one_is_queued() -> None:
    inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
    inboxes.receive_turn(
        {
            "step": 1,
            "sender": "police",
            "hint": "",
            "smell_grid": {},
            "commit": "a" * 64,
            "timestamp": "now",
            "game_uid": "series-123",
            "sub_game": 2,
        }
    )
    old = {
        "sender": "police",
        "records": [reveal()],
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 1,
    }
    current = {**old, "sub_game": 2}

    assert inboxes.submit_audit(old)["ok"] is False
    assert inboxes.audits.empty()
    assert inboxes.submit_audit(current) == {"ok": True}
    assert inboxes.audits.get_nowait().sub_game == 2


OPPONENT = str(reveal()["sender"])
"""Whoever the other side is here. Taken from the fixture so both repos read alike."""


def turn(**changes: object) -> dict[str, object]:
    """The phase-one message that makes a reveal openable."""
    body: dict[str, object] = {
        "step": 1,
        "sender": OPPONENT,
        "hint": "",
        "smell_grid": {},
        "commit": "a" * 64,
        "timestamp": "now",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    body.update(changes)
    return body


def audit(records: list[dict[str, object]], **changes: object) -> dict[str, object]:
    """The envelope a reveal travels in."""
    body: dict[str, object] = {
        "sender": OPPONENT,
        "records": records,
        "result_claim": "in_progress",
        "game_uid": "series-123",
        "sub_game": 2,
    }
    body.update(changes)
    return body


@dataclass
class Door:
    """A transport that delivers straight into a real mailbox, with no socket.

    The two halves of this fix only work together — the door has to refuse in a
    way the client understands, and the client has to re-send what the door
    refused — so they are proved against each other rather than against a stub
    of the other one.
    """

    inboxes: PeerInboxes

    def call(self, url: str, tool: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self.inboxes.receive_turn(payload["message"])


DEFERRED = {"ok": False, RETRY_KEY: True}
"""What a door that is not open *yet* answers, minus the human-readable detail."""


def deferred(answer: dict[str, object]) -> bool:
    """Whether the door asked the sender to come back rather than refusing it."""
    return {key: answer[key] for key in DEFERRED} == DEFERRED


class TestNothingReachesAQueueBeforeTheDoorIsBound:
    """The open door this binding left, written as the packets that walked through.

    An unbound mailbox used to call nothing stale, which reads as prudence and
    is really the opposite: with no binding to compare against, *every*
    canonically shaped packet was acknowledged and queued, and the ledger that
    decides what counts as a replay was written from it. A forged commitment
    pushed before the runner bound its inboxes therefore became the head of the
    queue the ceremony drains, and the legitimate opening commitment that
    followed was stranded behind it.

    The door now fails closed, and the sender is told which kind of *no* it got.
    A binding we cannot yet judge — unbound, or a sub-game this series has not
    opened — is answered with a **retryable** refusal and nothing is recorded;
    one we can judge and have refused is final.
    """

    def test_a_forged_packet_before_binding_is_refused_and_leaves_no_trace(self) -> None:
        """The production repro: ``old-or-forged/1`` pushed before the runner binds."""
        inboxes = PeerInboxes()
        answer = inboxes.receive_turn(turn(game_uid="old-or-forged", sub_game=1))
        assert deferred(answer)
        assert inboxes.turns.empty()
        assert inboxes.accepted_turns == {}
        assert inboxes.duplicates == [] and inboxes.rejected == []
        assert len(inboxes.deferred) == 1

    def test_the_same_forgery_after_binding_is_refused_for_good(self) -> None:
        """Once we know which series we are in, a foreign one is not a retry away."""
        inboxes = PeerInboxes()
        inboxes.bind("series-123", 1)
        answer = inboxes.receive_turn(turn(game_uid="old-or-forged", sub_game=1))
        assert answer["ok"] is False and answer.get(RETRY_KEY) is not True
        assert "old-or-forged" in str(answer["detail"])
        assert inboxes.turns.empty() and inboxes.accepted_turns == {}
        assert len(inboxes.rejected) == 1

    def test_a_forgery_before_the_bind_cannot_poison_the_head_of_the_queue(self) -> None:
        """Forged first, legitimate second: the ceremony must still drain the second."""
        inboxes = PeerInboxes()
        assert deferred(inboxes.receive_turn(turn(game_uid="old-or-forged", sub_game=1)))
        inboxes.bind("series-123", 1)
        assert inboxes.receive_turn(turn(sub_game=1)) == {"ok": True}
        assert inboxes.turns.qsize() == 1
        queued = inboxes.turns.get_nowait()
        assert (queued.game_uid, queued.sub_game) == ("series-123", 1)
        assert list(inboxes.accepted_turns) == [(OPPONENT, 1, "series-123", 1)]

    def test_an_honest_packet_that_beat_the_bind_is_deferred_then_accepted(self) -> None:
        """The race this replaces the open door with: refused, re-sent, played."""
        inboxes = PeerInboxes()
        assert deferred(inboxes.receive_turn(turn(sub_game=1)))
        assert inboxes.turns.empty() and inboxes.accepted_turns == {}
        inboxes.bind("series-123", 1)
        assert inboxes.receive_turn(turn(sub_game=1)) == {"ok": True}
        assert inboxes.turns.get_nowait().sub_game == 1
        assert inboxes.rejected == [] and inboxes.duplicates == []

    def test_the_audit_door_is_shut_before_binding_too(self) -> None:
        """A reveal queued while unbound writes the reveal ledger just as freely."""
        inboxes = PeerInboxes()
        assert deferred(inboxes.submit_audit(audit([reveal(sub_game=1)], sub_game=1)))
        assert inboxes.audits.empty()
        assert inboxes.accepted_reveals == {}
        assert inboxes.rejected == []

    def test_a_sub_game_this_series_has_not_opened_is_deferred_not_queued(self) -> None:
        """Was: queued early and drained later, which is the same open door one boundary on."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        assert deferred(inboxes.receive_turn(turn(sub_game=4)))
        assert inboxes.turns.empty() and inboxes.accepted_turns == {}
        assert inboxes.rejected == []

    def test_and_the_re_send_lands_once_we_have_crossed_too(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        assert deferred(inboxes.receive_turn(turn(sub_game=4)))
        inboxes.bind("series-123", 4)
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.submit_audit(audit([reveal(sub_game=4)], sub_game=4)) == {"ok": True}
        assert inboxes.rejected == []

    def test_binding_takes_the_series_before_it_takes_the_sub_game(self) -> None:
        """The two stores are read on the server thread, so their order is the contract.

        A message landing between them must see a door that defers it, never
        one that refuses it: taking the sub-game first would leave the door
        pointing at a series we are not in, which is a final refusal.
        """
        inboxes = PeerInboxes()
        seen: list[tuple[str, int]] = []
        original = PeerInboxes.receive_turn

        def watching(self: PeerInboxes, message: object) -> dict[str, object]:
            seen.append((self.game_uid, self.sub_game))
            return original(self, message)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(PeerInboxes, "receive_turn", watching)
            inboxes.bind("series-123", 1)
            assert deferred(inboxes.receive_turn(turn(game_uid="series-123", sub_game=2)))
        assert seen == [("series-123", 1)]

    def test_a_greeting_does_not_forget_a_turn_it_arrived_after(self) -> None:
        """Was: ``police revealed step 1 without a current phase-one commitment``.

        The boundary greeting used to empty the ledger, which is the same defect
        wearing the opponent's clothes: their announcement lands on our thread's
        schedule, so it could wipe a turn we had already accepted and acted on.
        """
        inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
        assert inboxes.receive_turn(turn()) == {"ok": True}
        inboxes.negotiate({"greeting": {"role": OPPONENT, "public_url": "https://moved"}})
        assert inboxes.submit_audit(audit([reveal()])) == {"ok": True}
        assert inboxes.rejected == []

    def test_step_one_recurs_every_sub_game_without_looking_like_a_replay(self) -> None:
        """Why the ledger was emptied at all, and why it no longer has to be."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=1)
        for number in range(1, 7):
            inboxes.bind("series-123", number)
            assert inboxes.receive_turn(turn(sub_game=number)) == {"ok": True}
        assert inboxes.rejected == [] and inboxes.duplicates == []
        assert len(inboxes.accepted_turns) == 6


class TestTheSenderSpendsABudgetRatherThanGivingUpOrWaitingForever:
    """The other half of a retryable refusal: somebody has to try again.

    ``receive_turn`` is fire-and-forget, so a door that refuses an honest packet
    silently costs the series. The client already owns a bounded budget for a
    socket that will not answer — Appendix F's attempts and backoff — and a door
    that is not open yet is answered inside that same budget, so the wait is
    bounded by a number both teams agreed rather than by patience.
    """

    def a_client(self, inboxes: PeerInboxes) -> OpponentClient:
        """A client whose backoff opens the door, standing in for the other thread."""

        def crossing(_: float) -> None:
            inboxes.bind("series-123", 1)

        return OpponentClient(
            transport=Door(inboxes),
            settings=ClientSettings(opponent_url="http://127.0.0.1:1/mcp", retry_backoff_sec=0.0),
            sleep=crossing,
        )

    def test_an_honest_packet_sent_just_before_the_bind_lands_on_the_retry(self) -> None:
        inboxes = PeerInboxes()
        client = self.a_client(inboxes)
        assert client.call("receive_turn", {"message": turn(sub_game=1)}) == {"ok": True}
        assert client.attempts == 2
        assert inboxes.turns.get_nowait().sub_game == 1
        assert inboxes.rejected == []

    def test_a_door_that_never_opens_costs_the_budget_and_then_the_match(self) -> None:
        """Deterministic technical loss, not a hang: the attempts are counted out."""
        inboxes = PeerInboxes()
        client = OpponentClient(
            transport=Door(inboxes),
            settings=ClientSettings(
                opponent_url="http://127.0.0.1:1/mcp", max_retries=2, retry_backoff_sec=0.0
            ),
        )
        with pytest.raises(PeerNotReadyError, match="receive_turn"):
            client.call("receive_turn", {"message": turn(sub_game=1)})
        assert client.attempts == 3
        assert inboxes.turns.empty() and inboxes.accepted_turns == {}

    def test_that_exhaustion_is_the_same_technical_loss_an_unreachable_peer_is(self) -> None:
        assert issubclass(PeerNotReadyError, OpponentUnreachableError)

    def test_a_final_refusal_is_not_retried(self) -> None:
        """Spending the budget on a *no* would turn one forgery into four."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=1)
        client = self.a_client(inboxes)
        answer = client.call("receive_turn", {"message": turn(game_uid="other", sub_game=1)})
        assert answer["ok"] is False and client.attempts == 1

    def test_a_re_send_is_the_same_bytes_rather_than_a_second_action(self) -> None:
        inboxes = PeerInboxes()
        client = self.a_client(inboxes)
        client.call("receive_turn", {"message": turn(sub_game=1)})
        assert len({digest for _, digest in client.sent}) == 1


class TestWhatIsBehindUsIsStillRefused:
    """A door that defers what it cannot judge still refuses what it can."""

    def test_a_turn_from_a_sub_game_already_played_is_refused(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=4)
        answer = inboxes.receive_turn(turn(sub_game=3))
        assert answer["ok"] is False and "already past" in answer["detail"]
        assert inboxes.turns.empty()

    def test_a_turn_from_another_series_is_refused_however_far_along_it_is(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
        answer = inboxes.receive_turn(turn(game_uid="series-999", sub_game=6))
        assert answer["ok"] is False and "series 'series-999'" in answer["detail"]
        assert inboxes.turns.empty()

    def test_a_reveal_rewrapped_in_a_fresher_envelope_is_refused(self) -> None:
        """The replay the inner binding exists to catch, and the one it still catches."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
        inboxes.receive_turn(turn())
        answer = inboxes.submit_audit(audit([reveal(sub_game=1)]))
        assert answer["ok"] is False and "travelled in an audit for" in answer["detail"]
        assert inboxes.audits.empty()

    def test_a_retry_of_an_accepted_turn_is_a_duplicate_not_a_second_turn(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=4)
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.turns.qsize() == 1
        assert len(inboxes.duplicates) == 1 and inboxes.rejected == []

    def test_a_deferred_turn_leaves_nothing_for_its_re_send_to_collide_with(self) -> None:
        """A retry after a deferral is the first acceptance, not a duplicate."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        for _ in range(3):
            assert deferred(inboxes.receive_turn(turn(sub_game=4)))
        inboxes.bind("series-123", 4)
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.duplicates == [] and inboxes.turns.qsize() == 1

    def test_a_turn_changed_after_the_fact_is_still_a_forgery(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=4)
        inboxes.receive_turn(turn(sub_game=4))
        answer = inboxes.receive_turn(turn(sub_game=4, commit="b" * 64))
        assert answer["ok"] is False and "never replace one" in answer["detail"]
