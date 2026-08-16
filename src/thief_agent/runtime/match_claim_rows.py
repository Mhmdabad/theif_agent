"""The rows both teams hash to agree a result.

Built by the same function the result document uses, so the rows offered before
play settles and the rows published afterwards cannot describe different games.
A second construction of the same facts is a second thing that can disagree
with the first -- and this one is compared against a stranger's.
"""

from typing import TYPE_CHECKING, Any

from ..domain.alternation import opposite
from ..infra.report_reference import UNKNOWN, by_group
from .match_scored import scored

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from .match import MatchRunner

__all__ = ["claim_rows", "groups_for_claim"]


def claim_rows(runner: "MatchRunner", ours: str, theirs: str) -> list[dict[str, Any]]:
    """Every played sub-game as a consensus row, keyed by group.

    The commit is the declaration's own. The agreed scope trims that column
    away, so its value never reaches the digest -- but an empty one would fail
    FR-7.28's check on the way in, and inventing a placeholder to get past a
    check is how a placeholder ends up somewhere it matters.
    """
    commit = runner.declaration.provenance.github_commit or UNKNOWN
    return [
        by_group(scored(o, commit), ours, theirs, runner.role, runner.game_id)
        for o in runner.outcomes
    ]


def groups_for_claim(runner: "MatchRunner") -> tuple[str, str]:
    """The two group ids the claim is keyed by, as the standing keys them.

    Read from the greeting rather than the private config, and suffixed on a
    collision, for the reasons ``series_result`` gives -- the two must agree,
    or the aggregate and the rows would name different pairs and no digest
    either produced could match the other side's.
    """
    ours, theirs = runner.declaration.us.name, runner.declaration.them.name
    if runner.peering is not None:
        ours = runner.peering.ours.group_id or ours
        theirs = runner.peering.theirs.group_id or theirs
    if ours == theirs:
        ours, theirs = f"{ours}-{runner.role}", f"{theirs}-{opposite(runner.role)}"
    return ours, theirs
