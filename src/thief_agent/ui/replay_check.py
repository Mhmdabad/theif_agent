"""Re-deriving one recorded step, and saying what came of it.

Split out of :mod:`.replay` to keep each module inside the line budget. Nothing
here reads a file or moves a cursor: it takes a step the loader already
vouched for the *shape* of and asks the only question the Replay App's
authority rests on — whether the stored commitment is the one the stored record
and nonce produce.
"""

import secrets
from dataclasses import dataclass

from ..domain.crypto import CryptoError, commit_of
from .replay_model import RecordedStep


@dataclass(frozen=True, slots=True)
class StepCheck:
    """One step, re-derived."""

    step: int
    verified: bool
    reason: str = ""

    def __str__(self) -> str:
        return f"step {self.step}: {'ok' if self.verified else self.reason}"


def check_step(recorded: RecordedStep) -> StepCheck:
    """Recompute the digest from the sealed record and its nonce.

    The whole of the Replay App's authority is this one line of arithmetic:
    ``sha256`` over the record the log stores, under the nonce the log stores,
    compared with the commitment the log stores. If those three were written
    honestly as the match ran, they agree; if any was edited afterwards, they
    cannot be made to.

    A step that cannot be opened is reported as **unverifiable** rather than
    failed. A mid-match log, or one from a sub-game that ended early, has steps
    with no nonce — and calling those tampered would accuse an honest team of
    fraud for stopping.

    Never raises. Every recorded step gets an answer, including one whose
    stored record is shaped in a way the committer could not have produced —
    a viewer that crashed on a hand-edited log would be reporting the edit as
    its own bug.

    A matching digest is necessary and not sufficient. It proves the row is
    **genuine**; it says nothing about whether the row is *here* honestly. A
    whole step copied from earlier in the same log re-derives perfectly, so the
    sealed step number is checked against the slot it was filed in — which is
    what the step number is sealed for. Anti-replay only works if somebody
    compares the two.
    """
    if not recorded.openable:
        missing = "no reveal" if recorded.reveal is None else "no nonce"
        return StepCheck(recorded.step, verified=False, reason=f"cannot be opened ({missing})")
    assert recorded.reveal is not None and recorded.nonce is not None
    try:
        recomputed = commit_of(recorded.reveal, recorded.nonce)
    except CryptoError as exc:
        return StepCheck(
            recorded.step,
            verified=False,
            reason=f"its recorded record cannot be hashed as the committer hashed it: {exc}",
        )
    if not secrets.compare_digest(recomputed, recorded.commit):
        return StepCheck(
            recorded.step,
            verified=False,
            reason=(
                f"commitment {recorded.commit[:16]}… but the recorded record under the "
                f"recorded nonce produces {recomputed[:16]}…"
            ),
        )
    sealed = recorded.reveal.get("state")
    if isinstance(sealed, dict) and sealed.get("step") != recorded.step:
        return StepCheck(
            recorded.step,
            verified=False,
            reason=(
                f"the record here is genuine but seals step {sealed.get('step')!r}; "
                "a real step filed under another number is a replay, not a record"
            ),
        )
    return StepCheck(recorded.step, verified=True)
