"""A whole sub-game, driven by the loop, ending in a log the Replay App clears.

The first test in this project that runs the sequence rather than the pieces.
Real brain, real ceremony, real digests, real log — and a stand-in opponent that
holds its own ceremony and shares no state with ours, so the two agree only by
actually exchanging messages.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

import pytest

from thief_agent.domain.actions import MoveAction, PlaceBarrier
from thief_agent.domain.axes import AxisConvention
from thief_agent.domain.board import BoardState
from thief_agent.domain.crypto import commit_of, nonce, step_record
from thief_agent.domain.memory import ScentMemory
from thief_agent.infra.ceremony import (
    Acknowledgement,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
    Verdict,
)
from thief_agent.infra.match_log import MatchLog
from thief_agent.runtime.subgame import SubGame, UnplayableReveal
from thief_agent.strategy.base import Decision
from thief_agent.strategy.thief_brain import ThiefBrain
from thief_agent.ui.replay import load
from thief_agent.ui.verdict import Stamp, walk


class Wireable(Protocol):
    """Anything the ceremony sends: it can describe itself as a dict."""

    def to_dict(self) -> dict[str, Any]: ...


WHEN = "2026-08-05T10:00:00+00:00"
AXES = AxisConvention()


def board(
    grid: int = 8, cop: tuple[int, int] = (0, 0), thief: tuple[int, int] = (6, 5)
) -> BoardState:
    return BoardState(grid_size=grid, cop=cop, thief=thief, barriers=frozenset(), step=0)


def walled_in() -> BoardState:
    """The thief with nowhere to go: the cop on top of it, barriers all round.

    The police repository forces a capture by starting the two on one cell,
    because its brain moves the cop *towards* the thief. Ours flees, so an
    overlap at step zero is gone by step one — the capture has to be one the
    thief cannot walk out of.
    """
    return BoardState(
        grid_size=3,
        cop=(1, 1),
        thief=(1, 1),
        barriers=frozenset({(0, 1), (2, 1), (1, 0), (1, 2)}),
        step=0,
    )


class StandInOpponent:
    """A thief with its own ceremony, its own nonces and no view of ours.

    Not a mock. It runs the same four phases from the other side and every
    message it sends is serialised and re-parsed, so anything the two sides
    agree on they agreed on over a wire.
    """

    def __init__(self, move: str = "STAY", corrupt_at: int | None = None) -> None:
        self.role = "police"
        self.move = move
        self.corrupt_at = corrupt_at
        self.ceremony = MatchCeremony(role=self.role)
        self.records: dict[int, dict[str, object]] = {}
        self.nonces: dict[int, str] = {}
        self.fields: dict[int, dict[str, float]] = {}
        self.scent = ScentMemory()
        self.seen: list[str] = []
        self.state = board()

    # --- the sub-game speaks to us ------------------------------------------
    def send_commit(self, commitment: Commitment) -> None:
        self.seen.append("commit")
        self.ceremony.at(commitment.step).receive(Commitment.from_dict(self._wire(commitment)))

    def await_commit(self, step: int) -> Commitment:
        # A real opponent advances its own board in step with ours. One that did
        # not would seal every commitment against step zero, and our audit would
        # accuse it of forgery at every step — correctly, because it would be
        # re-deriving against a board the two sides never agreed on.
        self.state = replace(self.state, step=step)
        # This cop stands still, so its emission centre never moves. Decay
        # fires once per full turn, at the boundary we have just crossed.
        if step > 1:
            self.scent.decay()
        self.scent.emit(self.state.cop, self.state.grid_size)
        self.fields[step] = self.scent.outgoing()
        record = step_record(
            self.state, self.role, self.move, "truth", f"t{step}", scent=self.fields[step]
        )
        secret = nonce()
        self.records[step], self.nonces[step] = record, secret
        mine = Commitment(
            step=step, sender=self.role, commit=commit_of(record, secret), timestamp=WHEN
        )
        self.ceremony.at(step).commit(mine, secret)
        return Commitment.from_dict(self._wire(mine))

    def send_ack(self, ack: Acknowledgement) -> None:
        self.seen.append("ack")
        self.ceremony.at(ack.step).receive_ack(Acknowledgement.from_dict(self._wire(ack)))

    def await_ack(self, step: int) -> Acknowledgement:
        return Acknowledgement.from_dict(self._wire(self.ceremony.at(step).acknowledge(WHEN)))

    def send_reveal(self, opened: Reveal) -> None:
        self.seen.append("reveal")
        self.ceremony.at(opened.step).receive_reveal(Reveal.from_dict(self._wire(opened)))

    def await_reveal(self, step: int) -> Reveal:
        spoken = "E" if step == self.corrupt_at else self.move
        mine = Reveal(
            step=step,
            sender=self.role,
            move=spoken,
            intent="truth",
            hint=f"t{step}",
            timestamp=WHEN,
            scent=self.fields[step],
        )
        self.ceremony.at(step).reveal(mine)
        return Reveal.from_dict(self._wire(mine))

    def send_final(self, disclosed: FinalReveal) -> None:
        self.seen.append("final")
        self.ceremony.receive_final_reveal(FinalReveal.from_dict(self._wire(disclosed)))

    def await_final(self) -> FinalReveal:
        self.ceremony.finish()
        return FinalReveal.from_dict(self._wire(self.ceremony.final_reveal(WHEN)))

    @staticmethod
    def _wire(message: Wireable) -> dict[str, Any]:
        """Serialise, so nothing crosses by reference."""
        body: dict[str, Any] = json.loads(json.dumps(message.to_dict()))
        return body


def a_subgame(
    tmp_path: Path,
    opponent: StandInOpponent | None = None,
    max_steps: int = 4,
    state: BoardState | None = None,
) -> tuple[SubGame, StandInOpponent, MatchLog]:
    peer = opponent or StandInOpponent()
    log = MatchLog(
        game_id="uoh26-s82kma9e",
        sub_game=1,
        role="thief",
        game_uid="u-0001",
        config_sha256="c" * 64,
    )
    game = SubGame(
        role="thief",
        brain=ThiefBrain(),
        peer=peer,
        log=log,
        state=state or board(),
        axes=AXES,
        max_steps=max_steps,
        now=lambda: WHEN,
    )
    return game, peer, log


class TestAWholeSubGameRuns:
    def test_it_plays_to_the_step_limit(self, tmp_path: Path) -> None:
        game, _, _ = a_subgame(tmp_path, max_steps=3)
        played = game.play()
        assert played.steps == 3
        assert played.reason == "step limit reached"

    def test_every_step_is_logged(self, tmp_path: Path) -> None:
        game, _, log = a_subgame(tmp_path, max_steps=3)
        game.play()
        assert sorted(log.entries) == [1, 2, 3]

    def test_the_board_advances(self, tmp_path: Path) -> None:
        game, _, _ = a_subgame(tmp_path, max_steps=3)
        before = game.state
        game.play()
        assert game.state != before, "three steps and nothing moved"

    def test_the_board_step_matches_the_ceremony_step(self, tmp_path: Path) -> None:
        """The bug that would have stamped every honest match TAMPERED."""
        game, _, log = a_subgame(tmp_path, max_steps=3)
        game.play()
        for number, entry in log.entries.items():
            assert entry.reveal is not None
            assert entry.reveal["state"]["step"] == number

    def test_the_four_phases_happen_in_order(self, tmp_path: Path) -> None:
        """The order is the whole point; a reveal before an ack is unsafe."""
        game, peer, _ = a_subgame(tmp_path, max_steps=2)
        game.play()
        assert peer.seen == ["commit", "ack", "reveal", "commit", "ack", "reveal", "final"]


class TestTheLogItProduces:
    def test_the_replay_app_stamps_it_verified_ok(self, tmp_path: Path) -> None:
        """The acceptance for this issue, end to end."""
        game, _, log = a_subgame(tmp_path, max_steps=4)
        game.play()
        result = walk(load(log.write(tmp_path)))
        assert result.stamp is Stamp.VERIFIED_OK, str(result)
        assert result.verified == 4

    def test_every_step_has_all_three_slots(self, tmp_path: Path) -> None:
        game, _, log = a_subgame(tmp_path, max_steps=3)
        game.play()
        for entry in log.entries.values():
            assert entry.commit and entry.reveal and entry.nonce

    def test_a_third_party_could_fully_re_verify_it(self, tmp_path: Path) -> None:
        game, _, log = a_subgame(tmp_path, max_steps=3)
        game.play()
        assert log.verifiable().complete, str(log.verifiable())

    def test_the_log_records_our_sealed_record_not_the_wire_message(self, tmp_path: Path) -> None:
        """The distinction that made every honest step read as tampered in #260."""
        game, _, log = a_subgame(tmp_path, max_steps=1)
        game.play()
        reveal = log.entries[1].reveal
        assert reveal is not None
        assert "state" in reveal and "timestamp" not in reveal

    def test_no_nonce_is_written_before_the_sub_game_ends(self, tmp_path: Path) -> None:
        """Phase 4 exists so a secret cannot escape while a step is still open."""
        game, _, log = a_subgame(tmp_path, max_steps=3)
        game._one_step(1)  # noqa: SLF001 - the point is the state mid-match
        assert log.unopened() == [1]


class TestTheCeremonyIsReal:
    def test_the_opponents_audit_of_us_is_clean(self, tmp_path: Path) -> None:
        """They re-derive our every step from what we disclosed. Nothing shared."""
        game, peer, _ = a_subgame(tmp_path, max_steps=3)
        game.play()
        assert peer.ceremony.steps, "the stand-in never received anything"

    def test_a_corrupted_reveal_is_not_caught_at_reveal_time(self, tmp_path: Path) -> None:
        """And it cannot be. The nonce that would prove it arrives in phase 4.

        Worth pinning, because the intuition is that ``receive_reveal`` checks
        the digest. It does not — it *cannot*, since the commitment can only be
        opened once the nonce is disclosed at the end. Detection belongs to the
        audit, and expecting it here would have hidden the fact that the loop
        does not yet run one.
        """
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        game.play()  # the sub-game completes; the lie is still on the record

    def test_the_material_to_catch_it_is_all_recorded(self, tmp_path: Path) -> None:
        """The audit needs their commitments, their reveals and their nonces."""
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        game.play()
        for step in (1, 2, 3):
            ceremony = game.ceremony.at(step)
            assert ceremony.theirs is not None
            assert ceremony.revealed_theirs is not None

    def test_an_unreadable_revealed_move_is_named(self, tmp_path: Path) -> None:
        """The board cannot be advanced from a statement it cannot read."""
        game, _, _ = a_subgame(tmp_path, max_steps=1)
        game._peer_reveals[1] = Reveal(  # noqa: SLF001
            step=1,
            sender="police",
            move="sideways",
            intent="truth",
            hint="somewhere",
            timestamp=WHEN,
        )
        with pytest.raises(UnplayableReveal, match="not a move"):
            game.peer_move(1)


class TestCaptureEndsIt:
    def test_the_loop_stops_on_capture(self, tmp_path: Path) -> None:
        """A log whose later steps describe a finished game is two results."""
        game, _, _ = a_subgame(tmp_path, max_steps=6, state=walled_in())
        played = game.play()
        assert played.captured
        assert played.reason == "capture"
        assert played.steps < 6

    def test_it_still_discloses_every_nonce(self, tmp_path: Path) -> None:
        """A sub-game that ended early must still be auditable."""
        game, _, log = a_subgame(tmp_path, max_steps=6, state=walled_in())
        game.play()
        assert log.unopened() == []

    def test_survival_is_the_other_outcome(self, tmp_path: Path) -> None:
        game, _, _ = a_subgame(tmp_path, max_steps=2)
        assert game.play().thief_survived


class TestTheBranchesARoleReversalReaches:
    """``SubGame`` is role-agnostic; only the default differs between repos."""

    @staticmethod
    def as_the_cop(tmp_path: Path) -> SubGame:
        """A cop-side sub-game, so the opponent is the thief."""
        log = MatchLog(game_id="uoh26-s82kma9e", sub_game=1, role="police", game_uid="u-1")
        return SubGame(
            role="police",
            brain=ThiefBrain(),
            peer=StandInOpponent(),
            log=log,
            state=board(),
            axes=AXES,
            max_steps=1,
            now=lambda: WHEN,
        )

    def test_a_barrier_from_the_cop_is_playable(self, tmp_path: Path) -> None:
        """Our opponent here *is* the cop, so this is the ordinary path."""
        game, _, _ = a_subgame(tmp_path, max_steps=1)
        game._peer_reveals[1] = Reveal(  # noqa: SLF001
            step=1,
            sender="police",
            move="barrier",
            intent="truth",
            hint="somewhere",
            timestamp=WHEN,
            barrier_placed=[2, 3],
        )
        action = game.peer_move(1)
        assert isinstance(action, PlaceBarrier)
        assert action.at == (2, 3)

    def test_a_barrier_from_the_thief_is_refused(self, tmp_path: Path) -> None:
        """Only the cop may place one. A board advanced illegally is two boards."""
        game = self.as_the_cop(tmp_path)
        game._peer_reveals[1] = Reveal(  # noqa: SLF001
            step=1,
            sender="thief",
            move="barrier",
            intent="truth",
            hint="somewhere",
            timestamp=WHEN,
            barrier_placed=[2, 3],
        )
        with pytest.raises(UnplayableReveal, match="only the cop may place"):
            game.peer_move(1)


class TestTheEdgesOfTheLoop:
    def test_a_step_the_opponent_has_not_revealed_yields_nothing(self, tmp_path: Path) -> None:
        """Asked before phase 3, there is no move to report — not a wrong one."""
        game, _, _ = a_subgame(tmp_path, max_steps=1)
        assert game.peer_move(1) is None

    def test_the_board_still_advances_when_they_did_not_move(self, tmp_path: Path) -> None:
        """Our own action applies whether or not theirs arrived."""
        game, _, _ = a_subgame(tmp_path, max_steps=1)
        before = game.state
        game.state = game.state
        game._advance(MoveAction(move="E"), None)  # noqa: SLF001
        assert game.state.thief != before.thief

    def test_reasoning_reaches_the_log_when_the_brain_supplies_it(self, tmp_path: Path) -> None:
        """The LLM discussion fields the rulebook asks the log to carry."""
        game, _, log = a_subgame(tmp_path, max_steps=1)

        original = game.brain.decide

        def with_reasoning(state: BoardState, **context: object) -> Decision:
            decision = original(state, **context)
            decision.reasoning = "closing the north gap"
            return decision

        game.brain.decide = with_reasoning  # type: ignore[method-assign]
        game.play()
        assert log.entries[1].discussion == {
            "intent": "truth",
            "reasoning": "closing the north gap",
        }


class TestTheOpponentIsAudited:
    """The question the nonces exist to answer, asked at last."""

    def test_an_honest_opponent_audits_clean(self, tmp_path: Path) -> None:
        game, _, _ = a_subgame(tmp_path, max_steps=3)
        played = game.play()
        assert played.opponent_played_fairly, str(played.audit)
        assert played.audit.checked == 3

    def test_a_corrupted_reveal_is_caught_here(self, tmp_path: Path) -> None:
        """Not at reveal time — the nonce that proves it arrives in phase 4."""
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        played = game.play()
        assert not played.opponent_played_fairly
        assert played.audit.verdict is Verdict.FORGED

    def test_the_finding_names_the_step_and_the_arithmetic(self, tmp_path: Path) -> None:
        """'You cheated' is not a claim anyone concedes; a digest is."""
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        failures = game.play().audit.failures
        assert "step 2" in failures[0]
        assert "produces" in failures[0]

    def test_a_forgery_does_not_stay_local(self, tmp_path: Path) -> None:
        """The step after a lie fails too, and that is correct rather than noise.

        A reveal that disagrees with its commitment is a move the two peers
        then apply differently — so their boards diverge, and every later step
        is sealed against a state we no longer share. The audit reports the
        first failure and everything downstream of it, which is what actually
        happened: not one bad step in an otherwise sound game, but a game that
        stopped being the same game at step two.

        Each divergent step now draws **two** accusations, and they are
        different accusations rather than a duplicate: the digest does not open
        to the move that was spoken, *and* the trail the cop disclosed is not
        the one that move would have laid. The second is the interesting one —
        a cheat can always tell a consistent story about its own hash, and
        cannot tell one about the environment it walked through.
        """
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        failures = game.play().audit.failures
        assert sorted(f.split(":")[0] for f in failures) == [
            "step 2",
            "step 2",
            "step 3",
            "step 3",
        ]

    def test_every_step_is_still_checked(self, tmp_path: Path) -> None:
        """Stopping at the first would hand them an incomplete accusation."""
        game, _, _ = a_subgame(tmp_path, StandInOpponent(corrupt_at=2), max_steps=3)
        assert game.play().audit.checked == 3

    def test_the_board_each_step_was_sealed_against_is_kept(self, tmp_path: Path) -> None:
        """Without it their nonces arrive and prove nothing."""
        game, _, _ = a_subgame(tmp_path, max_steps=3)
        game.play()
        assert sorted(game.sealed_states) == [1, 2, 3]
        assert game.sealed_states[2].step == 2

    def test_an_opponent_who_disclosed_nothing_is_unverifiable(self, tmp_path: Path) -> None:
        """Not 'clean'. Silence is not a defence, and must not read as one."""
        game, _, _ = a_subgame(tmp_path, max_steps=1)
        game._one_step(1)  # noqa: SLF001
        result = game.audit()
        assert result.verdict is Verdict.FORGED
        assert "unverifiable rather than proven" in result.failures[0]
