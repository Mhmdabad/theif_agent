"""What one step's ceremony *has*, and the questions answerable from that alone.

The base of :class:`~.ceremony.StepCeremony`: the evidence a step accumulates,
plus the reads that need no phase to be performed — whose turn it is not,
whether the lock is complete, and what is still missing. The phases themselves
live in :mod:`.ceremony_step_lock` and :mod:`.ceremony_step`, which extend this.
"""

from dataclasses import dataclass

from ..domain.actions import ROLES
from .ceremony_ack import Acknowledgement
from .ceremony_commit import Commitment
from .ceremony_errors import CeremonyError
from .ceremony_reveal import Reveal


@dataclass
class StepState:
    """The evidence one step accumulates, and the reads that need no phase.

    Split from the phases so the messages a step is holding, and the questions
    answerable from them alone, can be read without the methods that add to
    them. :class:`~.ceremony.StepCeremony` is this plus the four phases.
    """

    step: int
    role: str
    ours: Commitment | None = None
    theirs: Commitment | None = None
    ack_sent: Acknowledgement | None = None
    ack_received: Acknowledgement | None = None
    revealed_ours: Reveal | None = None
    revealed_theirs: Reveal | None = None
    our_nonce: str | None = None
    """The secret this step will disclose in phase 4, and not before.

    Held by the ceremony rather than by the message, which is the whole point:
    :class:`Commitment` cannot carry it and :class:`Reveal` refuses it, so the
    only path from here to the wire is the final reveal.
    """

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CeremonyError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")

    @property
    def opponent(self) -> str:
        """The role that is not ours."""
        return next(role for role in sorted(ROLES) if role != self.role)

    @property
    def locked(self) -> bool:
        """Whether both sides have committed *and* said so.

        The gate the rulebook puts between Commit and Reveal. All four have to
        be in: our commitment, theirs, our acknowledgement of theirs and theirs
        of ours. Three out of four is a peer that can still change its mind.
        """
        return all(
            part is not None for part in (self.ours, self.theirs, self.ack_sent, self.ack_received)
        )

    def pending(self) -> str:
        """Which parts of the lock are still missing. For the error, and the log."""
        missing = [
            name
            for name, part in (
                ("our commitment", self.ours),
                ("their commitment", self.theirs),
                ("our acknowledgement", self.ack_sent),
                ("their acknowledgement", self.ack_received),
            )
            if part is None
        ]
        return "missing " + ", ".join(missing) if missing else "locked"

    def _check_belongs(self, step: int, sender: str, expected_role: str, what: str) -> None:
        if step != self.step:
            raise CeremonyError(f"{what} is for step {step}, this ceremony is step {self.step}")
        if sender != expected_role:
            raise CeremonyError(f"{what} is from {sender!r}, expected {expected_role!r}")

    @staticmethod
    def _check_binding(game_uid: str, sub_game: int, locked: Commitment, what: str) -> None:
        if game_uid != locked.game_uid or sub_game != locked.sub_game:
            raise CeremonyError(
                f"{what} binding {game_uid!r}/{sub_game} does not match locked commitment "
                f"{locked.game_uid!r}/{locked.sub_game}"
            )
