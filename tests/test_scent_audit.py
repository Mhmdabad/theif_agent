"""The scent field as evidence: validated, reconstructed, and bound to a hash.

Chapter 4 makes one claim the whole belief layer rests on — *the scent map
cannot lie*. That claim is not true of a field that arrives as JSON from an
adversary. It is true only if three things hold, and each is tested here:

* a received field is **validated** before anything reads it, so a malformed,
  non-finite, negative, over-limit or off-board value is a refusal rather than
  a number that quietly widens the board we reason about;
* the field is **bound to the phase-1 commitment**, so it cannot be chosen
  after seeing the opponent's move;
* the field is **re-derived** at the final audit from the agreed start and the
  revealed movement history, so a field that is well-formed, correctly hashed
  and still impossible is caught.

Without the third, an opponent may commit to any field it likes and the
cryptography merely proves it did so early. The reconstruction is what turns
"you committed to this" into "this is what the physics produced".
"""

import math
from typing import Any

import pytest

from thief_agent.domain.actions import MoveAction, PlaceBarrier
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, step_record
from thief_agent.domain.memory import ScentMemory
from thief_agent.domain.scent import CENTRE_INTENSITY, emission
from thief_agent.domain.scent_audit import (
    ScentFieldError,
    StepPlay,
    audit_scent,
    check_field,
    replay,
    trail_snapshots,
)
from thief_agent.domain.trail import RETENTION, Trail

AXES = AxisConvention()
BOARD = 8

# --- role block -------------------------------------------------------------
# The only part of this file that differs between the two agents. Everything
# below is written against these names, so the cop's copy and the thief's copy
# stay one test rather than two that drift apart the first time either is
# edited.
OUR_ROLE = "thief"
OUR_START = (6, 5)
THEIR_START = (0, 0)
THEIR_MOVES = ["S", "E", "STAY"]
"""Three moves the opponent may legally play from :data:`THEIR_START`."""

OUR_STEP = ["STAY", "N"]
"""Our own two moves for the replay below."""

EXPECTED_REPLAY = [((6, 5), (1, 0)), ((5, 5), (1, 1))]
"""Where each side stands after those two turns.

Written out rather than computed: an expectation derived from the module under
test is a restatement of it.
"""

BARRIER_PLAY = StepPlay(1, MoveAction("N"), PlaceBarrier(at=(0, 1)), None)
BARRIER_EXPECT = [((5, 5), (0, 0))]
"""A turn spent building. Only the cop may, so which side holds it flips."""

CORNERED = (7, 0)
"""A cell from which ``THEIR_MOVES[0]`` would walk off the board."""
# --- end role block ---------------------------------------------------------

START = BoardState(
    grid_size=BOARD,
    cop=OUR_START if OUR_ROLE == "police" else THEIR_START,
    thief=THEIR_START if OUR_ROLE == "police" else OUR_START,
    barriers=frozenset(),
    step=0,
)


def board_with(theirs: tuple[int, int]) -> BoardState:
    """The start board with the opponent moved to ``theirs``."""
    return BoardState(
        grid_size=BOARD,
        cop=OUR_START if OUR_ROLE == "police" else theirs,
        thief=theirs if OUR_ROLE == "police" else OUR_START,
    )


def snapshot_at(cell: tuple[int, int]) -> dict[str, float]:
    """The wire field a fresh emission on ``cell`` produces."""
    trail = Trail()
    trail.deposit(emission(cell, BOARD))
    return trail.snapshot()


def honest(moves: list[str]) -> list[StepPlay]:
    """A play sequence where the disclosed field is the one physics produces.

    Built by replaying rather than by hand: a hand-written expectation is a
    second implementation of the model, and the two would drift.
    """
    plays = [
        StepPlay(step=n, ours=MoveAction("STAY"), theirs=MoveAction(m), disclosed=None)  # type: ignore[arg-type]
        for n, m in enumerate(moves, start=1)
    ]
    cells = [theirs for _, theirs in replay(START, AXES, OUR_ROLE, plays)]
    fields = trail_snapshots(cells, BOARD)
    return [
        StepPlay(step=play.step, ours=play.ours, theirs=play.theirs, disclosed=field)
        for play, field in zip(plays, fields, strict=True)
    ]


class TestAFieldIsValidatedBeforeAnythingReadsIt:
    """Everything here arrives from an agent that benefits from us believing it."""

    def test_an_honest_emission_is_accepted(self) -> None:
        parsed = check_field(snapshot_at((4, 4)), BOARD)
        assert parsed[(4, 4)] == CENTRE_INTENSITY

    def test_a_non_object_is_refused(self) -> None:
        with pytest.raises(ScentFieldError):
            check_field([], BOARD)  # type: ignore[arg-type]

    def test_a_non_string_key_is_refused(self) -> None:
        with pytest.raises(ScentFieldError):
            check_field({4: 0.9}, BOARD)  # type: ignore[dict-item]

    @pytest.mark.parametrize("key", ["3", "a,b", "1,2,3", " 1,2", "-1,2", "1, 2", "", "1,"])
    def test_a_malformed_cell_key_is_refused(self, key: str) -> None:
        with pytest.raises(ScentFieldError, match="cell"):
            check_field({key: 0.5}, BOARD)

    def test_a_cell_off_the_board_is_refused(self) -> None:
        """A cell off the board would quietly widen the board we reason about."""
        with pytest.raises(ScentFieldError, match="off"):
            check_field({f"{BOARD},0": 0.5}, BOARD)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_intensity_is_refused(self, value: float) -> None:
        with pytest.raises(ScentFieldError, match="finite"):
            check_field({"1,1": value}, BOARD)

    def test_a_negative_intensity_is_refused(self) -> None:
        """The rulebook clamps at zero: there is no evidence of *absence*."""
        with pytest.raises(ScentFieldError, match="negative"):
            check_field({"1,1": -0.5}, BOARD)

    def test_an_intensity_above_the_centre_is_refused(self) -> None:
        """No cell can be more fragrant than a fresh emission at its centre."""
        with pytest.raises(ScentFieldError, match="0.9"):
            check_field({"1,1": 1.5}, BOARD)

    def test_a_boolean_is_not_an_intensity(self) -> None:
        """``isinstance(True, int)`` is true in Python, so this needs saying."""
        with pytest.raises(ScentFieldError, match="number"):
            check_field({"1,1": True}, BOARD)

    def test_a_string_is_not_an_intensity(self) -> None:
        with pytest.raises(ScentFieldError, match="number"):
            check_field({"1,1": "0.9"}, BOARD)  # type: ignore[dict-item]

    def test_more_cells_than_the_board_has_is_refused(self) -> None:
        """A field larger than the board is either a bug or an exhaustion attempt."""
        oversized = {f"{r},{c}": 0.1 for r in range(BOARD) for c in range(BOARD)}
        oversized["0,0"] = 0.1
        check_field(oversized, BOARD)  # exactly board_size**2 is legitimate
        with pytest.raises(ScentFieldError, match="cells"):
            check_field(oversized, 3)

    def test_more_precision_than_the_wire_carries_is_refused(self) -> None:
        """Three decimals is what makes two implementations agree on a float."""
        with pytest.raises(ScentFieldError, match="precision"):
            check_field({"1,1": 0.123456}, BOARD)


class TestTheTrailIsRederivedFromTheMovementHistory:
    def test_a_stationary_agent_re_emits_at_full_strength(self) -> None:
        """Emission happens on every action, standing still included."""
        fields = trail_snapshots([(4, 4), (4, 4), (4, 4)], BOARD)
        assert [field["4,4"] for field in fields] == [CENTRE_INTENSITY] * 3

    def test_decay_happens_exactly_once_per_full_turn(self) -> None:
        """An abandoned cell keeps 90 % per turn — not 81 %, not 100 %."""
        fields = trail_snapshots([(4, 4), (0, 0), (0, 0)], BOARD)
        assert fields[1]["4,4"] == pytest.approx(CENTRE_INTENSITY * RETENTION, abs=5e-4)
        assert fields[2]["4,4"] == pytest.approx(CENTRE_INTENSITY * RETENTION**2, abs=5e-4)

    def test_it_agrees_with_what_a_live_peer_actually_emits(self) -> None:
        """The reconstruction and the engine must be one model, not two.

        Driven through :class:`ScentMemory` — the object a real match uses — so
        a divergence between what we transmit and what an auditor re-derives is
        a failing test rather than a forgery verdict against an honest peer.
        """
        memory = ScentMemory()
        live = []
        for cell in [(6, 5), (6, 4), (5, 4)]:
            memory.emit(cell, BOARD)
            live.append(memory.outgoing())
            memory.decay()
        assert live == trail_snapshots([(6, 5), (6, 4), (5, 4)], BOARD)

    def test_positions_come_from_the_revealed_moves(self) -> None:
        plays = [
            StepPlay(n, MoveAction(ours), MoveAction(theirs), None)  # type: ignore[arg-type]
            for n, (ours, theirs) in enumerate(zip(OUR_STEP, THEIR_MOVES, strict=False), start=1)
        ]
        assert replay(START, AXES, OUR_ROLE, plays) == EXPECTED_REPLAY

    def test_a_barrier_turn_leaves_the_placer_where_it_stands(self) -> None:
        """Forfeiting movement is still an action, and it still emits."""
        assert replay(START, AXES, OUR_ROLE, [BARRIER_PLAY]) == BARRIER_EXPECT


class TestForgedScentFailsTheAudit:
    """Verbal hints may lie. The trail may not."""

    def test_honest_play_audits_clean(self) -> None:
        assert audit_scent(START, AXES, OUR_ROLE, honest(THEIR_MOVES)) == ()

    def test_a_field_the_physics_never_produced_is_caught(self) -> None:
        """Well-formed, correctly hashed, and impossible."""
        plays = honest(THEIR_MOVES[:2])
        plays[1] = StepPlay(2, plays[1].ours, plays[1].theirs, snapshot_at(OUR_START))
        problems = audit_scent(START, AXES, OUR_ROLE, plays)
        assert len(problems) == 1
        assert problems[0].startswith("step 2:")

    def test_an_inflated_peak_is_caught(self) -> None:
        """The cheapest forgery: keep the shape, brighten the lie."""
        plays = honest(THEIR_MOVES[:1])
        forged = dict(plays[0].disclosed or {})
        forged["5,5"] = 0.9
        forged["4,5"] = 0.62
        plays[0] = StepPlay(1, plays[0].ours, plays[0].theirs, forged)
        assert audit_scent(START, AXES, OUR_ROLE, plays)

    def test_a_malformed_field_is_an_audit_failure_not_an_exception(self) -> None:
        """A crash mid-audit would be a technical loss scoring zero for both."""
        plays = honest(THEIR_MOVES[:1])
        plays[0] = StepPlay(1, plays[0].ours, plays[0].theirs, {"99,99": float("nan")})
        problems = audit_scent(START, AXES, OUR_ROLE, plays)
        assert len(problems) == 1
        assert "step 1" in problems[0]

    def test_an_absent_field_is_refused_rather_than_excused(self) -> None:
        """Fail-closed: unverifiable scent is not weaker evidence, it is none."""
        plays = honest(THEIR_MOVES[:1])
        plays[0] = StepPlay(1, plays[0].ours, plays[0].theirs, None)
        problems = audit_scent(START, AXES, OUR_ROLE, plays)
        assert len(problems) == 1
        assert "no scent" in problems[0]

    def test_an_absent_field_is_tolerated_only_by_explicit_agreement(self) -> None:
        """The downgrade exists, is named, and is never the default."""
        plays = honest(THEIR_MOVES[:1])
        plays[0] = StepPlay(1, plays[0].ours, plays[0].theirs, None)
        assert audit_scent(START, AXES, OUR_ROLE, plays, require_bound=False) == ()

    def test_a_move_the_board_forbids_is_an_audit_failure(self) -> None:
        """A reconstruction that cannot proceed is a claim that cannot be true."""
        plays = [StepPlay(1, MoveAction("STAY"), MoveAction(THEIR_MOVES[0]), None)]  # type: ignore[arg-type]
        problems = audit_scent(board_with(CORNERED), AXES, OUR_ROLE, plays)
        assert len(problems) == 1
        assert "step 1" in problems[0]

    def test_every_step_is_reported_not_only_the_first(self) -> None:
        """The opponent is entitled to the whole list; one settled step reopens."""
        plays = honest(THEIR_MOVES[:2])
        plays = [StepPlay(p.step, p.ours, p.theirs, snapshot_at(OUR_START)) for p in plays]
        assert len(audit_scent(START, AXES, OUR_ROLE, plays)) == 2


class TestTheFieldIsBoundToThePhaseOneCommitment:
    """Requirement 3: a field changed after the commit must fail verification."""

    def record(self, field: dict[str, float] | None) -> dict[str, Any]:
        return step_record(START, OUR_ROLE, OUR_STEP[1], "truth", "uptown", scent=field)

    def test_the_sealed_record_carries_the_field(self) -> None:
        field = snapshot_at(OUR_START)
        assert self.record(field)["scent"] == field

    def test_a_turn_without_scent_seals_null_rather_than_omitting_the_key(self) -> None:
        """Both sides serialise one shape, so an absence is a fact about the turn."""
        assert self.record(None)["scent"] is None

    def test_changing_one_cell_after_the_commit_breaks_it(self) -> None:
        honest_field = snapshot_at(OUR_START)
        tampered = {**honest_field, f"{OUR_START[0]},{OUR_START[1]}": 0.899}
        assert commit_of(self.record(honest_field), "0" * 32) != commit_of(
            self.record(tampered), "0" * 32
        )

    def test_the_binding_survives_a_json_round_trip(self) -> None:
        """Floats that survive the wire must survive re-hashing, or every
        honest match audits as tampered."""
        import json

        field = snapshot_at((3, 3))
        assert commit_of(self.record(field), "0" * 32) == commit_of(
            self.record(json.loads(json.dumps(field))), "0" * 32
        )


class TestTheModelIsTheOneTheBookLocks:
    def test_no_cell_can_exceed_the_appendix_f_centre(self) -> None:
        assert max(check_field(snapshot_at((4, 4)), BOARD).values()) == CENTRE_INTENSITY

    def test_every_reconstructed_value_is_finite_and_in_range(self) -> None:
        for field in trail_snapshots([(4, 4), (4, 5), (4, 6)], BOARD):
            for value in field.values():
                assert math.isfinite(value)
                assert 0.0 < value <= CENTRE_INTENSITY
