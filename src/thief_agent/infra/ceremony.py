"""The four-phase Commit-Reveal ceremony, in the order the rulebook gives it.

Commit, Acknowledge, Reveal, Final Reveal. Each phase exists to remove one way
of cheating, and the order is the mechanism — a phase performed early gives
away exactly what the next phase was protecting.

**Why this is a separate module from** :mod:`.protocol`. The reference bundles
a turn into a single ``TurnMessage`` carrying the commitment *and* the hint
together, one round trip per turn. The rulebook does not: it puts an
Acknowledge between them, and says why — the acknowledgement *"ensures the
reveal happens only once both sides have already fixed their moves"* (Ch. 5.3.2).

Those are not the same protocol. Under the bundled form, whichever peer sends
second has already read the first one's hint before choosing what to commit to,
which is the precise advantage the Acknowledge phase exists to remove. The
rulebook is authoritative, so the ceremony here follows the book; the bundled
shape stays available through :class:`~.protocol.TurnMessage` for an opponent
who will only speak the reference dialect, and the divergence is recorded in
the README contradictions table.

Phase 1 is this module's smallest and strictest object. A commitment is a hash
and the bookkeeping needed to file it — nothing else. Any additional field is a
way to narrow the search space of what was committed to, and the move space is
small enough that narrowing it at all is fatal: five moves and a handful of
barrier cells means an opponent who learns *which cells were even candidates*
can hash the remainder in microseconds.
"""

import secrets
from typing import Any

from ..domain.board import BoardState
from ..domain.crypto import commit_of, step_record
from .ceremony_ack import ACK_FIELDS, Acknowledgement
from .ceremony_commit import COMMIT_FIELDS, Commitment
from .ceremony_errors import DIGEST, NONCE, NONCE_LENGTH, CeremonyError
from .ceremony_final import FinalReveal
from .ceremony_match import MatchCeremony
from .ceremony_reveal import REVEAL_FIELDS, Reveal
from .ceremony_step import StepCeremony
from .ceremony_verdict import AuditResult, Verdict

__all__ = [
    "ACK_FIELDS",
    "COMMIT_FIELDS",
    "DIGEST",
    "NONCE",
    "NONCE_LENGTH",
    "REVEAL_FIELDS",
    "Acknowledgement",
    "AuditResult",
    "CeremonyError",
    "Commitment",
    "FinalReveal",
    "MatchCeremony",
    "Reveal",
    "StepCeremony",
    "Verdict",
    "audit_opponent",
    "verify_step",
]


def verify_step(record: dict[str, Any], nonce: str, commit: str) -> bool:
    """Whether ``record`` under ``nonce`` really produces ``commit``.

    Compared with :func:`secrets.compare_digest` rather than ``==``, as the
    rulebook specifies. Being honest about why: by audit time both digests are
    public, so the timing channel here leaks nothing anyone does not already
    have. The reason to use it anyway is that ``==`` on a digest is a habit,
    and the habit is what eventually gets applied to a comparison where the
    timing *does* matter — and a project that hashes for a living should not be
    growing that habit.
    """
    return secrets.compare_digest(commit_of(record, nonce), commit)


def audit_opponent(
    match: MatchCeremony,
    disclosed: FinalReveal,
    sealed_states: dict[int, BoardState],
) -> AuditResult:
    """Re-derive every step the opponent committed to, and say whether it holds.

    ``sealed_states`` is the board they sealed against at each step, supplied
    by the caller: reconstructing their trajectory is a different job from
    checking arithmetic, and mixing the two would make a reconstruction bug
    indistinguishable from a forgery.

    The record is rebuilt through :func:`~..domain.crypto.step_record` — the
    same function the committer used, not a re-implementation of it. An audit
    with its own assembly path would report forgery whenever the two paths
    drifted, which is the one verdict that must never be reachable by accident.

    A step is a failure if we cannot rebuild it *or* if the rebuild disagrees.
    Those are reported separately: a missing reveal and a wrong digest are
    different accusations, and only one of them is provable tampering.

    **Every step is checked before returning.** Stopping at the first failure
    would be faster and would hand the opponent an incomplete accusation — they
    are entitled to see the whole list, and a dispute settled on one step tends
    to be reopened on the next.
    """
    failures: list[str] = []
    checked = 0
    for step in sorted(match.steps):
        ceremony = match.steps[step]
        if ceremony.theirs is None:
            continue
        checked += 1
        opened, nonce = ceremony.revealed_theirs, disclosed.nonces.get(step)
        if opened is None:
            failures.append(f"step {step}: committed but never revealed")
            continue
        if nonce is None:
            failures.append(f"step {step}: committed but no nonce disclosed")
            continue
        if step not in sealed_states:
            failures.append(f"step {step}: no board state to re-derive against")
            continue
        record = step_record(
            sealed_states[step],
            opened.sender,
            opened.move,
            opened.intent,
            opened.hint,
            barrier_placed=(
                (opened.barrier_placed[0], opened.barrier_placed[1])
                if opened.barrier_placed
                else None
            ),
            scent=opened.scent,
            game_uid=opened.game_uid,
            sub_game=opened.sub_game,
        )
        if not verify_step(record, nonce, ceremony.theirs.commit):
            failures.append(
                f"step {step}: committed {ceremony.theirs.commit[:16]}… but the revealed "
                f"move {opened.move!r} under the disclosed nonce produces "
                f"{commit_of(record, nonce)[:16]}…"
            )
    return AuditResult(
        verdict=Verdict.FORGED if failures else Verdict.CLEAN,
        checked=checked,
        failures=tuple(failures),
    )
