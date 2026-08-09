"""Emitting our trail, absorbing theirs, and re-deriving theirs at the audit.

Split from :mod:`.subgame` unchanged, including the fail-closed rule: both the
absorb path and the audit pass ``require_bound=self.require_bound_scent``, so a
peer that discloses scent it cannot bind to its commitment fails the audit
rather than being quietly excused.
"""

from dataclasses import dataclass

from ..domain.actions import Action, apply_action
from ..domain.inference import update as absorb_evidence
from ..domain.rules import position_of
from ..domain.scent_audit import ScentFieldError, StepPlay, audit_scent, check_field
from .subgame_moves import SubGameMoves


@dataclass
class SubGameScent(SubGameMoves):
    """The pheromone half of a sub-game: emit, absorb, and re-derive."""

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
        plays = [
            StepPlay(
                step=played_step,
                ours=action,
                theirs=self.peer_move(played_step),
                disclosed=reveal.scent if (reveal := self._peer_reveals.get(played_step)) else None,
            )
            for played_step, action in sorted(self._our_actions.items())
            if played_step <= step
        ]
        failures = audit_scent(
            self.start,
            self.axes,
            self.role,
            plays,
            require_bound=self.require_bound_scent,
        )
        if any(
            failure.startswith(f"step {step}:") or "revealed move cannot be replayed" in failure
            for failure in failures
        ):
            return
        self.scent.absorb(opened.scent, self.state.grid_size)
        absorb_evidence(self.belief, self.scent.opponent.values)

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
