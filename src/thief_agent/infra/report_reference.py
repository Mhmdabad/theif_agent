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

**This is a superset of the reference, because §9.3.3 requires more than the
reference emits.** The book names what the attached JSON must carry: the group's
identity, its GitHub addresses, the FastMCP server addresses, cryptographically
signed hardware declarations, the game timestamp, and SHA-256-backed agreement.
It then lists the mandatory fields outright -- both groups' GitHub links, each
sub-game's commit id, and the tokens consumed.

The reference's result omits the links, the addresses, the hardware and the
match timestamp, because its declaration sits in the repository beside it. The
attachment is the report, and the book outranks the reference where they
disagree, so the shape is the reference's and the contents are the book's.

Two fields are honest about what this peer cannot know. The opponent's commit
is ``unknown`` -- the greeting carries a role, a group id, a URL and a protocol
version, and nothing else crosses the wire -- and the opponent's token spend is
theirs to report, not ours to guess. The reference's own sample writes
``unknown`` in exactly this place.
"""

from typing import TYPE_CHECKING, Any

from ..domain.alternation import role_for
from ..domain.scoring import Outcome
from ..shared.naming import declaration_filename, log_filename, result_filename

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from .report_document import Report
    from .report_parts import SubGameResult

__all__ = ["SCHEMA_VERSION", "TIMEZONE", "UNKNOWN", "links", "result_document"]

SCHEMA_VERSION = "1.1"
"""The reference's version, because this is the reference's document."""

TIMEZONE = "Asia/Jerusalem"
"""Where the course is. Timestamps stay UTC; this names the reading."""

UNKNOWN = "unknown"
"""What the reference writes for a fact the reporting peer cannot have."""


def links(game_id: str) -> dict[str, str]:
    """The four artefact names, derived from ``game_id`` as the reference requires.

    ``config`` and ``log`` keep the literal ``<NN>`` placeholder: they name one
    file per sub-game, so a single name would be a lie about a series.
    """
    return {
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


def _outcome(sub: "SubGameResult") -> str:
    """How the sub-game ended, in the reference's vocabulary."""
    if sub.technical_loss:
        return Outcome.TECHNICAL_LOSS.value
    return Outcome.CAPTURE.value if sub.cop_score > sub.thief_score else Outcome.SURVIVAL.value


def _by_group(
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
        "github_commit": {us: sub.commit_hash, them: UNKNOWN},
        "tokens": {us: sub.tokens, them: 0},
        "score": {us: our_score, them: their_score},
        "log_files": dict.fromkeys((us, them), log_filename(game_id, sub.sub_game)),
        "audit": {"log_verified": sub.log_verified, "tampered": sub.tampered},
        "steps": sub.steps,
    }


def result_document(report: "Report") -> dict[str, Any]:
    """The whole result, as the reference lays it out."""
    us, them = report.team, report.opponent_team
    natural = report.starting_role or report.role
    standing = report.series_result or {}
    subs = [_by_group(sub, us, them, natural, report.game_id) for sub in report.sub_games]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "final_game_result",
        "game_id": report.game_id,
        "game_uid": report.game_uid,
        "links": links(report.game_id),
        "timezone": TIMEZONE,
        "groups": [us, them],
        "num_sub_games": len(report.sub_games),
        "sub_games": subs,
        "final_result": {
            "total_score": standing.get("total_score", {}),
            "sub_games_won": standing.get("sub_games_won", {}),
            "ties": standing.get("ties", 0),
            "winner_group": standing.get("winner_group"),
            "series_tie": standing.get("series_tie", False),
            "tokens_total_series": {us: report.total_tokens, them: 0},
        },
        "mutual_agreement": {"sha256": report.result_claim_sha256, "confirmed": report.agreed},
        "repositories": report.repositories.to_dict(),
        "started_at": report.started_at,
        "ended_at": report.ended_at,
        "reported_by": {"role": report.role, "team": us},
        "machine": report.machine,
        "mcp_addresses": report.mcp_addresses,
        "signature": report.signature,
    }
