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
"""The three things recorded per step, in the only order they may arrive.

``discussion`` is a fourth slot but not one of these: it is written alongside
the reveal rather than in sequence with it, and it is **not covered by the
commitment**. Keeping it out of ``SLOTS`` is what stops it being treated as
evidence — see :meth:`MatchLog.discuss`.
"""


class MatchLogError(ValueError):
    """Raised on any attempt to write a slot that is already written."""


@dataclass(frozen=True, slots=True)
class Completeness:
    """Whether a log can be fully re-verified, and what is absent if not."""

    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing

    def __str__(self) -> str:
        if self.complete:
            return "a third party can fully re-verify this sub-game"
        return "cannot be fully re-verified without " + "; ".join(self.missing)


@dataclass
class StepEntry:
    """One step's row. Each field is write-once."""

    step: int
    commit: str | None = None
    reveal: dict[str, Any] | None = None
    nonce: str | None = None
    discussion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "commit": self.commit,
            "reveal": self.reveal,
            "nonce": self.nonce,
            "discussion": self.discussion,
        }


@dataclass
class MatchLog:
    """Every step of one sub-game, append-only."""

    game_id: str
    sub_game: int
    role: str
    game_uid: str = ""
    config_sha256: str = ""
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

    def reveal(self, step: int, sealed: dict[str, Any]) -> None:
        """Record the **sealed record** — what the commitment was taken over.

        Not the wire ``Reveal``. Those are different objects: the message
        carries ``sender``, ``step`` and ``timestamp``, while the commitment
        was computed over ``state``, ``role``, ``move``, ``intent``, ``hint``
        and ``barrier_placed``. Storing the message would produce a log that
        **cannot verify itself** — the Replay App would recompute a digest from
        fields that were never hashed and report every honest step as tampered.

        The log is the audit artefact, so what it stores has to be the thing
        the digest is about.

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
        entry.reveal = sealed

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

    def discuss(self, step: int, fields: dict[str, Any]) -> None:
        """Record the LLM discussion fields for a step. Write-once, like the rest.

        **Not covered by the commitment, and deliberately so.** What we said to
        our own model is not something the opponent can check, and sealing an
        unverifiable value would let a team write anything here afterwards and
        point at a digest that never described it. The rulebook asks for these
        fields because they show *how* a decision was reached; they are context
        for a reader, not evidence for an auditor, and the log should not blur
        the two.

        Raises:
            MatchLogError: if the step has no commitment yet. Discussion
                recorded before a commitment is a note about a move that had
                not been fixed, which is the ordering the log exists to refute.
        """
        entry = self._slot(step, "discussion")
        if entry.commit is None:
            raise MatchLogError(
                f"step {step} has discussion recorded before any commitment; the order "
                "is the evidence, and reasoning that precedes a sealed move proves nothing"
            )
        entry.discussion = fields

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
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return path
