"""Loading and validating the shared game configuration.

The shared ``game.json`` is the constitution both peers sign. It is loaded
byte-identically on each side and its SHA-256 is exchanged before the first
move; any mismatch means refuse to play.
"""

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Final

from .appendix_f import book_int
from .config_validation import ConfigError, validate

__all__ = [
    "SERIES_KEY",
    "SERIES_SECTION",
    "SHARED_CONFIG",
    "ConfigError",
    "canonical_bytes",
    "config_sha256",
    "digests_agree",
    "load",
    "series_length",
    "validate",
]

SHARED_CONFIG = Path("config/game.json")
"""Where the agreed configuration lives, relative to the repository root.

One constant rather than one per caller: two paths to the constitution is two
constitutions, and the second one is the one nobody validates.
"""

SERIES_SECTION: Final = "network_and_league"
SERIES_KEY: Final = "num_games"
"""Appendix F table 18 row 1 — how many sub-games one series against an opponent is."""


def series_length(config: dict[str, Any], requested: int | None = None) -> int:
    """How many sub-games one series against an opponent is.

    Appendix F table 18 row 1 fixes it at six, and a fixed parameter is the kind
    whose deviation disqualifies the team rather than merely losing a game. So
    the number is never a default written next to a flag or a loop: it is read
    back out of a *validated* configuration, which cannot hold any other value
    and still validate. That is why this returns the book value rather than the
    file's — after :func:`validate` they are the same number, and returning the
    book one makes a series of any other length unrepresentable.

    Args:
        requested: a length asked for from outside — a command-line flag, say —
            or ``None`` for "whatever the book says".

    Raises:
        ConfigError: if the configuration deviates anywhere, or if ``requested``
            is anything but the book length. Refused here, before a socket
            opens, rather than played out and found at the opponent's audit.
    """
    validate(config)
    length = book_int(SERIES_SECTION, SERIES_KEY)
    if requested is not None and requested != length:
        raise ConfigError(
            f"a series length of {requested} was asked for, but Appendix F table 18 row 1 "
            f"fixes a series at {length} sub-games; deviating from a fixed value "
            "disqualifies the team"
        )
    return length


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

    ``ensure_ascii=False``
        Non-ASCII stays native UTF-8 rather than escaping to ``\\uXXXX``.

        This is the one place the book is followed to the letter by *not*
        following it. Its ``commit()`` (PDF p. 37) passes ``sort_keys`` and
        ``separators`` and omits ``ensure_ascii``, so Python's default escapes —
        and this form used to match that. But the digest's whole purpose is that
        two independent implementations reproduce it, and the cohort's
        interop kit pins ``False``, as does the reference. A byte-exact rule
        only one team follows is not a canonical form.

        The cost of getting it wrong lands on hints, which are free natural
        language: one Hebrew place name, one emoji, one em-dash from a language
        model, and two honest peers compute two different digests and each
        concludes the other tampered. :func:`~..domain.crypto.commit_of` already
        pinned ``False`` for exactly that reason; this had stayed strict, which
        left one codebase holding two canonical forms — the defect this
        module's own first paragraph warns about.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


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
