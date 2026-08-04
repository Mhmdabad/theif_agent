"""What the network did, in the order it did it.

When a match ends in a technical result there is no board to argue from — no
capture, no survival, just two peers who stopped agreeing. And a technical loss
scores **zero for both sides**, so the opponent has every reason to believe it
was our fault and none to take our word for it. Both teams must agree the
result before either may report it. This file is what that agreement is made
out of.

So the log records what actually happened on the wire rather than what the
runtime concluded: when we first reached an address, what we sent and its
digest, which attempts failed and with what error, when we backed off, when we
gave up, and when we moved to a new address. A line saying "timeout" is worth
little; a line saying *which* call timed out, against *which* URL, at *which*
attempt of four, and at what time, is a fact the other side can check against
their own log.

**It is the client's only record.** The digests that prove a retry re-sent an
identical payload, and the address history that shows where our traffic went,
are derived from these events rather than kept alongside them. Two records of
the same thing is one record that can be wrong without anyone noticing.

Timestamps are UTC and ISO 8601. Two peers in different timezones comparing
logs is the ordinary case, and "09:41" means nothing without knowing whose
morning it was.

Rendering is plain text, one event per line, because the audience is a person
reading it during a dispute. :meth:`TransportLog.to_dicts` exists for the
machine-readable report, so the human format never has to compromise.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONNECT = "connect"
"""First successful call against an address. Proof the tunnel was ever alive."""

SENT = "sent"
SENT_DETAIL = "sha256"

TIMEOUT = "timeout"
"""One attempt failed at the transport level. Not yet a match-ending event."""

RETRY = "retry"
UNREACHABLE = "unreachable"
"""The retry budget is spent. This is the line that becomes a technical loss."""

RECONNECT = "reconnect"
"""The address moved. A rotated tunnel, never a redirect we were handed."""

KINDS = (CONNECT, SENT, TIMEOUT, RETRY, UNREACHABLE, RECONNECT)


def now_utc() -> str:
    """ISO 8601 in UTC, to milliseconds.

    Milliseconds because a retry burst inside one second is exactly the shape
    of event this log exists to explain, and second resolution would render it
    as several things happening at once.
    """
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened on the wire."""

    at: str
    kind: str
    tool: str
    url: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}, got {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "kind": self.kind,
            "tool": self.tool,
            "url": self.url,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        line = f"{self.at}  {self.kind:<12} {self.tool or '-':<16} {self.url}"
        return f"{line}  {self.detail}" if self.detail else line


@dataclass
class TransportLog:
    """Every transport event of one match, oldest first."""

    events: list[Event] = field(default_factory=list)
    clock: Callable[[], str] = now_utc

    def record(self, kind: str, tool: str, url: str, detail: str = "") -> Event:
        """Append one event, timestamped now."""
        event = Event(self.clock(), kind, tool, url, detail)
        self.events.append(event)
        return event

    def of_kind(self, kind: str) -> list[Event]:
        return [event for event in self.events if event.kind == kind]

    @property
    def addresses(self) -> list[str]:
        """Every address we have talked to, in the order we adopted them."""
        seen: list[str] = []
        for event in self.events:
            if event.kind in (CONNECT, RECONNECT) and event.url not in seen:
                seen.append(event.url)
        return seen

    def summary(self) -> str:
        """One line per kind. What a person wants before reading 400 lines."""
        counts = {kind: len(self.of_kind(kind)) for kind in KINDS if self.of_kind(kind)}
        if not counts:
            return "no transport events recorded"
        return ", ".join(f"{kind} {count}" for kind, count in counts.items())

    def render(self) -> str:
        """The human-readable form, which is what the rulebook asks for."""
        if not self.events:
            return "no transport events recorded\n"
        body = "\n".join(str(event) for event in self.events)
        return f"{body}\n\n{self.summary()}\n"

    def to_dicts(self) -> list[dict[str, Any]]:
        """The machine-readable form, for the signed JSON report."""
        return [event.to_dict() for event in self.events]

    def write(self, path: Path) -> Path:
        """Write the human-readable log, creating the directory if needed.

        Written whole rather than appended to. A match's transport log is
        evidence about one match; appending across matches would make the file
        that proves a dispute the same file that has to be searched to find it.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render())
        return path
