"""Loading and validating the shared game configuration.

The shared ``game.json`` is the constitution both peers sign. It is loaded
byte-identically on each side and its SHA-256 is exchanged before the first
move; any mismatch means refuse to play.
"""

import hashlib
import hmac
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


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """The one canonical form. Every digest in this system is taken over it.

    The config digest, the scent lock, the step commitments and the transport
    payload freeze all hash through here. One implementation rather than
    several, because two canonical forms that disagree is the same defect as
    none: both sides serialise "canonically", both get different bytes, and the
    audit calls an honest match tampered.

    Three settings, and the third is the one that bites:

    ``sort_keys=True``
        Key order is an accident of construction and must not reach the digest.

    ``separators=(",", ":")``
        No incidental whitespace.

    ``ensure_ascii`` left at its default of **True**
        Non-ASCII is escaped to ``\\uXXXX``, so the output is pure ASCII
        whatever went in. This looks like the setting to turn off — raw UTF-8
        reads better and is just as deterministic *on its own*. It is the wrong
        call here, because determinism alone is not the requirement:
        interoperability is. The rulebook's own ``commit()`` leaves the default
        (p. 37), so an opponent running that code escapes where we would not,
        and the first hint carrying a non-ASCII character produces two
        different digests from two honest peers — a ``TAMPERED`` verdict, no
        appeal, zero for both sides. Hints are free natural language, so that
        character will arrive eventually.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def config_sha256(config: dict[str, Any]) -> str:
    """The digest exchanged before the first move."""
    return hashlib.sha256(canonical_bytes(config)).hexdigest()


def digests_agree(ours: str, theirs: str) -> bool:
    """Whether two peers are playing by the same parameters.

    Constant-time, via :func:`hmac.compare_digest`. Not because a config digest
    is a secret — both sides publish theirs — but because ``==`` on strings
    stops at the first differing byte, and the time it takes therefore says how
    long a common prefix was. An opponent free to re-negotiate could use that to
    walk a digest out of us one character at a time and then claim our
    parameters as its own. The comparison costs nothing either way, and the
    version that leaks is the one that has to be justified.

    Compared as bytes rather than as ``str``: ``compare_digest`` raises
    ``TypeError`` on a non-ASCII string, and an unhandled exception on a path an
    opponent can reach is a technical loss scoring zero for both sides.
    """
    return hmac.compare_digest(ours.encode("utf-8"), theirs.encode("utf-8"))


def load(path: Path) -> dict[str, Any]:
    """Read and validate a shared configuration file."""
    config: dict[str, Any] = json.loads(path.read_text())
    validate(config)
    return config
