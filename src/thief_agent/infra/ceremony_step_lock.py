"""Phases 1 and 2 of one step: committing, and locking both sides on it.

Everything up to — and only up to — the point where revealing becomes legal.
:class:`~.ceremony.StepCeremony` extends this with phase 3.
"""

from dataclasses import dataclass

from .ceremony_ack import Acknowledgement
from .ceremony_commit import Commitment
from .ceremony_errors import NONCE, NONCE_LENGTH, CeremonyError
from .ceremony_step_state import StepState


@dataclass
class StepLock(StepState):
    """The commit and acknowledge phases, in the order the rulebook gives them."""

    def commit(self, ours: Commitment, nonce: str) -> Commitment:
        """File our own commitment for this step, and keep the nonce that opens it.

        The nonce arrives here rather than staying with the caller because this
        object is what discloses it in phase 4. A secret held somewhere else is
        a secret with a second path to the wire.

        Raises:
            CeremonyError: on a second commitment, one for another step or
                role, or a malformed nonce. Re-committing is the move this
                ceremony exists to prevent, and it is not less serious for
                being local.
        """
        if self.ours is not None:
            raise CeremonyError(
                f"step {self.step} is already committed; a commitment is not revisable"
            )
        if not NONCE.match(nonce):
            raise CeremonyError(f"nonce is not {NONCE_LENGTH} hex characters: {nonce!r}")
        self._check_belongs(ours.step, ours.sender, expected_role=self.role, what="commitment")
        self.ours = ours
        self.our_nonce = nonce
        return ours

    def receive(self, theirs: Commitment) -> Commitment:
        """File the opponent's commitment.

        Raises:
            CeremonyError: if they commit twice, or for the wrong step or role.
                A second commitment for one step is either a bug on their side
                or an attempt to replace a move, and we cannot tell which.
        """
        if self.theirs is not None:
            raise CeremonyError(
                f"the opponent already committed to step {self.step}; "
                "a second commitment would replace a move that is already locked"
            )
        self._check_belongs(
            theirs.step, theirs.sender, expected_role=self.opponent, what="commitment"
        )
        if self.ours is not None:
            self._check_binding(theirs.game_uid, theirs.sub_game, self.ours, "commitment")
        self.theirs = theirs
        return theirs

    def acknowledge(self, timestamp: str) -> Acknowledgement:
        """Confirm we are locked on their commitment.

        Raises:
            CeremonyError: if they have not committed. Acknowledging nothing is
                worse than not acknowledging: it tells them they may reveal,
                against a step we have no record of.
        """
        if self.theirs is None:
            raise CeremonyError(
                f"nothing to acknowledge at step {self.step}; the opponent has not committed, "
                "and acknowledging would tell them to reveal into a step we cannot check"
            )
        self.ack_sent = Acknowledgement(
            step=self.step,
            sender=self.role,
            acknowledges=self.theirs.commit,
            timestamp=timestamp,
        )
        return self.ack_sent

    def receive_ack(self, ack: Acknowledgement) -> Acknowledgement:
        """File their acknowledgement of *our* commitment.

        Raises:
            CeremonyError: if we have not committed, if it is for the wrong
                step or role, or if the digest is not the one we sent. That
                last case is the one worth the check: an acknowledgement of
                some other digest is not a weaker lock, it is a lock on a
                commitment we never made.
        """
        if self.ours is None:
            raise CeremonyError(f"acknowledgement for step {self.step} arrived before we committed")
        self._check_belongs(
            ack.step, ack.sender, expected_role=self.opponent, what="acknowledgement"
        )
        if ack.acknowledges != self.ours.commit:
            raise CeremonyError(
                f"they acknowledged {ack.acknowledges[:16]}… but we committed "
                f"{self.ours.commit[:16]}…; that is a lock on a commitment we never made"
            )
        self.ack_received = ack
        return ack
