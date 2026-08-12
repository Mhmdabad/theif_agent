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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.naming import log_filename
from .match_log_entry import SLOTS, Completeness, MatchLogError, StepEntry
from .match_log_slots import LogSlots

__all__ = ["SLOTS", "Completeness", "MatchLog", "MatchLogError", "StepEntry"]


@dataclass
class MatchLog(LogSlots):
    """Every step of one sub-game, append-only."""

    def unopened(self) -> list[int]:
        """Steps with no nonce yet. Empty is the only acceptable end state."""
        return sorted(step for step, entry in self.entries.items() if entry.nonce is None)

    def verifiable(self) -> "Completeness":
        """Whether a third party could fully re-verify this sub-game from this file.

        The question the rulebook actually asks of a log, and it is not the same
        as "was it written correctly". A log can be perfectly well-formed and
        still leave an auditor unable to finish: without ``config_sha256`` they
        cannot say which physics applied, without ``game_uid`` they cannot tie
        it to the declaration, and without every nonce they cannot open every
        commitment.

        Reported rather than raised. A mid-match log is legitimately incomplete,
        and refusing to describe it would make this useless at exactly the
        moment somebody wants to know how far along it is.
        """
        missing: list[str] = []
        if not self.game_uid:
            missing.append("game_uid (nothing ties this log to the declaration)")
        if not self.config_sha256:
            missing.append("config_sha256 (nobody can say which physics applied)")
        if not self.entries:
            missing.append("steps (a log of nothing verifies nothing)")
        unopened = self.unopened()
        if unopened:
            missing.append(f"nonces for steps {unopened}")
        unrevealed = sorted(step for step, entry in self.entries.items() if entry.reveal is None)
        if unrevealed:
            missing.append(f"reveals for steps {unrevealed}")
        return Completeness(tuple(missing))

    def to_dict(self) -> dict[str, Any]:
        """The file's contents, sorted by step so identical histories agree."""
        return {
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "sub_game": self.sub_game,
            "role": self.role,
            "config_sha256": self.config_sha256,
            "steps": [self.entries[step].to_dict() for step in sorted(self.entries)],
        }

    def write(self, directory: Path) -> Path:
        """Write ``log_<game_id>_g<NN>.json``, creating the directory if needed."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / log_filename(self.game_id, self.sub_game)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        return path
