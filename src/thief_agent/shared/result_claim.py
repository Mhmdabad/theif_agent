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

import hashlib
from collections.abc import Sequence
from typing import Any

from .config import canonical_bytes

__all__ = ["claim_and_digest", "claim_sha256", "result_claim"]


def result_claim(
    game_uid: str,
    scores: Sequence[tuple[int, int]],
    series: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The agreeable part of a result: the series, and every sub-game's score.

    Args:
        game_uid: the series this claim is about, so a result agreed for one
            series cannot be replayed to close another.
        scores: ``(cop, thief)`` per sub-game, in the order they were played.
        series: the group-keyed standing — totals, winner, tie rule, who opened
            as police — computed by the runner so this module stays below the
            domain layer. Group-name keys keep it objective: both peers name
            the same two groups, so both produce identical bytes.
    """
    claim = {
        "game_uid": game_uid,
        "sub_games": [
            {"sub_game": number, "cop_score": cop, "thief_score": thief}
            for number, (cop, thief) in enumerate(scores, start=1)
        ],
        "cop_total": sum(cop for cop, _ in scores),
        "thief_total": sum(thief for _, thief in scores),
    }
    if series is not None:
        claim["series"] = series
    return claim


def claim_sha256(claim: dict[str, Any]) -> str:
    """The digest exchanged before either side reports.

    Over :func:`~.config.canonical_bytes`, the one canonical form every other
    digest in this system is taken over — so the property that makes the config
    digest comparable across two machines holds here for the same reason.
    """
    return hashlib.sha256(canonical_bytes(claim)).hexdigest()


def claim_and_digest(
    game_uid: str,
    scores: Sequence[tuple[int, int]],
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
    claim = result_claim(game_uid, scores, series=series)
    return claim, claim_sha256(claim)
