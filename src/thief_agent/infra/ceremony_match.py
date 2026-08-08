"""The match-level ceremony: every step's, and the event that ends them all."""

from dataclasses import dataclass, field

from ..domain.actions import ROLES
from .ceremony_errors import CeremonyError
from .ceremony_final import FinalReveal
from .ceremony_step import StepCeremony


@dataclass
class MatchCeremony:
    """Every step's ceremony, and the one event that ends them all.

    Exists so phase 4 has something to be complete *against*. A final reveal is
    only meaningful relative to the set of steps that were played, and no
    individual :class:`StepCeremony` knows how many of those there were.
    """

    role: str
    steps: dict[int, StepCeremony] = field(default_factory=dict)
    over: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CeremonyError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")

    def at(self, step: int) -> StepCeremony:
        """The ceremony for ``step``, opening one if this is its first message."""
        if step not in self.steps:
            self.steps[step] = StepCeremony(step=step, role=self.role)
        return self.steps[step]

    def finish(self) -> None:
        """Mark the match over. Only after this may nonces be disclosed."""
        self.over = True

    def final_reveal(self, timestamp: str) -> FinalReveal:
        """Disclose every nonce of the match, at the end, in one message.

        Raises:
            CeremonyError: while the match is still running, or if any step
                cannot contribute a nonce. Both refusals protect the same
                thing from opposite sides — an early disclosure reopens
                commitments that still matter, and a partial one leaves a step
                nobody can re-derive, which is precisely the step a cheat would
                omit.
        """
        if not self.over:
            raise CeremonyError(
                "cannot disclose nonces while the match is running; every step uses the "
                "same construction, so one released early narrows all the others"
            )
        missing = sorted(step for step, one in self.steps.items() if one.our_nonce is None)
        if missing:
            raise CeremonyError(
                f"no nonce recorded for step(s) {missing}; a step nobody can re-derive "
                "proves nothing at audit, which is what makes a partial reveal worse "
                "than a late one"
            )
        return FinalReveal(
            sender=self.role,
            nonces={step: one.our_nonce for step, one in self.steps.items() if one.our_nonce},
            timestamp=timestamp,
        )

    def receive_final_reveal(self, disclosed: FinalReveal) -> FinalReveal:
        """File the opponent's nonces, checking they cover what they committed to.

        Raises:
            CeremonyError: if it comes from the wrong role, or omits a step
                they committed to. Extra steps are tolerated — a nonce for a
                step we have no record of verifies nothing and harms nothing —
                but a **missing** one is the shape of a hidden move.
        """
        if disclosed.sender != self.opponent:
            raise CeremonyError(
                f"final reveal is from {disclosed.sender!r}, expected {self.opponent!r}"
            )
        owed = {step for step, one in self.steps.items() if one.theirs is not None}
        absent = sorted(owed - set(disclosed.nonces))
        if absent:
            raise CeremonyError(
                f"their final reveal omits step(s) {absent}, which they committed to; "
                "an unopenable commitment is indistinguishable from a hidden move"
            )
        return disclosed

    @property
    def opponent(self) -> str:
        """The role that is not ours."""
        return next(role for role in sorted(ROLES) if role != self.role)
