"""How many league games this agent has already played, and against whom.

Appendix E rule 37 requires each match to open with a declaration of the exact
number of games already played, and rule 38 makes a false count a breach rather
than a slip. The declaration had every other fact about this peer — hardware,
commit, model, token ceiling — and no games-played field at all, so the count
was a rule with nothing behind it.

**It lives in ``artefacts/`` on purpose.** The obvious place for a counter is a
dotfile beside the quota and the DOS lock, which are per-machine safety state
nobody audits. This is the opposite: it is a claim about our record that another
team is entitled to check, and the check is simple when the ledger sits next to
the evidence — one entry per committed ``declaration_<game_id>.json``. A count
that disagrees with the artefacts around it is visible to anybody who looks,
which is the only thing that makes rule 38 more than an honour system.

**Rehearsals are not games.** Rule 52 allows warm-ups and counts one game per
opponent, so only real matches against another team are recorded. Recording a
loopback rehearsal would inflate the count with games nobody played, which is
the false declaration rule 38 names, arrived at by carelessness rather than
intent.

Appending is idempotent per game: a match re-run under the same ``game_id``
against the same opponent replaces its entry rather than counting twice, because
a series that crashed and was replayed is one game and the artefacts will show
one.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["LEDGER_FILE", "MatchLedger", "Entry"]

LEDGER_FILE = "match_ledger.json"
"""Beside the artefacts it can be checked against, not in a hidden dotfile."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One league game that was actually played, and when it ended."""

    game_id: str
    opponent: str
    ended_at: str

    def to_dict(self) -> dict[str, str]:
        return {"game_id": self.game_id, "opponent": self.opponent, "ended_at": self.ended_at}


@dataclass(frozen=True, slots=True)
class MatchLedger:
    """The league games behind us, read from and written to one file."""

    directory: Path

    @property
    def path(self) -> Path:
        return self.directory / LEDGER_FILE

    def entries(self) -> tuple[Entry, ...]:
        """Every game recorded so far. An unreadable ledger is an empty one.

        A missing file means no games, which is the truth on a fresh clone. A
        *corrupt* file is treated the same way rather than raising, because the
        alternative is an agent that cannot open a match at all — and declaring
        zero is both the honest reading of an unreadable record and the count
        that understates rather than inflates.
        """
        try:
            body = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(body, list):
            return ()
        return tuple(
            Entry(
                game_id=str(item.get("game_id", "")),
                opponent=str(item.get("opponent", "")),
                ended_at=str(item.get("ended_at", "")),
            )
            for item in body
            if isinstance(item, dict)
        )

    def played(self) -> int:
        """The number rule 37 asks for: games already played, before this one."""
        return len(self.entries())

    def opponents(self) -> tuple[str, ...]:
        """Distinct teams faced, in the order first met.

        Rule 31 counts games against *different* teams and rule 52 counts one
        per opponent, so the list matters as much as the total.
        """
        seen: list[str] = []
        for entry in self.entries():
            if entry.opponent and entry.opponent not in seen:
                seen.append(entry.opponent)
        return tuple(seen)

    def record(self, game_id: str, opponent: str, ended_at: str) -> tuple[Entry, ...]:
        """Add this game to the record, replacing any earlier run of the same one."""
        kept = [entry for entry in self.entries() if entry.game_id != game_id]
        kept.append(Entry(game_id=game_id, opponent=opponent, ended_at=ended_at))
        self.directory.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = [entry.to_dict() for entry in kept]
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return tuple(kept)
