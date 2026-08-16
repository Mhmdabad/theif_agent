"""The consensus scope: what both teams hash to agree a result.

The book leaves the preimage open, and the wrong choice can *never* match --
two conformant teams computing different scopes produce different digests and
fail settlement at the exact moment they must agree. The cohort settled this
one live, and it is the reference's own ``symmetric_outcome``:

    { game_id, aggregate, sub_games: [ trimmed rows ] }

**Everything two honest teams must agree on, and nothing they may legitimately
differ on.** A whole-body scope is per-side *by construction* -- each carries
its own timestamps, its own token counts, its own commit -- so hashing the
report itself can never produce equal digests. That is what our old claim did.

**Five keys per row, not six.** ``tie`` belongs in the document and not in the
preimage: the cohort's own convention carried it for nine days, and every hash
ever settled live reproduces only under the five. ``tie`` is derivable from
``winner_group`` being null, and the tie *count* already sits in the aggregate.
"""

from typing import Any

__all__ = ["AGGREGATE_KEYS", "ROW_KEYS", "consensus_scope"]

AGGREGATE_KEYS = ("total_score", "sub_games_won", "ties", "winner_group", "series_tie")
"""The aggregate, in the cohort's order-independent set."""

ROW_KEYS = ("sub_game_number", "roles", "result", "winner_group", "score")
"""One row of the preimage. Five, and ``tie`` is deliberately not among them."""


def consensus_scope(
    game_id: str, standing: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """The agreeable part of a result, in the shape every conformant team hashes.

    ``rows`` are the result document's own sub-game entries, trimmed here rather
    than rebuilt: a second construction of the same facts is a second thing that
    can disagree with the first, and this one is compared against a stranger's.
    """
    return {
        "game_id": game_id,
        "aggregate": {key: standing.get(key) for key in AGGREGATE_KEYS},
        "sub_games": [{key: row.get(key) for key in ROW_KEYS} for row in rows],
    }
