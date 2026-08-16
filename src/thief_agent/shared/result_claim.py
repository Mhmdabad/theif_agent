"""What "the result" means when two peers have to agree on one.

Appendix E rule 35 requires both sides to agree the result *before* either
reports it, and each side then sends its own report. Agreement needs something
narrower than a report to agree about: a report carries timestamps, token
counts, repository URLs and a role, all of which legitimately differ between
the two peers. Hashing that would make honest opponents disagree forever.

So the claim below is the intersection — the part of the result that is a fact
about the *series* rather than about the peer describing it: which series, and
what each sub-game scored for each side. Two peers that played the same match
produce identical bytes here, and two peers that disagree about who won produce
different ones, which is the entire question.

The scores travel as ``(cop, thief)`` in both repositories rather than as "ours"
and "theirs", because a claim phrased from the sender's point of view would be
two different claims and could never match.
"""

from collections.abc import Sequence
from typing import Any

from .consensus import consensus_signature
from .consensus_scope import consensus_scope

__all__ = ["claim_and_digest", "claim_sha256", "result_claim"]


def result_claim(
    game_id: str,
    rows: Sequence[dict[str, Any]],
    series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The agreeable part of a result, in the cohort's settled scope.

    Delegates to :func:`~.consensus_scope.consensus_scope`, which is where the
    shape and the reasoning live. What matters here is what changed: this used
    to hash ``game_uid`` with ``cop_score``/``thief_score`` rows and role-keyed
    totals -- an honest scope, and one no other implementation computes, so the
    digest could never equal a stranger's and settlement failed at the moment
    both sides had to agree.

    Args:
        game_id: the match both sides name identically, sorted from the pair.
        rows: the result document's own sub-game entries, trimmed by the scope.
        series: the group-keyed standing the aggregate is taken from.
    """
    return consensus_scope(game_id, series or {}, list(rows))


def claim_sha256(claim: dict[str, Any]) -> str:
    """The digest exchanged before either side reports.

    The reference report writer uses its exceptional spaced serialization for
    this digest.  :func:`consensus_signature` pins that form to the kit vector.
    """
    return consensus_signature(claim)


def claim_and_digest(
    game_id: str,
    rows: Sequence[dict[str, Any]],
    series: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """The claim and the digest over it, built together so they cannot disagree.

    Two callers need this pair: :meth:`~..runtime.match.MatchRunner.agree_result`,
    which puts the digest on the wire, and the report, which records the digest
    the two sides agreed on (§9.3.3 wants the mutual agreement backed by
    SHA-256, not asserted by a boolean). Built here rather than twice because a
    claim assembled slightly differently in one of those places would produce a
    digest that silently fails to match the one actually exchanged — and the
    report would then attest to an agreement that never happened.
    """
    claim = result_claim(game_id, rows, series=series)
    return claim, claim_sha256(claim)
