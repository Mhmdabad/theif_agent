"""Loading and validating the shared game configuration.

The shared ``game.json`` is the constitution both peers sign. It is loaded
byte-identically on each side and its SHA-256 is exchanged before the first
move; any mismatch means refuse to play.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from .appendix_f import TABLE, Param, Status


class ConfigError(ValueError):
    """Raised when a configuration violates Appendix F."""


def _violation(param: Param, actual: object) -> str | None:
    if param.status is Status.FIXED and actual != param.book_value:
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


def canonical_bytes(config: dict[str, Any]) -> bytes:
    """Serialise canonically, so both peers hash identical bytes."""
    return json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")


def config_sha256(config: dict[str, Any]) -> str:
    """The digest exchanged before the first move."""
    return hashlib.sha256(canonical_bytes(config)).hexdigest()


def load(path: Path) -> dict[str, Any]:
    """Read and validate a shared configuration file."""
    config: dict[str, Any] = json.loads(path.read_text())
    validate(config)
    return config
