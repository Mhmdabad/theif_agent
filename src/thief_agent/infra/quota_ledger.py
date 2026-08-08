"""The quota ledger on disk: where it lives, what a day's count is, and how it is read.

Split out of :mod:`.quota` so the ceiling policy — the limit, the refusal, the day
boundary — reads separately from the storage that backs it. Nothing here decides
whether a send may go out; this module only reports what the file on disk says, and
refuses to guess when that file cannot be trusted. Both exception types are defined
here, beside the read that raises the first of them.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

QUOTA_PATH_ENV = "GMAIL_QUOTA_PATH"
"""Explicit location for the ledger, mainly so tests never touch a real one."""


class QuotaError(RuntimeError):
    """Raised when a send must not proceed, or when the ledger cannot be trusted."""


class QuotaExhausted(QuotaError):
    """Raised when today's ceiling has been reached. Not retryable today."""


def quota_path(package: str, environ: "dict[str, str] | None" = None) -> Path:
    """Where this agent's ledger lives. Per agent, like the token."""
    chosen = (environ if environ is not None else dict(os.environ)).get(QUOTA_PATH_ENV)
    return Path(chosen) if chosen else Path(f".quota_{package.split('_')[0]}.json")


@dataclass(frozen=True, slots=True)
class DayCount:
    """What the ledger says about one UTC day."""

    day: str
    used: int

    def to_dict(self) -> dict[str, object]:
        return {"day": self.day, "used": self.used}


def read_day_count(path: Path, today: str) -> DayCount:
    """Read the ledger, treating an unreadable one as an error rather than zero.

    Raises:
        QuotaError: if the file exists but cannot be parsed. A missing file
            is a first run and counts as zero; a *damaged* file is a count
            we do not have, and guessing zero would make corruption the way
            to get an unlimited day.
    """
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return DayCount(today, 0)
    except (OSError, json.JSONDecodeError) as exc:
        raise QuotaError(
            f"the quota ledger at {path} cannot be read ({exc}), so this agent "
            "cannot show it is under today's ceiling and will not send. Inspect it, "
            "then clear it deliberately with quota.reset() if the count is genuinely "
            "unknown"
        ) from exc

    if not isinstance(body, dict) or not isinstance(body.get("used"), int):
        raise QuotaError(
            f"the quota ledger at {path} is not a count ({body!r}); refusing to "
            "send rather than assume zero"
        )
    if body.get("day") != today:
        return DayCount(today, 0)
    return DayCount(today, int(body["used"]))


def write_day_count(path: Path, count: DayCount) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as stream:
        json.dump(count.to_dict(), stream, sort_keys=True)
        stream.write("\n")
