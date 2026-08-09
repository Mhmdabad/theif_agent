"""Reading the two files a run cannot start without.

The private per-peer TOML is ours alone; the shared JSON is the one both peers
sign. Both are read before a socket opens, because a missing file and a
deviating series length are cheapest to learn on our own terminal and most
expensive to learn at the opponent's audit.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

from .shared.config import load as load_shared
from .shared.config import series_length


class StartupError(RuntimeError):
    """Raised when this peer cannot honestly start."""


def load_private(path: Path) -> dict[str, Any]:
    """Read the private per-peer TOML, or say which file is missing."""
    try:
        body: dict[str, Any] = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise StartupError(
            f"no private config at {path}; it is committed to this repository, so a "
            "missing one means the command is being run from somewhere other than the "
            "repository root"
        ) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise StartupError(f"cannot read {path}: {exc}") from exc
    return body


def resolve_series_length(requested: int | None, path: Path) -> int:
    """How many sub-games this peer will play, from the file both peers sign.

    Read here — before the server thread, before the announcement, before any
    address reaches an opponent — because a series of the wrong length is not a
    badly played match, it is a disqualified one (Appendix F table 18 row 1,
    status *fixed*). The cheapest place to learn that is our own terminal, and
    the most expensive is the opponent's audit after six sub-games that were
    only ever going to be one.

    Args:
        requested: the value typed after ``--sub-games``, or ``None`` for the
            book length. Any other number is refused rather than honoured; the
            flag exists so that somebody who deviates on purpose is told the
            rule, not so that the deviation is available.

    Raises:
        StartupError: if the shared configuration cannot be read at all.
        ConfigError: if it deviates, or if ``requested`` does.
    """
    try:
        config = load_shared(path)
    except OSError as exc:
        raise StartupError(
            f"cannot read the shared configuration at {path}: {exc}; it is committed to "
            "this repository, so a missing one means the command is being run from "
            "somewhere other than the repository root"
        ) from exc
    except json.JSONDecodeError as exc:
        raise StartupError(f"{path} is not valid JSON: {exc}") from exc
    return series_length(config, requested)
