"""Translating our configuration into the agreement both peers sign.

Appendix B gives the config schema; the cohort reference gives the *wire* shape
of the signed agreement, and the two use different key names for the same
values. Appendix D settles which wins on **values** — the book and Appendix F —
but says nothing about key names on the wire, and interoperability depends on
the wire.

So Appendix B stays our internal source of truth and Appendix F stays the
authority on values, and we translate at the negotiation boundary. Nothing is
weakened: the Appendix F validator still runs against our own config before
anything is translated.

Terms with **no default** fail rather than resolving to ``None``. The reference
takes the same position, and for the same reason: a ``None`` board size does not
announce itself at negotiation, it crashes mid-play — or worse, silently plays a
different game from the opponent.
"""

from typing import Any

from .appendix_f import book_int

REQUIRED_TERMS: tuple[str, ...] = (
    "board_size",
    "smell_grid_size",
    "decay_per_step",
    "emit_intensity",
    "min_center_intensity",
    "max_steps",
    "barriers_max",
    "thief_start",
    "cop_start",
)
"""Terms that must resolve. A missing one is a match that cannot start."""


class TermsError(ValueError):
    """Raised when the agreed terms cannot be built or read."""


def _dig(config: dict[str, Any], section: str, key: str) -> object:
    part = config.get(section)
    if not isinstance(part, dict) or key not in part:
        raise TermsError(f"config is missing {section}.{key}")
    return part[key]


def to_terms(config: dict[str, Any]) -> dict[str, Any]:
    """Build the signed agreement from our Appendix B configuration.

    Raises:
        TermsError: if a required term cannot be resolved.
    """
    board = config.get("board_and_agents", {})
    terms: dict[str, Any] = {
        "board_size": _dig(config, "board_and_agents", "grid_size"),
        "smell_grid_size": _dig(config, "pheromones", "pheromone_grid_size"),
        "decay_per_step": _dig(config, "pheromones", "pheromone_decay"),
        "emit_intensity": _dig(config, "pheromones", "pheromone_center_intensity"),
        "min_center_intensity": _dig(config, "pheromones", "pheromone_center_intensity"),
        "max_steps": _dig(config, "movement_and_barriers", "max_moves"),
        "barriers_max": _dig(config, "movement_and_barriers", "max_barriers"),
        "thief_start": _dig(config, "board_and_agents", "thief_start"),
        "cop_start": _dig(config, "board_and_agents", "cop_start"),
        "setting": config.get("world", {}).get("map_area", ""),
        "hint_max_words": config.get("world", {}).get("hint_max_words", 15),
        "axis_origin_corner": board.get("axis_origin_corner", "top-left"),
        "axis_start_index": board.get("axis_start_index", 0),
        # Appendix F table 18 row 1 is fixed at six, so the fallback is the book
        # value and not a demo-sized one. A term that quietly announces a series
        # of one to the opponent is a deviation they audit us on.
        "num_games": config.get("network_and_league", {}).get(
            "num_games", book_int("network_and_league", "num_games")
        ),
    }
    missing = [name for name in REQUIRED_TERMS if terms.get(name) is None]
    if missing:
        raise TermsError(f"required terms did not resolve: {sorted(missing)}")
    return terms


def check_required(terms: dict[str, Any]) -> None:
    """Verify an opponent's terms carry everything play depends on.

    Raises:
        TermsError: naming every missing term at once, so a mismatched
            opponent is told the whole problem in one message rather than
            discovering it one round trip at a time.
    """
    missing = [name for name in REQUIRED_TERMS if terms.get(name) is None]
    if missing:
        raise TermsError(f"agreement is missing required terms: {sorted(missing)}")
