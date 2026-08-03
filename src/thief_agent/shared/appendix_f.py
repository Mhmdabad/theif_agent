"""The Appendix F parameter table and its three statuses.

Appendix F is the single source of truth for every quantitative value in the
project. Each parameter carries a status that decides what may be done to it:

``FIXED``
    May not change at all. **Deviating disqualifies the team.**
``MINIMUM``
    May be negotiated *upward* only — never below the book value.
``NEGOTIABLE``
    Any mutually agreed value.

Validation refuses rather than warns. A parameter violation is not detected
when it is written; it is detected at audit, by the opponent, after a match has
been played. Failing at load turns a disputed result into a config error before
move one.
"""

from enum import Enum
from typing import Any, Final, NamedTuple


class Status(Enum):
    FIXED = "fixed"
    MINIMUM = "minimum"
    NEGOTIABLE = "negotiable"


class Param(NamedTuple):
    """One row of the binding table."""

    section: str
    key: str
    book_value: Any
    status: Status


TABLE: tuple[Param, ...] = (
    # Table 13 - board, axes, start positions
    Param("board_and_agents", "grid_size", 7, Status.MINIMUM),
    Param("board_and_agents", "num_agents", 2, Status.FIXED),
    Param("board_and_agents", "axis_origin_corner", "top-left", Status.NEGOTIABLE),
    Param("board_and_agents", "axis_start_index", 0, Status.NEGOTIABLE),
    Param("board_and_agents", "thief_start", [3, 3], Status.NEGOTIABLE),
    Param("board_and_agents", "cop_start", [0, 0], Status.NEGOTIABLE),
    # Table 14 - world
    Param("world", "map_area", "New York", Status.NEGOTIABLE),
    Param("world", "hint_max_words", 15, Status.NEGOTIABLE),
    # Table 15 - movement and barriers
    Param("movement_and_barriers", "move_set", ["N", "S", "E", "W", "STAY"], Status.FIXED),
    Param("movement_and_barriers", "max_barriers", 14, Status.MINIMUM),
    Param("movement_and_barriers", "max_moves", 35, Status.MINIMUM),
    Param("movement_and_barriers", "survival_threshold", 35, Status.MINIMUM),
    # Table 17 - scoring
    Param("scoring", "capture_cop", 20, Status.FIXED),
    Param("scoring", "capture_thief", 5, Status.FIXED),
    Param("scoring", "survival_cop", 5, Status.FIXED),
    Param("scoring", "survival_thief", 10, Status.FIXED),
    Param("scoring", "tie_score", 2, Status.FIXED),
    Param("scoring", "technical_loss", 0, Status.FIXED),
    # Table 16 - pheromones
    Param("pheromones", "pheromone_center_intensity", 0.9, Status.FIXED),
    Param("pheromones", "pheromone_decay", 0.10, Status.FIXED),
    Param("pheromones", "pheromone_grid_size", 5, Status.FIXED),
    # Table 18 - network and league
    Param("network_and_league", "diversity_reward", 10, Status.FIXED),
    Param("network_and_league", "min_games_to_pass", 2, Status.FIXED),
    Param("network_and_league", "max_games_per_team", 10, Status.FIXED),
    Param("network_and_league", "token_budget_per_series", 200000, Status.NEGOTIABLE),
    Param("network_and_league", "response_timeout_sec", 30, Status.NEGOTIABLE),
    Param("network_and_league", "watchdog_timeout_sec", 60, Status.NEGOTIABLE),
    # Table 19 - rate limiter
    Param("rate_limiter_gatekeeper", "requests_per_minute", 30, Status.MINIMUM),
    Param("rate_limiter_gatekeeper", "concurrent_requests", 2, Status.MINIMUM),
    Param("rate_limiter_gatekeeper", "retry_backoff_sec", 5, Status.MINIMUM),
    Param("rate_limiter_gatekeeper", "max_retries", 3, Status.MINIMUM),
    Param("rate_limiter_gatekeeper", "queue_depth", 100, Status.MINIMUM),
)


_BY_KEY: Final = {(p.section, p.key): p for p in TABLE}


def book_value(section: str, key: str) -> object:
    """The Appendix F value for one parameter.

    Modules read their defaults through here rather than restating a number,
    so the table is authoritative for behaviour as well as for validation. A
    constant that merely agrees with the table today is a constant that can
    silently disagree tomorrow.
    """
    try:
        return _BY_KEY[(section, key)].book_value
    except KeyError:
        raise KeyError(f"{section}.{key} is not an Appendix F parameter") from None


def book_int(section: str, key: str) -> int:
    """The Appendix F value for a parameter that must be a whole number."""
    value = book_value(section, key)
    if not isinstance(value, int):
        raise TypeError(f"{section}.{key} is {type(value).__name__}, not int")
    return value
