"""The result document, in the shape the lecturer's own tooling reads.

Modelled field for field on ``docs/sample-run/result_*.json`` in the reference
implementation, because the rulebook does not specify a layout and the grader
is the reference. Where the two disagree elsewhere the book wins; here it is
silent, so the reference is the only specification there is.

**Everything is keyed by group id, never by role.** Roles alternate every
sub-game, so ``cop_score`` names a seat rather than a team and cannot be added
up across a series. The book scores a group pair; this document says so
directly, and a reader building league standings never has to work out who sat
where.

    Unknown values are explicit rather than invented. Counted reference-v3 exchanges
    the opponent's commit; legacy paths retain ``unknown`` when it never crossed the wire.
"""

from typing import TYPE_CHECKING, Any

from ..domain.alternation import role_for
from ..domain.scoring import Outcome
from ..shared.naming import declaration_filename, log_filename, result_filename
from .report_league import final_result, league_block

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from .report_document import Report
    from .report_parts import SubGameResult

__all__ = ["SCHEMA_VERSION", "TIMEZONE", "UNKNOWN", "by_group", "links", "result_document"]

SCHEMA = "".join(
    [
        "Summary and final result for the WHOLE game (all sub-games) between two teams. It ",
        "condenses the per-sub-game logs into a per-group score for every sub-game plus the ",
        "aggregate outcome the lecturer needs to build the league standings. Static team ",
        "metadata (identity, members, repos, MCP, hardware, model) is NOT repeated here — it ",
        "lives in 1-pre-game-declaration.json and is referenced via game_id / group_id. Both ",
        "teams must agree on this result and each sends its own copy to the lecturer (book ch9).",
    ]
)
"""The reference's own description, carried verbatim so the two documents match."""

SCHEMA_VERSION = "1.1"
"""The reference's version, because this is the reference's document."""

TIMEZONE = "Asia/Jerusalem"
"""Where the course is. Timestamps stay UTC; this names the reading."""

UNKNOWN = "unknown"
"""What the reference writes for a fact the reporting peer cannot have."""


def links(game_id: str, report: "Report | None" = None) -> dict[str, Any]:
    """The four artefact names, derived from ``game_id`` as the reference requires.

    ``config`` and ``log`` keep the literal ``<NN>``: one file per sub-game, so a
    single name would be a lie about a series.
    """
    body: dict[str, Any] = {
        "_remark": (
            "Logical roles, not fixed filenames. Every name is derived from game_id so "
            "files from different games are never mixed. Match-level files are "
            "<role>_<game_id>.json; per-sub-game files are <role>_<game_id>_g<NN>.json."
        ),
        "declaration": declaration_filename(game_id),
        "config": f"config_{game_id}_g<NN>.json",
        "log": f"log_{game_id}_g<NN>.json",
        "result": result_filename(game_id),
    }
    if report and report.repositories:
        repos = report.repositories
        body["github"] = {
            report.team: {"cop": repos.cop_repo, "thief": repos.thief_repo},
            report.opponent_team: {
                "cop": repos.opponent_cop_repo,
                "thief": repos.opponent_thief_repo,
            },
        }
    return body


def _outcome(sub: "SubGameResult") -> str:
    """How the sub-game ended, in the reference's vocabulary."""
    if sub.technical_loss:
        return Outcome.TECHNICAL_LOSS.value
    return Outcome.CAPTURE.value if sub.cop_score > sub.thief_score else Outcome.SURVIVAL.value


def by_group(
    sub: "SubGameResult", us: str, them: str, natural: str, game_id: str
) -> dict[str, Any]:
    """One sub-game, with every per-team fact keyed by group id."""
    ours = role_for(natural, sub.sub_game)
    theirs = "thief" if ours == "police" else "police"
    our_score = sub.cop_score if ours == "police" else sub.thief_score
    their_score = sub.thief_score if ours == "police" else sub.cop_score
    winner = None if our_score == their_score else (us if our_score > their_score else them)
    return {
        "sub_game_number": sub.sub_game,
        "roles": {us: ours, them: theirs},
        "started_at": sub.started_at,
        "ended_at": sub.ended_at,
        "result": _outcome(sub),
        "winner_group": winner,
        "tie": our_score == their_score,
        "steps": sub.steps,
        "github_commit": {us: sub.commit_hash, them: sub.opponent_commit_hash},
        "tokens": {us: sub.tokens, them: 0},
        "score": {us: our_score, them: their_score},
        "log_files": dict.fromkeys((us, them), log_filename(game_id, sub.sub_game)),
        "audit": {"log_verified": sub.log_verified, "tampered": sub.tampered},
    }


def result_document(report: "Report") -> dict[str, Any]:
    """The lecturer's field set, plus the cohort's league block.

    No consensus signature key: neither the lecturer's sample nor the cohort's
    example carries one. The kit pins the signature's *construction* and the
    scope it covers, and what two teams must agree on is
    ``mutual_agreement.sha256`` -- not a field beside it.
    """
    us, them = report.team, report.opponent_team
    natural = report.starting_role or report.role
    standing = report.series_result or {}
    subs = [by_group(sub, us, them, natural, report.game_id) for sub in report.sub_games]
    return {
        "_schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "report_type": "final_game_result",
        "game_id": report.game_id,
        "game_uid": report.game_uid,
        "links": links(report.game_id, report),
        "timezone": TIMEZONE,
        "groups": [us, them],
        "num_sub_games": len(report.sub_games),
        "sub_games": subs,
        "final_result": final_result(report, standing, us, them),
        "mutual_agreement": {"sha256": report.result_claim_sha256, "confirmed": report.agreed},
        "league": league_block(report.counted),
    }
