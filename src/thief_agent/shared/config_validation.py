"""Checking a shared configuration against Appendix F.

Split out of :mod:`.config` because judging a configuration and hashing one are
two jobs: this module holds the Appendix F table's verdict — which files may be
played at all — while :mod:`.config` holds the canonical form every digest in
the system is taken over. The table is consulted here and nowhere else.
"""

from typing import Any

from .appendix_f import TABLE, Param, Status

__all__ = ["ConfigError", "validate"]


class ConfigError(ValueError):
    """Raised when a configuration violates Appendix F."""


def _wrong_type(actual: object, expected: object) -> bool:
    """Whether a value deviates in *type*, before its value is even compared.

    ``6.0 == 6`` and ``True == 1`` in Python, so equality alone lets a float or
    a boolean stand in for a fixed integer. That is not a pedantic distinction
    here: ``"num_games": true`` compares equal to nothing the book says, but
    ``range(1, True + 1)`` plays one sub-game, and a config that validates while
    the series runs short is exactly the deviation this module exists to catch —
    found at audit, by the opponent, after the match.

    Applied to fixed parameters only. A minimum is compared with ``<``, which
    already refuses the shapes it cannot order.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return not (isinstance(expected, bool) and isinstance(actual, bool))
    if isinstance(expected, int):
        return not isinstance(actual, int)
    if isinstance(expected, float):
        return not isinstance(actual, int | float)
    return not isinstance(actual, type(expected))


def _violation(param: Param, actual: object) -> str | None:
    if param.status is Status.FIXED and (
        _wrong_type(actual, param.book_value) or actual != param.book_value
    ):
        return (
            f"{param.section}.{param.key} = {actual!r} but Appendix F fixes "
            f"{param.book_value!r}; deviating from a fixed value disqualifies the team"
        )
    if (
        param.status is Status.MINIMUM
        and isinstance(actual, int | float)
        and isinstance(param.book_value, int | float)
        and actual < param.book_value
    ):
        return (
            f"{param.section}.{param.key} = {actual!r} is below the Appendix F "
            f"minimum {param.book_value!r}; minimums may be raised, never lowered"
        )
    return None


def validate(config: dict[str, Any]) -> None:
    """Check every parameter against Appendix F.

    Raises:
        ConfigError: listing every violation found, not merely the first, so a
            misconfigured file is fixed in one pass rather than several.
    """
    problems: list[str] = []
    for param in TABLE:
        section = config.get(param.section)
        if not isinstance(section, dict) or param.key not in section:
            problems.append(f"{param.section}.{param.key} is missing")
            continue
        problem = _violation(param, section[param.key])
        if problem:
            problems.append(problem)
    if problems:
        raise ConfigError("; ".join(problems))
