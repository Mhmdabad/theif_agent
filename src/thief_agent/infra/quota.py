"""Gate one of the Gatekeeper: how many sends today, and the day's hard ceiling.

FR-7.18 calls this the **last line of defence against account suspension**. The
threat it answers is stated plainly in the rulebook: automation hands code — which
may contain a bug — the key to a live mail account, and the question is what
happens when an infinite loop starts firing thousands of messages a minute.

Two design decisions follow directly from that threat, and both are the opposite
of what the obvious implementation does.

**The count is on disk, not in memory.** A counter held in a process is defeated
by the precise failure it exists to stop. A bug that sends and then crashes takes
the counter with it; systemd, a shell loop or an impatient human restarts the
agent, and the fresh process believes nothing has been sent today. The loop is
unbounded and the quota manager watched it happen. Only a count that outlives the
process is a count at all.

**Reservation happens before the send, never after.** Recording a send once it
succeeds sounds tidier and is exactly wrong: a send that goes out and then fails
— a timeout after delivery, a crash between the API call and the write — is
uncounted but not unsent. Under a crash loop every attempt is uncounted, and the
ceiling is never reached no matter how much mail leaves. So a slot is taken
first; if the send then fails, we have overcounted by one, which costs at worst a
single report and cannot cost the account.

**A ledger that cannot be read fails closed.** If we cannot say how many sends
happened today, we cannot say we are under the ceiling, and the whole point of a
last line of defence is that it does not yield to uncertainty. Corruption would
otherwise be a bypass: damage the file, get an unlimited day. Clearing it is a
deliberate human act — :func:`reset` — rather than something the failure path
does for itself.

The day boundary is UTC, so it does not move with the machine's timezone or with
daylight saving. A ceiling that shifts by an hour twice a year is a ceiling that
is wrong twice a year.
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DAILY_LIMIT = 50
"""Sends permitted per UTC day.

Not an Appendix F parameter — the rulebook names a daily safety threshold
without fixing a number, so this is ours to choose and to justify.

One legal match produces one report (FR-7.15), and the league caps a team at
``max_games_per_team`` = 10 games. Fifty leaves room for re-runs, both agents on
one account, and a day of testing, while sitting far below any limit Google
enforces — the free-tier ceiling on recipients per day is an order of magnitude
higher. The number is deliberately closer to *our* expected volume than to
Google's limit: a threshold set just under the provider's does not protect
anything, because by the time it trips the damage is already interesting.
"""

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


@dataclass
class Quota:
    """The daily ceiling, counted on disk."""

    path: Path
    limit: int = DAILY_LIMIT
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def today(self) -> str:
        return self.now().astimezone(UTC).date().isoformat()

    def _read(self) -> DayCount:
        """Read the ledger, treating an unreadable one as an error rather than zero.

        Raises:
            QuotaError: if the file exists but cannot be parsed. A missing file
                is a first run and counts as zero; a *damaged* file is a count
                we do not have, and guessing zero would make corruption the way
                to get an unlimited day.
        """
        today = self.today()
        try:
            body = json.loads(self.path.read_text())
        except FileNotFoundError:
            return DayCount(today, 0)
        except (OSError, json.JSONDecodeError) as exc:
            raise QuotaError(
                f"the quota ledger at {self.path} cannot be read ({exc}), so this agent "
                "cannot show it is under today's ceiling and will not send. Inspect it, "
                "then clear it deliberately with quota.reset() if the count is genuinely "
                "unknown"
            ) from exc

        if not isinstance(body, dict) or not isinstance(body.get("used"), int):
            raise QuotaError(
                f"the quota ledger at {self.path} is not a count ({body!r}); refusing to "
                "send rather than assume zero"
            )
        if body.get("day") != today:
            return DayCount(today, 0)
        return DayCount(today, int(body["used"]))

    def used(self) -> int:
        """Sends already taken today. Rolls over at UTC midnight."""
        return self._read().used

    def remaining(self) -> int:
        return max(self.limit - self.used(), 0)

    def check(self) -> None:
        """Raise if a send now would cross the ceiling, without taking a slot.

        Separate from :meth:`reserve` so a caller can report the state — a
        status line, a dry run — without spending anything.
        """
        used = self.used()
        if used >= self.limit:
            raise QuotaExhausted(
                f"{used} of {self.limit} sends used today ({self.today()} UTC); "
                "nothing further goes out until the day rolls over. This is the last "
                "line of defence against the account being suspended, so it does not "
                "yield to a retry"
            )

    def reserve(self, count: int = 1) -> int:
        """Take ``count`` slots **before** sending, and return the new total.

        Called before the API request, not after. A send that goes out and then
        fails is uncounted but not unsent, and under a crash loop that is every
        send. Overcounting by one costs a report; undercounting costs the
        account.

        Raises:
            QuotaExhausted: if the reservation would cross the ceiling. Nothing
                is written in that case, so a refused reservation does not burn
                the slot it was refused.
        """
        if count < 1:
            raise QuotaError(f"a reservation must be for at least one send, got {count}")
        current = self._read()
        if current.used + count > self.limit:
            raise QuotaExhausted(
                f"{current.used} of {self.limit} sends used today ({current.day} UTC); "
                f"a further {count} would cross the daily ceiling and nothing is sent"
            )
        taken = DayCount(current.day, current.used + count)
        self._write(taken)
        return taken.used

    def _write(self, count: DayCount) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w") as stream:
            json.dump(count.to_dict(), stream, sort_keys=True)
            stream.write("\n")

    def reset(self) -> None:
        """Clear the ledger. A deliberate act, never taken by a failure path."""
        self._write(DayCount(self.today(), 0))

    def status(self) -> str:
        """One line for an operator, safe to print."""
        try:
            used = self.used()
        except QuotaError:
            return f"quota unreadable at {self.path} — sending is blocked"
        return f"{used}/{self.limit} sends used on {self.today()} UTC"
