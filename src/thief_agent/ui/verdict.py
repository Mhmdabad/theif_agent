"""The stamp the Replay App puts on a log, and the walk that earns it.

FR-7.12 asks for two outcomes: a green ``Verified OK`` on a match, a red
``TAMPERED`` on any alteration however small, and the match void immediately.
FR-7.13 adds that the walk aborts on the first failure rather than gathering a
list — one bad step is already the whole answer, and continuing would only
produce more detail about a match that no longer exists.

**There are three outcomes here, not two, and the third is the design
decision.** A step that carries no nonce cannot be re-derived, and stamping
that ``TAMPERED`` would accuse a team of forgery for a sub-game that ended
early or a log copied mid-match. So the walk distinguishes:

* every step re-derived and matching → ``Verified OK``;
* a step that opens and **disagrees** → ``TAMPERED``, void;
* a step that **cannot be opened** → ``INCOMPLETE``, nothing proven either way.

The obvious worry is that ``INCOMPLETE`` is a hiding place: forge a step, then
delete its nonce and be un-caught. It is not, because it is not an *acquittal*.
The only outcome that clears a log is ``Verified OK``, a log with a missing
nonce never reaches it, and that stamp is what the submission requires. A cheat
who deletes a nonce has not escaped the check — they have failed it in a way
that names their own file as unverifiable.

Which of the three applies is decided by :attr:`~.replay.RecordedStep.openable`
and by the arithmetic, never by reading the text of a reason. Reasons are
written for a person; branching on them would put a verdict at the mercy of
a reworded sentence.

This module reports; it does not navigate. ``walk`` leaves the cursor where it
found it and names the offending step, so a viewer that wants to land there
calls :meth:`~.replay.Replay.seek` and does so visibly.
"""

from dataclasses import dataclass
from enum import Enum

from .replay import Replay, check_step


class Stamp(Enum):
    """The verdict, and the colour the rulebook asks it to be shown in."""

    VERIFIED_OK = "green"
    """Every step re-derived from the log itself and matched."""

    TAMPERED = "red"
    """A step opened and did not produce its commitment. The match is void."""

    INCOMPLETE = "grey"
    """A step could not be opened. Nothing proven, and nothing cleared."""

    @property
    def text(self) -> str:
        """The words on the stamp, spelled as the rulebook spells them."""
        return {
            Stamp.VERIFIED_OK: "Verified OK",
            Stamp.TAMPERED: "TAMPERED",
            Stamp.INCOMPLETE: "INCOMPLETE",
        }[self]


@dataclass(frozen=True, slots=True)
class Attestation:
    """What the walk found, and which step the verdict is about.

    Carries ``verified`` and ``at_step`` alongside the stamp because a red
    banner on its own is an accusation nobody can check. "Step 7 committed to a
    digest its own recorded record and nonce do not produce" is one the other
    team can run themselves and get the same answer — which is the only kind of
    finding that settles anything.
    """

    stamp: Stamp
    verified: int
    total: int
    at_step: int | None = None
    """The step the verdict names: the forged one, or the first unopenable one."""

    unopened: tuple[int, ...] = ()
    """Steps passed over because they could not be re-derived."""

    reason: str = ""

    @property
    def clean(self) -> bool:
        return self.stamp is Stamp.VERIFIED_OK

    @property
    def void(self) -> bool:
        """Whether this result voids the match. No appeal, no retroactive fix."""
        return self.stamp is Stamp.TAMPERED

    def __str__(self) -> str:
        if self.clean:
            return f"{self.stamp.text} — {self.verified} steps re-derived"
        return (
            f"{self.stamp.text} at step {self.at_step} — "
            f"{self.verified} of {self.total} steps re-derived, then {self.reason}"
        )


def walk(replay: Replay) -> Attestation:
    """Re-derive the log in order, aborting the moment a step fails to hold.

    Aborting on a mismatch is the rulebook's instruction and it is also the
    honest thing to report. Once one step is forged the match is void, so the
    steps after it are not evidence of anything — checking them would only
    invite an argument about how many were wrong, when the answer is *enough*.

    A step that cannot be **opened** does not abort the walk, and that
    asymmetry is deliberate. Stopping there would let a cheat shield a forgery
    by deleting the nonce of some earlier step, so the walk passes over the gap
    and keeps looking. It still refuses to clear the log: gaps that survive to
    the end make the verdict ``INCOMPLETE``, never ``Verified OK``. Between the
    two, tampering wins — a proven forgery is a harder fact than a gap.

    Steps are walked in the log's own order rather than from the cursor, so
    the verdict does not depend on where the reader happens to be looking.
    """
    verified = 0
    total = len(replay.steps)
    unopened: list[int] = []
    gap = ""
    for recorded in replay.steps:
        if not recorded.openable:
            unopened.append(recorded.step)
            gap = gap or check_step(recorded).reason
            continue
        checked = check_step(recorded)
        if not checked.verified:
            return Attestation(
                Stamp.TAMPERED,
                verified,
                total,
                at_step=recorded.step,
                unopened=tuple(unopened),
                reason=checked.reason,
            )
        verified += 1
    if unopened:
        return Attestation(
            Stamp.INCOMPLETE,
            verified,
            total,
            at_step=unopened[0],
            unopened=tuple(unopened),
            reason=gap,
        )
    return Attestation(Stamp.VERIFIED_OK, verified, total)
