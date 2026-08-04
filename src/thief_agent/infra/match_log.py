"""The match log: what happened, in the order it happened, never rewritten.

``log_<game_id>_g<NN>.json`` is the file the Replay App re-verifies and the
file the two teams audit against each other. It is the only durable record that
a step was committed *before* it was revealed, which is the claim the whole
ceremony rests on — and a claim nobody can check from a file that could have
been assembled afterwards.

**Append-only is the property, and it is enforced rather than intended.** Each
step has three slots — commitment, reveal, nonce — filled in that order and
never twice. A log that permitted an overwrite would be exactly as convincing
as no log at all: an auditor cannot distinguish "written honestly as it
happened" from "written honestly at the end", and the second one is what a
cheat produces.

The slots fill at different times on purpose. The commitment is known before
the move goes out, the reveal a phase later, and the nonce only once the whole
match is over. A log entry with a nonce in it while the match is running is a
bug that has already leaked the thing the nonce exists to hide.

Written whole, sorted by step, so two peers with identical histories produce
identical bytes. The audit compares content, not files, but a diff that is
noise-free is a diff two tired people can read at midnight after a match.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.actions import ROLES
from ..shared.naming import log_filename

SLOTS = ("commit", "reveal", "nonce")
"""The three things recorded per step, in the only order they may arrive."""


class MatchLogError(ValueError):
    """Raised on any attempt to write a slot that is already written."""


@dataclass
class StepEntry:
    """One step's row. Each field is write-once."""

    step: int
    commit: str | None = None
    reveal: dict[str, Any] | None = None
    nonce: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "commit": self.commit,
            "reveal": self.reveal,
            "nonce": self.nonce,
        }


@dataclass
class MatchLog:
    """Every step of one sub-game, append-only."""

    game_id: str
    sub_game: int
    role: str
    entries: dict[int, StepEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise MatchLogError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")
        log_filename(self.game_id, self.sub_game)  # validates both, raising NamingError

    def _slot(self, step: int, name: str) -> StepEntry:
        entry = self.entries.setdefault(step, StepEntry(step=step))
        if getattr(entry, name) is not None:
            raise MatchLogError(
                f"step {step} already has a {name}; this log is append-only, and a log "
                "that permitted an overwrite would be as convincing as no log at all"
            )
        return entry

    def commit(self, step: int, digest: str) -> None:
        """Record a commitment, before the move goes out."""
        self._slot(step, "commit").commit = digest

    def reveal(self, step: int, opened: dict[str, Any]) -> None:
        """Record a disclosure.

        Raises:
            MatchLogError: if the step was never committed. A reveal with no
                commitment before it is the exact shape of a move decided after
                seeing the opponent's, and the ordering here is the only place
                the file can show it did not happen.
        """
        entry = self._slot(step, "reveal")
        if entry.commit is None:
            raise MatchLogError(
                f"step {step} revealed with no commitment recorded; the order is the "
                "evidence, and a reveal that precedes its commitment proves nothing"
            )
        entry.reveal = opened

    def disclose(self, step: int, nonce: str) -> None:
        """Record a nonce, once the match is over.

        Raises:
            MatchLogError: if the step has not been revealed. A nonce recorded
                against an unrevealed step opens a commitment nobody has seen
                the contents of yet.
        """
        entry = self._slot(step, "nonce")
        if entry.reveal is None:
            raise MatchLogError(
                f"step {step} has no reveal to open; a nonce recorded here would open a "
                "commitment whose contents nobody has seen"
            )
        entry.nonce = nonce

    def unopened(self) -> list[int]:
        """Steps with no nonce yet. Empty is the only acceptable end state."""
        return sorted(step for step, entry in self.entries.items() if entry.nonce is None)

    def to_dict(self) -> dict[str, Any]:
        """The file's contents, sorted by step so identical histories agree."""
        return {
            "game_id": self.game_id,
            "sub_game": self.sub_game,
            "role": self.role,
            "steps": [self.entries[step].to_dict() for step in sorted(self.entries)],
        }

    def write(self, directory: Path) -> Path:
        """Write ``log_<game_id>_g<NN>.json``, creating the directory if needed."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / log_filename(self.game_id, self.sub_game)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return path
