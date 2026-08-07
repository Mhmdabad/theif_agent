"""P0-2: verbal hints cross the existing four-phase ceremony."""

from dataclasses import dataclass

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.board import Agent, BoardState, Move
from thief_agent.infra.ceremony import CeremonyError, Reveal
from thief_agent.infra.inboxes import PeerInboxes
from thief_agent.strategy.base import BrainBase, Decision


@dataclass
class StayingBrain(BrainBase):
    @property
    def role(self) -> Agent:
        return "thief"

    def _pick_move(self, state: BoardState, **context: object) -> Move:
        return "STAY"


def test_default_brain_emits_one_safe_hint_even_when_staying() -> None:
    state = BoardState(cop=(0, 0), thief=(3, 3), grid_size=7)
    decision = StayingBrain().decide(state)
    assert decision == Decision(MoveAction("STAY"), "I am watching the streets", "truth")


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


class TestABoundaryTheOpponentCrossesFirstDoesNotStrandTheSeries:
    """The deadlock this binding introduced, written as the packets it refused.

    Two peers advance their own ``sub_game`` on their own thread and nothing
    orders the two: the re-handshake makes each side *announce* at a boundary,
    not adopt it, so under load the peer that crosses first sends the next
    sub-game's opening messages while our door still names the last one. Both
    refusals below were observed on a real six-sub-game series, and both are
    silent to the sender — ``receive_turn`` is fire-and-forget, so a refused
    turn is never re-sent and the series simply stops.

    Every assertion is on :attr:`~PeerInboxes.rejected` rather than on a wait.
    The 25s timeout is how this surfaced, not what went wrong, and a regression
    that reproduced the timeout would take 25s to say so.
    """

    def test_the_next_sub_games_opening_turn_is_queued_rather_than_refused(self) -> None:
        """Was: ``turn is bound to 'u-0001' sub-game 4, expected ... sub-game 3``."""
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.rejected == []
        inboxes.sub_game = 4
        assert inboxes.turns.get_nowait().sub_game == 4

    def test_and_its_reveal_still_opens_once_we_have_crossed_too(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        inboxes.receive_turn(turn(sub_game=4))
        inboxes.sub_game = 4
        assert inboxes.submit_audit(audit([reveal(sub_game=4)], sub_game=4)) == {"ok": True}
        assert inboxes.rejected == []

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
            inboxes.sub_game = number
            assert inboxes.receive_turn(turn(sub_game=number)) == {"ok": True}
        assert inboxes.rejected == [] and inboxes.duplicates == []
        assert len(inboxes.accepted_turns) == 6


class TestWhatIsBehindUsIsStillRefused:
    """Admitting an early message is not admitting a stale one."""

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

    def test_a_retry_of_an_early_turn_is_a_duplicate_not_a_second_turn(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.receive_turn(turn(sub_game=4)) == {"ok": True}
        assert inboxes.turns.qsize() == 1
        assert len(inboxes.duplicates) == 1 and inboxes.rejected == []

    def test_an_early_turn_changed_after_the_fact_is_still_a_forgery(self) -> None:
        inboxes = PeerInboxes(game_uid="series-123", sub_game=3)
        inboxes.receive_turn(turn(sub_game=4))
        answer = inboxes.receive_turn(turn(sub_game=4, commit="b" * 64))
        assert answer["ok"] is False and "never replace one" in answer["detail"]
