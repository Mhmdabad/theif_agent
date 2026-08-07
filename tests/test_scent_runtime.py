"""The pheromone layer, driven by the loop that plays a real match.

Every part of this existed before and none of it was ever called by a game.
``ScentMemory`` emitted, ``Trail`` decayed, ``Belief`` normalised and
``inference`` combined — and no sub-game touched any of them, so the rulebook's
central mechanism was a library the agent shipped and never used.

What is checked here is the wiring, and the wiring is where the rules live:

* emission happens on **every** action, ``STAY`` included, because the field is
  laid down by occupying a cell rather than by leaving one;
* decay fires **once per full turn**, after both agents have acted — twice
  would halve the trail's memory and put us out of step with a peer who read
  the rule correctly, and the model is hash-locked, so being out of step is a
  dispute rather than a weaker strategy;
* the belief map is updated from the **opponent's** field only, never from a
  pool of both, because an agent that read its own trail would confidently
  track itself;
* a field that cannot be verified is not absorbed at all.

The opponent here holds its own scent memory and its own ceremony, and every
message between the two is serialised and re-parsed, so nothing agrees by
sharing an object.
"""

import json
from dataclasses import replace
from typing import Any, Protocol

import pytest

from thief_agent.domain.actions import MoveAction
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, nonce, step_record
from thief_agent.domain.memory import ScentMemory
from thief_agent.domain.scent import CENTRE_INTENSITY
from thief_agent.domain.trail import RETENTION
from thief_agent.infra.ceremony import (
    Acknowledgement,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
)
from thief_agent.infra.match_log import MatchLog
from thief_agent.runtime.subgame import SubGame
from thief_agent.strategy.base import Decision, StrategyContextError
from thief_agent.strategy.thief_brain import ThiefBrain

WHEN = "2026-08-05T10:00:00+00:00"
AXES = AxisConvention()
GRID = 8

# --- role block -------------------------------------------------------------
# The only part of this file that differs between the two agents. Both copies
# assert the same behaviour of the same shared modules; only which side of the
# board we sit on changes.
OUR_ROLE = "thief"
THEIR_ROLE = "police"
OUR_START = (6, 5)
THEIR_START = (0, 0)
AWAY = "N"
"""A move legal from :data:`OUR_START` four times over, in a straight line."""

TWO_AWAY = (4, 5)
"""Where two :data:`AWAY` moves put us."""

FORGED_FIELD = {"0,1": 0.9, "0,0": 0.62}
"""Well formed, correctly rounded, on the board — and not what was emitted."""
# --- end role block ---------------------------------------------------------


class Wireable(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


def board() -> BoardState:
    return BoardState(
        grid_size=GRID,
        cop=OUR_START if OUR_ROLE == "police" else THEIR_START,
        thief=THEIR_START if OUR_ROLE == "police" else OUR_START,
        barriers=frozenset(),
        step=0,
    )


class ScriptedBrain:
    """Plays a fixed sequence, so what the trail should look like is arithmetic."""

    def __init__(self, moves: list[str]) -> None:
        self.moves = moves
        self.played = 0

    def decide(self, state: BoardState, **context: object) -> Decision:
        move = self.moves[min(self.played, len(self.moves) - 1)]
        self.played += 1
        return Decision(action=MoveAction(move=move), hint="somewhere", intent="truth")  # type: ignore[arg-type]


class RecordingBrain(ScriptedBrain):
    """A configured context brain that records the real runtime contract."""

    def __init__(self, moves: list[str]) -> None:
        super().__init__(moves)
        self.calls: list[tuple[BoardState, dict[str, object]]] = []

    def decide(self, state: BoardState, **context: object) -> Decision:
        self.calls.append((state, context))
        return super().decide(state, **context)


class ScentedOpponent:
    """An opponent that stands still, emits honestly, and can be told to cheat.

    Standing still keeps its trail a matter of arithmetic rather than of
    replaying its policy, which is the point: the assertions here are about
    what *this* agent does with the field, and a moving opponent would make
    every expected number depend on a second strategy.
    """

    def __init__(self, forge_at: int | None = None, omit: bool = False, junk: bool = False) -> None:
        self.role = THEIR_ROLE
        self.forge_at = forge_at
        self.omit = omit
        self.junk = junk
        self.ceremony = MatchCeremony(role=self.role)
        self.scent = ScentMemory()
        self.fields: dict[int, dict[str, float]] = {}
        self.nonces: dict[int, str] = {}
        self.state = board()
        self.commits: list[Commitment] = []

    @property
    def cell(self) -> tuple[int, int]:
        return THEIR_START

    def send_commit(self, commitment: Commitment) -> None:
        self.commits.append(Commitment.from_dict(self._wire(commitment)))
        self.ceremony.at(commitment.step).receive(self.commits[-1])

    def await_commit(self, step: int) -> Commitment:
        if step > 1:
            self.scent.decay()  # once per full turn, at the boundary we just crossed
        self.scent.emit(self.cell, GRID)
        self.fields[step] = self.scent.outgoing()
        self.state = replace(self.state, step=step)
        record = step_record(
            self.state, self.role, "STAY", "truth", f"t{step}", scent=self.sealed(step)
        )
        secret = nonce()
        self.nonces[step] = secret
        mine = Commitment(
            step=step, sender=self.role, commit=commit_of(record, secret), timestamp=WHEN
        )
        self.ceremony.at(step).commit(mine, secret)
        return Commitment.from_dict(self._wire(mine))

    def sealed(self, step: int) -> dict[str, float] | None:
        """What this step's commitment covers.

        The forgeries below seal the honest field and speak a different one, so
        the *hash* still opens and only the reconstruction can catch them —
        which is the case the reconstruction exists for. ``omit`` is not a
        forgery at all: it models a peer with no scent binding, so it seals
        nothing and speaks nothing, and its commitments verify perfectly.
        """
        return None if self.omit else self.fields[step]

    def spoken(self, step: int) -> dict[str, float] | None:
        """What this step's reveal claims, which may not be what it emitted."""
        if self.omit:
            return None
        if self.junk:
            return {"99,99": 4.2}
        if step == self.forge_at:
            return FORGED_FIELD
        return self.fields[step]

    def send_ack(self, ack: Acknowledgement) -> None:
        self.ceremony.at(ack.step).receive_ack(Acknowledgement.from_dict(self._wire(ack)))

    def await_ack(self, step: int) -> Acknowledgement:
        return Acknowledgement.from_dict(self._wire(self.ceremony.at(step).acknowledge(WHEN)))

    def send_reveal(self, opened: Reveal) -> None:
        self.ceremony.at(opened.step).receive_reveal(Reveal.from_dict(self._wire(opened)))

    def await_reveal(self, step: int) -> Reveal:
        mine = Reveal(
            step=step,
            sender=self.role,
            move="STAY",
            intent="truth",
            hint=f"t{step}",
            timestamp=WHEN,
            scent=self.spoken(step),
        )
        self.ceremony.at(step).reveal(mine)
        return Reveal.from_dict(self._wire(mine))

    def send_final(self, disclosed: FinalReveal) -> None:
        self.ceremony.receive_final_reveal(FinalReveal.from_dict(self._wire(disclosed)))

    def await_final(self) -> FinalReveal:
        self.ceremony.finish()
        return FinalReveal.from_dict(self._wire(self.ceremony.final_reveal(WHEN)))

    @staticmethod
    def _wire(message: Wireable) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(json.dumps(message.to_dict()))
        return body


def a_subgame(
    opponent: ScentedOpponent | None = None,
    moves: list[str] | None = None,
    max_steps: int = 3,
) -> tuple[SubGame, ScentedOpponent]:
    peer = opponent or ScentedOpponent()
    game = SubGame(
        role=OUR_ROLE,
        brain=ScriptedBrain(moves or [AWAY] * 4),  # type: ignore[arg-type]
        peer=peer,
        log=MatchLog(
            game_id="uoh26-s82kma9e",
            sub_game=1,
            role=OUR_ROLE,
            game_uid="u-0001",
            config_sha256="c" * 64,
        ),
        state=board(),
        axes=AXES,
        max_steps=max_steps,
        now=lambda: WHEN,
    )
    return game, peer


class TestTheAgentActuallyEmits:
    def test_a_played_sub_game_lays_a_trail(self) -> None:
        game, _ = a_subgame()
        game.play()
        assert game.scent.outgoing()

    def test_standing_still_emits_too(self) -> None:
        """The field is laid by occupying a cell, not by leaving one.

        Read off the field we actually transmitted, at the moment we
        transmitted it: a peer that skipped its ``STAY`` turns would send a
        trail whose centre had faded while it was standing on it.
        """
        game, _ = a_subgame(moves=["STAY", "STAY", "STAY"])
        game.play()
        for step in (1, 2, 3):
            opened = game.ceremony.at(step).revealed_ours
            assert opened is not None and opened.scent is not None
            assert opened.scent[f"{OUR_START[0]},{OUR_START[1]}"] == CENTRE_INTENSITY

    def test_a_barrier_turn_would_emit_from_where_the_cop_stands(self) -> None:
        """Forfeiting movement is an action; there is no silent turn."""
        game, _ = a_subgame(moves=["STAY"], max_steps=1)
        game.play()
        assert game.scent.own.strongest() == OUR_START

    def test_the_emission_follows_the_move_that_was_committed(self) -> None:
        """The centre is where we ended the turn, not where we began it."""
        game, _ = a_subgame(moves=[AWAY, AWAY], max_steps=2)
        game.play()
        opened = game.ceremony.at(2).revealed_ours
        assert opened is not None and opened.scent is not None
        assert opened.scent[f"{TWO_AWAY[0]},{TWO_AWAY[1]}"] == CENTRE_INTENSITY


class TestDecayHappensOncePerFullTurn:
    def test_an_abandoned_cell_keeps_ninety_percent_a_turn(self) -> None:
        """Three steps of marching south, measured at the cell left behind.

        Decaying twice a turn would leave 0.478 here rather than 0.656, so this
        distinguishes the two readings several times over. The first turn is a
        ``STAY`` so the measured cell really was the emission centre; the two
        that follow move away and re-deposit less than the cell already holds,
        which is exactly the max-merge the trail is specified with.
        """
        game, _ = a_subgame(moves=["STAY", AWAY, AWAY], max_steps=3)
        game.play()
        assert game.scent.own.intensity_at(OUR_START) == pytest.approx(
            CENTRE_INTENSITY * RETENTION**3, abs=1e-9
        )

    def test_exactly_one_decay_follows_a_single_turn(self) -> None:
        game, _ = a_subgame(moves=["STAY"], max_steps=1)
        game.play()
        assert game.scent.own.intensity_at(OUR_START) == pytest.approx(
            CENTRE_INTENSITY * RETENTION, abs=1e-9
        )


class TestOnlyTheOpponentsFieldIsAbsorbed:
    def test_their_trail_arrives(self) -> None:
        game, _ = a_subgame()
        game.play()
        assert game.scent.opponent.strongest() == THEIR_START

    def test_our_own_field_is_never_mixed_in(self) -> None:
        """An agent pooling both fields would confidently track itself.

        The two emissions never overlap here — a 5x5 field around ``(0,0)`` and
        one around ``(6,5)`` are disjoint on an 8x8 board — so our own centre
        appearing in the opponent's trail could only mean pooling.
        """
        game, _ = a_subgame(moves=["STAY", "STAY", "STAY"])
        game.play()
        assert game.scent.own.intensity_at(OUR_START) > 0.5
        assert game.scent.opponent.intensity_at(OUR_START) == 0.0

    def test_a_field_we_cannot_verify_is_not_absorbed(self) -> None:
        """Fail-closed: no scent beats scent we cannot check."""
        game, _ = a_subgame(ScentedOpponent(junk=True), moves=["STAY"])
        game.play()
        assert game.scent.opponent.values == {}

    def test_an_omitted_field_absorbs_nothing(self) -> None:
        game, _ = a_subgame(ScentedOpponent(omit=True))
        game.play()
        assert game.scent.opponent.values == {}


class TestTheBeliefMapMoves:
    def test_it_starts_uniform_over_the_free_cells(self) -> None:
        game, _ = a_subgame()
        assert game.belief.total() == pytest.approx(1.0)
        assert game.belief.concentration() == 0.0

    def test_evidence_concentrates_it(self) -> None:
        game, _ = a_subgame()
        before = game.belief.heatmap()
        game.play()
        assert game.belief.heatmap() != before
        assert game.belief.concentration() > 0.0

    def test_it_points_at_the_trail_rather_than_at_us(self) -> None:
        game, _ = a_subgame()
        game.play()
        peak = game.belief.most_likely()
        assert peak is not None
        assert abs(peak[0] - THEIR_START[0]) <= 2 and abs(peak[1] - THEIR_START[1]) <= 2

    def test_it_stays_a_distribution(self) -> None:
        game, _ = a_subgame()
        game.play()
        assert game.belief.total() == pytest.approx(1.0)
        assert all(value >= 0.0 for value in game.belief.mass.values())

    def test_an_unverifiable_field_leaves_the_belief_alone(self) -> None:
        """A malformed field must not become evidence by being loud."""
        game, _ = a_subgame(ScentedOpponent(junk=True), moves=["STAY"])
        before = game.belief.heatmap()
        game.play()
        assert game.belief.heatmap() == before

    def test_the_live_view_is_never_handed_the_true_cell(self) -> None:
        """FR-7.11: local truth only. Enforced by a signature, not by discipline."""
        import inspect

        from thief_agent.ui.view import render

        assert "thief" not in inspect.signature(render).parameters
        assert "opponent" not in inspect.signature(render).parameters


class TestBeliefDrivesTheNextDecision:
    def test_completed_scent_becomes_the_very_next_deterministic_context(self) -> None:
        game, _ = a_subgame(max_steps=2)
        game.state = replace(game.state, cop=(7, 7))
        brain = RecordingBrain(["STAY", "STAY"])
        game.brain = brain  # type: ignore[assignment]
        game.play()

        first_state, first = brain.calls[0]
        second_state, second = brain.calls[1]
        assert first == {
            "threat": (0, 0),
            "concentration": 0.0,
            "uncertainty": 1.0,
        }
        assert game.received_hints[1] == "t1"
        assert game.belief.at(OUR_START) == 0.0
        assert first["threat"] != (7, 7)
        assert second["threat"] == THEIR_START
        assert second["concentration"] > 0.0  # type: ignore[operator]
        assert second["uncertainty"] == pytest.approx(1.0 - second["concentration"])  # type: ignore[operator]
        assert first_state.cop == first["threat"]
        assert second_state.cop == second["threat"]

    def test_old_explicit_strategy_signature_remains_supported(self) -> None:
        class ExplicitBrain(RecordingBrain):
            def decide(  # type: ignore[override]
                self,
                state: BoardState,
                *,
                threat: tuple[int, int],
                concentration: float,
                uncertainty: float,
            ) -> Decision:
                return super().decide(
                    state,
                    threat=threat,
                    concentration=concentration,
                    uncertainty=uncertainty,
                )

        game, _ = a_subgame(max_steps=2)
        game.brain = ExplicitBrain(["STAY", "STAY"])  # type: ignore[assignment]
        game.play()

    def test_malformed_scent_and_our_own_scent_cannot_poison_context(self) -> None:
        game, _ = a_subgame(ScentedOpponent(junk=True), moves=["STAY", "STAY"], max_steps=2)
        brain = RecordingBrain(["STAY", "STAY"])
        game.brain = brain  # type: ignore[assignment]
        game.play()
        assert [call[1]["threat"] for call in brain.calls] == [(0, 0), (0, 0)]
        assert all(call[1]["concentration"] == 0.0 for call in brain.calls)

    def test_physically_forged_step_one_cannot_redirect_step_two(self) -> None:
        game, _ = a_subgame(ScentedOpponent(forge_at=1), max_steps=2)
        game.state = replace(game.state, cop=(7, 7))
        brain = RecordingBrain(["STAY", "STAY"])
        game.brain = brain  # type: ignore[assignment]

        played = game.play()

        assert brain.calls[1][1]["threat"] == (0, 0)
        assert not played.audit.clean
        assert any("step 1" in failure for failure in played.audit.failures)

    def test_barriers_and_zero_mass_are_never_selected(self) -> None:
        game, _ = a_subgame(max_steps=1)
        brain = RecordingBrain(["STAY"])
        game.brain = brain  # type: ignore[assignment]
        game.state = replace(game.state, barriers=frozenset({(0, 1)}))
        game.belief.mass = {(0, 1): 9.0, (1, 1): 0.0, (1, 0): 1.0}
        game.play()
        assert brain.calls[0][1]["threat"] == (1, 0)

    def test_context_is_not_added_to_gui_or_log(self) -> None:
        game, _ = a_subgame(max_steps=1)
        brain = RecordingBrain(["STAY"])
        game.brain = brain  # type: ignore[assignment]
        game.play()
        reveal = game.log.entries[1].reveal
        assert reveal is not None
        assert not ({"threat", "concentration", "uncertainty"} & reveal.keys())

    def test_incompatible_configured_brain_gets_a_migration_error(self) -> None:
        class LegacyBrain:
            def decide(self, state: BoardState) -> Decision:
                return Decision(MoveAction("STAY"))

        game, _ = a_subgame(max_steps=1)
        game.brain = LegacyBrain()  # type: ignore[assignment]
        with pytest.raises(StrategyContextError, match=r"accept \*\*context.*threat"):
            game.play()

    def test_shipped_thief_evades_belief_not_the_true_coordinate(self) -> None:
        game, _ = a_subgame(max_steps=1)
        game.state = replace(game.state, cop=(0, 0), thief=(3, 3))
        game.brain = ThiefBrain(axes=AXES, min_open_neighbours=0)
        game.belief.mass = {(6, 3): 1.0}
        game.play()
        opened = game.ceremony.at(1).revealed_ours
        assert opened is not None and opened.move == "N"

    def test_shipped_thief_decision_changes_when_only_belief_changes(self) -> None:
        moves: list[str] = []
        for peak in ((0, 3), (6, 3)):
            game, _ = a_subgame(max_steps=1)
            game.state = replace(game.state, cop=(3, 6), thief=(3, 3))
            game.brain = ThiefBrain(axes=AXES, min_open_neighbours=0)
            game.belief.mass = {peak: 1.0}
            game.play()
            opened = game.ceremony.at(1).revealed_ours
            assert opened is not None
            moves.append(opened.move)
        assert moves == ["S", "N"]


class TestTheFieldTravelsInPhaseThreeOnly:
    def test_the_commitment_we_send_carries_no_field(self) -> None:
        game, opponent = a_subgame(max_steps=2)
        game.play()
        for commitment in opponent.commits:
            assert "scent" not in commitment.to_dict()
            assert "smell_grid" not in commitment.to_dict()

    def test_our_reveal_carries_the_field_we_sealed(self) -> None:
        game, _ = a_subgame(max_steps=2)
        game.play()
        for step in (1, 2):
            opened = game.ceremony.at(step).revealed_ours
            assert opened is not None
            assert opened.scent

    def test_the_log_records_the_field_the_commitment_covers(self) -> None:
        """A third party must be able to re-verify from the file alone."""
        game, _ = a_subgame(max_steps=2)
        game.play()
        entry = game.log.entries[1]
        assert entry.reveal is not None
        assert entry.reveal["scent"]


class TestTheAuditJudgesTheField:
    def test_an_honest_opponent_audits_clean(self) -> None:
        game, _ = a_subgame()
        played = game.play()
        assert played.audit.clean, str(played.audit)

    def test_a_forged_field_fails_the_audit(self) -> None:
        """Sealed honestly, spoken falsely — only reconstruction catches it."""
        game, _ = a_subgame(ScentedOpponent(forge_at=2))
        played = game.play()
        assert not played.audit.clean
        assert any("step 2" in failure for failure in played.audit.failures)

    def test_a_malformed_field_fails_the_audit_without_crashing(self) -> None:
        game, _ = a_subgame(ScentedOpponent(junk=True))
        played = game.play()
        assert not played.audit.clean

    def test_a_peer_that_cannot_bind_scent_is_refused(self) -> None:
        """Requirement 6: no silent acceptance of unverified scent."""
        game, _ = a_subgame(ScentedOpponent(omit=True))
        played = game.play()
        assert not played.audit.clean
        assert any("no scent" in failure for failure in played.audit.failures)

    def test_the_downgrade_exists_and_is_explicit(self) -> None:
        """A series may be negotiated without scent — never by default."""
        game, _ = a_subgame(ScentedOpponent(omit=True))
        game.require_bound_scent = False
        played = game.play()
        assert played.audit.clean, str(played.audit)

    def test_the_crypto_verdict_is_still_reported_alongside(self) -> None:
        """Two different accusations; the opponent is entitled to both."""
        game, _ = a_subgame(ScentedOpponent(forge_at=1))
        played = game.play()
        assert played.audit.checked == 3
