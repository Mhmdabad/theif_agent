"""One sub-game, start to finish: brain → ceremony → peer → log.

Every module this calls has been tested for months. **Nothing has ever called
them in sequence.** Every acceptance test to date drove them directly, which
means the seams between them were the only part of the system with no coverage
at all — and nine of the defects found in this project have been exactly there.

The order below is the rulebook's four phases, in the order Chapter 6 puts them
and the order ``test_stage6_acceptance`` already proves the ceremony expects:

1. **Commit** — both sides seal a move before either says anything about it.
2. **Acknowledge** — each confirms it holds the other's commitment. This phase
   is the one the reference implementation omits, and it is the reason the
   reveal is safe: a reveal that went out before the opponent had committed
   would let them choose their move knowing ours.
3. **Reveal** — only now, and only for a step both sides have locked.
4. **Final Reveal** — every nonce, once, at the end of the sub-game.

**The peer is a Protocol, not a client.** This module decides *what* must be
said and in what order; how it crosses the wire is :mod:`.mcp_transport`'s
problem and the entry point's. Keeping them apart is what lets a whole sub-game
run in a test against a stand-in opponent, with real digests, a real ceremony
and a real log — which is the only way to check the sequence itself.

**The log is written as the match runs, never afterwards.** A commitment is
recorded before it goes out and a reveal when it is spoken, because the *order*
in the file is the evidence: a log assembled at the end is exactly what a cheat
produces, and an auditor cannot tell the two apart.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from inspect import signature
from typing import Protocol, cast

from ..domain.actions import Action, MoveAction, PlaceBarrier, apply_action
from ..domain.axes import AxisConvention
from ..domain.belief import Belief
from ..domain.board import Agent, BoardState, Move
from ..domain.crypto import commit_of, nonce, step_record
from ..domain.inference import update as absorb_evidence
from ..domain.memory import ScentMemory
from ..domain.outcome import is_capture_by_overlap, is_enclosure_capture, is_trapping_capture
from ..domain.rules import advance_turn, position_of
from ..domain.scent_audit import ScentFieldError, StepPlay, audit_scent, check_field
from ..infra.ceremony import (
    Acknowledgement,
    AuditResult,
    Commitment,
    FinalReveal,
    MatchCeremony,
    Reveal,
    Verdict,
    audit_opponent,
)
from ..infra.match_log import MatchLog
from ..strategy.base import BrainBase, StrategyContextError

OPPONENT_OF = {"police": "thief", "thief": "police"}

MOVES: frozenset[str] = frozenset({"N", "S", "E", "W", "STAY"})
"""What a revealed move may be. A barrier turn reveals ``"barrier"`` instead."""


class UnplayableReveal(ValueError):
    """Raised when the opponent revealed something the board cannot be advanced by."""


class Peer(Protocol):
    """The opponent, reduced to the eight things a sub-game needs to say and hear.

    Each ``await_`` blocks until the message for that step arrives or the
    caller's deadline passes; a peer that never answers is the transport's
    problem to convert into a technical loss, not this module's to guess at.
    """

    def send_commit(self, commitment: Commitment) -> None: ...
    def await_commit(self, step: int) -> Commitment: ...
    def send_ack(self, ack: Acknowledgement) -> None: ...
    def await_ack(self, step: int) -> Acknowledgement: ...
    def send_reveal(self, opened: Reveal) -> None: ...
    def await_reveal(self, step: int) -> Reveal: ...
    def send_final(self, disclosed: FinalReveal) -> None: ...
    def await_final(self) -> FinalReveal: ...


@dataclass(frozen=True, slots=True)
class Played:
    """How a sub-game ended, the board it ended on, and whether they played fair."""

    steps: int
    final: BoardState
    captured: bool
    reason: str
    audit: AuditResult

    @property
    def thief_survived(self) -> bool:
        return not self.captured

    @property
    def opponent_played_fairly(self) -> bool:
        return self.audit.clean


@dataclass
class SubGame:
    """One sub-game of one match."""

    role: str
    brain: BrainBase
    peer: Peer
    log: MatchLog
    state: BoardState
    axes: AxisConvention
    max_steps: int
    ceremony: MatchCeremony = field(init=False)
    now: Callable[[], str] = field(default=lambda: "")
    sealed_states: dict[int, BoardState] = field(default_factory=dict, init=False)
    """The board each step was sealed against, kept for the audit.

    Recorded when the step opens, before either side's move is applied. That is
    the state both peers hashed into their commitments, and without it their
    reveals cannot be re-derived from anything — the nonces would arrive and
    prove nothing.
    """

    their_final: FinalReveal | None = field(default=None, init=False)

    require_bound_scent: bool = True
    """Whether a peer must disclose a scent field bound to its commitment.

    **Fail-closed, and the default is the closed side.** Unverifiable scent is
    not weaker evidence than verified scent — it is no evidence wearing the
    appearance of some, and absorbing it would let an opponent steer our belief
    by simply declining to bind what it sends. So a peer that discloses nothing
    checkable fails the audit rather than being quietly excused.

    **Supplied by the caller, from a negotiation.**
    :meth:`~.match.MatchRunner.play_sub_game` reads it off
    :attr:`~..domain.lock.ScentAgreement.require_bound_scent` — the ``binding``
    term of a lock the opponent matched exactly — and refuses to open a sub-game
    at all when no lock was agreed. The default here is what a sub-game
    constructed directly by a test gets, and it is the closed side for the same
    reason the rest of this docstring gives; it is no longer how a match decides.

    Setting this false is the *negotiated* downgrade, and it downgrades to
    **no scent at all** rather than to unverified scent: the reference dialect
    ships its field in the phase-1 turn message, unbound and alongside the
    commitment it would otherwise conceal, and there is no reading of that we
    can accept without giving up both the secrecy of our position and the one
    witness the rulebook calls unfalsifiable. Playing an opponent who speaks
    only that dialect therefore costs the pheromone layer, explicitly, and is
    agreed before the series rather than discovered inside it — which is why the
    lock refuses any other ``binding`` outright rather than accommodating it.
    """

    start: BoardState = field(init=False)
    """The board this sub-game opened on, kept for the scent reconstruction.

    ``state`` moves; the audit needs the position both sides agreed to start
    from, because the whole point of re-deriving the opponent's trail is to do
    it from terms that were fixed before anybody played.
    """

    scent: ScentMemory = field(default_factory=ScentMemory, init=False)
    """What we have emitted, and what we have absorbed — never pooled."""

    belief: Belief = field(init=False)
    """The distribution the policy targets and the live GUI paints.

    One object, not two. A display-only copy would let the picture we show
    diverge from the reasoning we did, which is the one thing the screenshot
    requirement exists to demonstrate.
    """

    play_result: Played | None = field(default=None, init=False)
    """How this sub-game ended, kept so a caller can ask again later.

    ``play()`` returns it too. Keeping it as well means a match runner that
    assembles artefacts after the fact does not have to have held on to the
    return value through a handshake, an audit and a file write.
    """

    def __post_init__(self) -> None:
        self.ceremony = MatchCeremony(role=self.role)
        self.start = self.state
        self.belief = Belief.uniform(self.state)

    @property
    def opponent(self) -> str:
        return OPPONENT_OF[self.role]

    def play(self) -> Played:
        """Run until capture or the step limit, then disclose every nonce.

        The loop stops the moment a capture is on the board rather than
        finishing the step count. A sub-game that continued past a capture
        would produce a log whose later steps describe a game that was already
        over, and two peers disagreeing about when it ended is a disagreement
        about the result.
        """
        if self._captured():
            self._disclose()
            return self._finished(0, captured=True, reason="capture")
        played = 0
        for step in range(1, self.max_steps + 1):
            played = step
            self._one_step(step)
            if self._captured():
                self._disclose()
                return self._finished(step, captured=True, reason="capture")
        self._disclose()
        return self._finished(played, captured=False, reason="step limit reached")

    def _finished(self, steps: int, *, captured: bool, reason: str) -> Played:
        self.play_result = Played(steps, self.state, captured, reason, self.audit())
        return self.play_result

    def _one_step(self, step: int) -> None:
        """Advance the board's own step counter *before* anything is sealed.

        ``step_record`` seals ``state.step``, and the Replay App checks that
        number against the slot the row was filed under — the anti-replay rule
        from #102. A loop that committed while the board still said ``step - 1``
        would produce a log in which every row seals the wrong number, and the
        stamp on every honest match this agent ever played would be
        ``TAMPERED``. It is the loop's job to keep the board and the ceremony
        counting the same thing.
        """
        self.state = advance_turn(self.state)
        self.sealed_states[step] = self.state
        record, action, opened = self._commit(step)
        self._acknowledge(step)
        self._reveal(step, record, opened)
        self._advance(action, self.peer_move(step))
        self._observe(step)
        self.scent.decay()

    def _commit(self, step: int) -> tuple[dict[str, object], Action, Reveal]:
        """Phase 1. Seal our move, record it, then send — in that order.

        The log entry is written **before** the commitment crosses the wire.
        Sending first and recording after would leave a window in which the
        opponent holds a commitment we have no record of making, which is the
        one asymmetry an append-only log exists to prevent.
        """
        decision_state, context = self._strategy_input()
        try:
            signature(self.brain.decide).bind(decision_state, **context)
        except TypeError as exc:
            raise StrategyContextError(
                "configured brain decide() must accept **context containing "
                f"{next(iter(context))}, concentration, and uncertainty"
            ) from exc
        decision = self.brain.decide(decision_state, **context)
        action = decision.action
        self._our_actions[step] = action
        placed = action.at if isinstance(action, PlaceBarrier) else None
        move: Move | str = action.move if isinstance(action, MoveAction) else "barrier"
        laid = self._emit(action)
        record = step_record(
            self.state, self.role, move, decision.intent, decision.hint, placed, laid
        )
        secret = nonce()
        commitment = Commitment(
            step=step,
            sender=self.role,
            commit=commit_of(record, secret),
            timestamp=self.now(),
        )
        self.ceremony.at(step).commit(commitment, secret)
        self.log.commit(step, commitment.commit)
        if decision.reasoning:
            self.log.discuss(step, {"intent": decision.intent, "reasoning": decision.reasoning})
        self.peer.send_commit(commitment)
        self.ceremony.at(step).receive(self.peer.await_commit(step))

        opened = Reveal(
            step=step,
            sender=self.role,
            move=move,
            intent=decision.intent,
            hint=decision.hint,
            timestamp=self.now(),
            barrier_placed=list(placed) if placed else None,
            scent=laid,
        )
        return record, action, opened

    def _strategy_input(self) -> tuple[BoardState, dict[str, object]]:
        """Return the stable, belief-only decision boundary for a strategy.

        ``state`` retains the board geometry and our exact cell, but its opponent
        coordinate is replaced by the deterministic belief peak. The keyword
        context is intentionally small and stable for configured ``**context``
        brains: role-appropriate ``target``/``threat``, ``concentration``, and
        ``uncertainty``.
        """
        self.belief.apply_barriers(self.state)
        peak = self.belief.most_likely()
        if peak is None:
            raise StrategyContextError("opponent belief has no possible cell")
        concentration = self.belief.concentration()
        state = (
            replace(self.state, thief=peak)
            if self.role == "police"
            else replace(self.state, cop=peak)
        )
        focus = "target" if self.role == "police" else "threat"
        return state, {
            focus: peak,
            "concentration": concentration,
            "uncertainty": 1.0 - concentration,
        }

    def _emit(self, action: Action) -> dict[str, float]:
        """Lay this turn's field and return the whole trail, in wire form.

        **Centred where the turn ends, not where it began.** The field is laid
        down by occupying a cell, so an agent that moved emits around its new
        position — and one that stood still, or forfeited movement to build,
        emits around the cell it is on. There is no silent turn.

        The centre is computed by applying the action we are about to commit
        to, which is the same function that will apply it for real a phase
        later. Deriving it any other way would be a second movement model, and
        the two would disagree exactly once, in a match, against a real
        opponent re-deriving our trail from the moves we revealed.

        What is returned is the accumulated trail rather than this turn's
        deposit alone: the rulebook's scent *trail* is a short film of recent
        movement, and a peer sent only the newest frame could read direction
        out of nothing.
        """
        agent = self._agent(self.role)
        after = apply_action(self.state, agent, action, self.axes)
        self.scent.emit(position_of(after, agent), self.state.grid_size)
        return self.scent.outgoing()

    def _observe(self, step: int) -> None:
        """Absorb what the opponent emitted, once the full turn is over.

        Three rules, each of which has a way of being got wrong quietly:

        **Theirs only.** :class:`~..domain.memory.ScentMemory` keeps the two
        fields apart structurally, and the belief update is fed
        ``scent.opponent`` — never a pool. An agent that merged both would
        track itself, confidently, since its own trail is brightest exactly
        where it stands.

        **At the full-turn boundary.** Called after both sides have acted, so
        the evidence entering the belief describes a completed turn rather than
        half of one.

        **Validated, or discarded whole.** A field that fails
        :func:`~..domain.scent_audit.check_field` is not partially absorbed:
        one bad cell means an untrustworthy field, and keeping the rest would
        let an opponent steer the belief with the half we accepted. The failure
        is not raised here either — it surfaces at the audit as a verdict,
        because a crash mid-match is a technical loss scoring zero for *both*
        sides and would reward sending us rubbish.
        """
        self.belief.apply_barriers(self.state)
        opened = self._peer_reveals.get(step)
        if opened is None or opened.scent is None:
            return
        try:
            check_field(opened.scent, self.state.grid_size)
        except ScentFieldError:
            return
        self.scent.absorb(opened.scent, self.state.grid_size)
        absorb_evidence(self.belief, self.scent.opponent.values)

    def _acknowledge(self, step: int) -> None:
        """Phase 2. The phase the reference skips, and the reason reveal is safe."""
        self.peer.send_ack(self.ceremony.at(step).acknowledge(self.now()))
        self.ceremony.at(step).receive_ack(self.peer.await_ack(step))

    def _reveal(self, step: int, record: dict[str, object], opened: Reveal) -> None:
        """Phase 3. Only reachable once both sides are locked."""
        self.ceremony.at(step).reveal(opened)
        self.log.reveal(step, record)
        self.peer.send_reveal(opened)
        self._peer_reveals[step] = self.ceremony.at(step).receive_reveal(
            self.peer.await_reveal(step)
        )

    _peer_reveals: dict[int, Reveal] = field(default_factory=dict, init=False)
    _our_actions: dict[int, Action] = field(default_factory=dict, init=False)
    """What we actually did each step, kept so the audit can replay the board.

    The opponent's trail is only checkable against a board, and the board only
    exists if *both* histories are known — our barrier at step 4 is what makes
    their move at step 5 legal or not.
    """

    def peer_move(self, step: int) -> Action | None:
        """What the opponent said they did, once they have said it."""
        opened = self._peer_reveals.get(step)
        if opened is None:
            return None
        if opened.barrier_placed:
            if self.opponent != "police":
                raise UnplayableReveal(
                    f"the thief revealed a barrier at step {step}; only the cop may place "
                    "one, and a board advanced by an illegal action is a board the two "
                    "peers no longer share"
                )
            return PlaceBarrier(at=(opened.barrier_placed[0], opened.barrier_placed[1]))
        if opened.move not in MOVES:
            raise UnplayableReveal(
                f"the {self.opponent} revealed move {opened.move!r} at step {step}, which is "
                "not a move; the board cannot be advanced from a statement it cannot read"
            )
        return MoveAction(move=cast("Move", opened.move))

    def _advance(self, ours: Action, theirs: Action | None) -> None:
        """Apply both moves to one board.

        Ours first, then theirs, and both against the same starting state as
        far as legality is concerned — the two were chosen simultaneously and
        neither saw the other. Applying them in sequence is the only thing a
        single board can do; what must not happen is either side *deciding*
        with knowledge of the other, and the ceremony above is what prevents it.
        """
        self.state = apply_action(self.state, self._agent(self.role), ours, self.axes)
        if theirs is not None:
            self.state = apply_action(self.state, self._agent(self.opponent), theirs, self.axes)

    @staticmethod
    def _agent(role: str) -> Agent:
        return "cop" if role == "police" else "thief"

    def _captured(self) -> bool:
        """Any of the three capture conditions the rulebook defines."""
        return (
            is_capture_by_overlap(self.state)
            or is_trapping_capture(self.state)
            or is_enclosure_capture(self.state, self.axes)
        )

    def _disclose(self) -> None:
        """Phase 4. Every nonce, once, and only now.

        ``finish()`` is what makes the nonces releasable at all — the ceremony
        refuses to produce them while any step is still open, so a sub-game
        that ended early cannot leak a secret for a step nobody has revealed.
        """
        self.ceremony.finish()
        disclosed = self.ceremony.final_reveal(self.now())
        for step, secret in disclosed.nonces.items():
            self.log.disclose(step, secret)
        self.peer.send_final(disclosed)
        self.their_final = self.ceremony.receive_final_reveal(self.peer.await_final())

    def audit(self) -> AuditResult:
        """Re-derive every step the opponent committed to.

        The nonces arrive in phase 4 and are the only thing that can open their
        commitments, so this is the first moment the question is answerable —
        and it is the last moment anybody asks it. A match that retained all the
        material and never ran this would be one where the cryptography was
        decoration.

        Every step is checked rather than stopping at the first failure. The
        opponent is entitled to the whole list: a dispute settled on one step
        tends to be reopened on the next.
        """
        if self.their_final is None:
            return AuditResult(
                verdict=Verdict.FORGED,
                checked=0,
                failures=(
                    f"the {self.opponent} disclosed no nonces, so nothing they committed "
                    "to can be opened; their play is unverifiable rather than proven",
                ),
            )
        sealed = audit_opponent(self.ceremony, self.their_final, self.sealed_states)
        impossible = self._audit_scent()
        if not impossible:
            return sealed
        return AuditResult(
            verdict=Verdict.FORGED,
            checked=sealed.checked,
            failures=sealed.failures + impossible,
        )

    def _audit_scent(self) -> tuple[str, ...]:
        """Re-derive their trail from the agreed start and the revealed moves.

        A second, independent question from the one the nonces answer. The
        commitments prove the opponent *fixed* its field before the turn; they
        say nothing about whether the field it fixed is one the physics could
        produce. A peer that committed to a trail centred across the board from
        where it stood would open every commitment honestly and pass a
        cryptographic audit — while lying about the one witness Chapter 4 calls
        unfalsifiable.

        So the trail is rebuilt from scratch: both sides' revealed movement
        replayed on the board they agreed to start from, emission on every
        action, decay once per full turn, compared against every field they
        disclosed. This is what makes *a hint may lie, a trail may not* a
        property of the protocol rather than an aspiration about it.
        """
        plays = [
            StepPlay(
                step=step,
                ours=action,
                theirs=self.peer_move(step),
                disclosed=opened.scent if (opened := self._peer_reveals.get(step)) else None,
            )
            for step, action in sorted(self._our_actions.items())
        ]
        return audit_scent(
            self.start,
            self.axes,
            self.role,
            plays,
            require_bound=self.require_bound_scent,
        )
