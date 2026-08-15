"""Filling a sub-game's log summary once the series has settled.

A sub-game cannot state its own outcome while it is being played: the result is
not known until it ends, and ``mutual_agreement`` not until the whole series is
agreed. So the runner fills both here, at the moment the artefacts are
assembled, from the outcome it already holds and the report both peers accepted.
"""

from typing import TYPE_CHECKING

from ..infra.match_log import MatchLog
from ..infra.report_reference import TIMEZONE

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from ..infra.report_document import Report
    from .match_outcome import SubGameOutcome

__all__ = ["settled"]


def _seconds(started: str, ended: str) -> float | None:
    """Wall-clock length of the sub-game, or ``None`` when either end is unknown."""
    from datetime import datetime

    if not started or not ended:
        return None
    try:
        return round(
            (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds(), 1
        )
    except ValueError:
        return None


def settled(outcome: "SubGameOutcome", result: "Report") -> MatchLog:
    """The outcome's log with its summary and settlement filled in."""
    log = outcome.log
    cop, thief = outcome.scores()
    ours = log.role
    winner = "police" if cop > thief else ("thief" if thief > cop else None)
    log.summary.update(
        {
            "group_id": result.team,
            "opponent_group_id": result.opponent_team,
            "result": "capture" if cop > thief else "survival",
            "winner_role": winner,
            "steps": outcome.played.steps,
            "timezone": TIMEZONE,
            "started_at": outcome.started_at,
            "ended_at": outcome.ended_at,
            "duration_seconds": _seconds(outcome.started_at, outcome.ended_at),
            "tokens_total": outcome.tokens,
            "audit": {
                "passed": outcome.audit.clean,
                "verified_steps": len(log.entries),
                "failed_steps": [] if outcome.audit.clean else sorted(log.entries),
            },
        }
    )
    log.settlement.update(
        {
            "opponent_group_id": result.opponent_team,
            "sha256": result.result_claim_sha256,
            "confirmed": result.agreed,
        }
    )
    _ = ours
    return log
