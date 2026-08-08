"""One step's ceremony, completed: the lock, and phase 3 on top of it."""

from dataclasses import dataclass

from .ceremony_errors import CeremonyError
from .ceremony_reveal import Reveal
from .ceremony_step_lock import StepLock


@dataclass
class StepCeremony(StepLock):
    """The four phases of one step, and what is permitted at each point.

    A mutable object among frozen ones, deliberately: the messages are
    evidence and must not change, while *how far we have got* is the one thing
    that legitimately does.

    The invariant the whole class exists for is :attr:`locked` — nothing may be
    revealed until both peers hold each other's commitment and have said so.
    Everything else here is bookkeeping in service of that one question.
    """

    def reveal(self, opened: Reveal) -> Reveal:
        """Disclose our action and hint, once and only once both sides are locked.

        Raises:
            CeremonyError: if the lock is incomplete, or on a second reveal.
                Revealing early is not an efficiency — it hands the opponent
                our move while theirs is still free to change, which is the one
                thing the acknowledgement was for.
        """
        if not self.locked:
            raise CeremonyError(
                f"cannot reveal step {self.step} before both sides are locked ({self.pending()}); "
                "revealing early hands over our move while theirs can still change"
            )
        if self.revealed_ours is not None:
            raise CeremonyError(f"step {self.step} is already revealed; a reveal is not revisable")
        self._check_belongs(opened.step, opened.sender, expected_role=self.role, what="reveal")
        assert self.ours is not None
        self._check_binding(opened.game_uid, opened.sub_game, self.ours, "reveal")
        self.revealed_ours = opened
        return opened

    def receive_reveal(self, opened: Reveal) -> Reveal:
        """File the opponent's disclosure. **It cannot be checked yet.**

        The digest cannot be recomputed without their nonce, so this is
        believed on the strength of the lock and verified only at the final
        audit. Storing it is therefore the whole job: a reveal we did not keep
        is a step the audit cannot re-derive, and an audit that cannot
        re-derive a step proves nothing about it either way.

        Raises:
            CeremonyError: if they have not committed, if we are not locked, or
                on a second reveal for the step.
        """
        if not self.locked:
            raise CeremonyError(
                f"the opponent revealed step {self.step} before both sides were locked "
                f"({self.pending()}); accepting it would reward revealing early"
            )
        if self.revealed_theirs is not None:
            raise CeremonyError(
                f"the opponent already revealed step {self.step}; "
                "a second disclosure would replace an action we have acted on"
            )
        self._check_belongs(opened.step, opened.sender, expected_role=self.opponent, what="reveal")
        assert self.theirs is not None
        self._check_binding(opened.game_uid, opened.sub_game, self.theirs, "reveal")
        self.revealed_theirs = opened
        return opened
