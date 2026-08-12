"""One sub-game's outcome, as the report records it.

Split from :mod:`.match` for the line budget. It is also the one place that
knows a report entry needs more than the score: when the sub-game ran, what it
cost us in tokens, and what the audit concluded about it -- three facts the
reference's result document carries per sub-game and the runner is the only
thing positioned to measure.
"""

from ..infra.report_parts import SubGameResult
from .match_outcome import SubGameOutcome

__all__ = ["scored"]


def scored(outcome: SubGameOutcome, commit_hash: str) -> SubGameResult:
    """One outcome as the report records it, audit verdict and all."""
    cop, thief = outcome.scores()
    return SubGameResult(
        sub_game=outcome.number,
        cop_score=cop,
        thief_score=thief,
        commit_hash=commit_hash,
        steps=outcome.played.steps,
        started_at=outcome.started_at,
        ended_at=outcome.ended_at,
        tokens=outcome.tokens,
        log_verified=outcome.audit.clean,
        tampered=not outcome.audit.clean,
    )
