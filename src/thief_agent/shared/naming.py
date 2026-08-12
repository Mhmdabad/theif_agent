"""Filenames for the four mandatory match artefacts.

All four share a ``game_uid`` and every name derives from ``game_id``, so files
from different matches can never be confused. With up to ten counted matches of
six sub-games each, that is up to sixty logs and configs in one repository —
naming discipline is what keeps the evidence trail auditable.

Appendix F, mandatory rule 4: **every match's config file must be committed to
the GitHub repository**, so any past match can be reconstructed exactly,
including the parameters negotiated with that particular opponent.
"""

import hashlib
import re
import uuid
from collections.abc import Mapping
from typing import Any, Final

from .config import canonical_bytes

GAME_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
"""Safe as a filename component: no separators, no traversal, non-empty."""

MAX_SUB_GAME: Final = 99
"""``<NN>`` is two digits, so a series cannot exceed 99 sub-games."""


class NamingError(ValueError):
    """Raised when a game id or sub-game number cannot form a valid filename."""


def _check_game_id(game_id: str) -> None:
    if not GAME_ID_PATTERN.match(game_id):
        raise NamingError(
            f"game_id {game_id!r} must be 1-64 chars of letters, digits, '-' or '_' "
            "and start alphanumeric; it becomes a filename component"
        )


def _check_sub_game(sub_game: int) -> None:
    if not 1 <= sub_game <= MAX_SUB_GAME:
        raise NamingError(f"sub_game must be 1..{MAX_SUB_GAME}, got {sub_game}")


def declaration_filename(game_id: str) -> str:
    """Pre-game declaration. One per match, not per sub-game."""
    _check_game_id(game_id)
    return f"declaration_{game_id}.json"


def config_filename(game_id: str, sub_game: int) -> str:
    """Agreed configuration for one sub-game. Committed to the repository."""
    _check_game_id(game_id)
    _check_sub_game(sub_game)
    return f"config_{game_id}_g{sub_game:02d}.json"


def log_filename(game_id: str, sub_game: int) -> str:
    """Step-by-step log for one sub-game, verified by the Replay App."""
    _check_game_id(game_id)
    _check_sub_game(sub_game)
    return f"log_{game_id}_g{sub_game:02d}.json"


def transport_log_filename(game_id: str, sub_game: int) -> str:
    """Wire-event log for one sub-game. Not one of the four mandatory files.

    Named alongside them anyway. It is the evidence a technical result is
    argued from, and evidence that cannot be matched to the sub-game it came
    from is evidence nobody can check.
    """
    _check_game_id(game_id)
    _check_sub_game(sub_game)
    return f"transport_{game_id}_g{sub_game:02d}.log"


def result_filename(game_id: str) -> str:
    """Final results report. One per match; this is what is emailed."""
    _check_game_id(game_id)
    return f"result_{game_id}.json"


def game_id_for(group_a: str, group_b: str) -> str:
    """The match id both peers derive, from the two group ids alone.

    ``"-vs-".join(sorted([a, b]))``. **Sorted**, so each side computes the same
    string with no round trip and no convention to settle. A peer naming itself
    first produces a different id on each side, and one match then yields two
    sets of artefact filenames that cannot be joined by ``game_id`` at all.
    """
    return "-vs-".join(sorted([group_a, group_b]))


def game_uid(terms: Mapping[str, Any], group_a: str, group_b: str) -> str:
    """The match's UUID, derived from the agreed terms and the two group ids.

    ``UUID(SHA256(canonical(terms) + "|" + "|".join(sorted([a, b])))[:16])``.

    Both peers must hold the same uid -- it binds the commitments, the turns and
    the agreed result -- and nothing in the protocol exchanges it. Deriving it
    from the terms they already agreed byte-for-byte solves that without a round
    trip, and says something a name cannot: this uid is *about these terms*, so
    a uid agreed for one series cannot be replayed to open another played under
    different ones.

    The cohort's interop kit defines it this way, which is the reason to prefer
    it over a hash of ``game_id``: a uid only we compute is not a shared one.
    """
    pair = sorted([group_a, group_b])
    seed = f"{canonical_bytes(dict(terms)).decode('utf-8')}|{'|'.join(pair)}"
    return str(uuid.UUID(bytes=hashlib.sha256(seed.encode("utf-8")).digest()[:16]))
