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


def test_reveal_retry_is_idempotent_but_cannot_mask_a_conflicting_hint() -> None:
    inboxes = PeerInboxes(game_uid="series-123", sub_game=2)
    committed = {
        "step": 1,
        "sender": "police",
        "hint": "",
        "smell_grid": {},
        "commit": "a" * 64,
        "timestamp": "now",
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
