"""The write-once half of a match log: the three slots, filled in order.

Split out of :mod:`.match_log` for length only. :class:`LogSlots` carries
the fields and the append-only writers; ``MatchLog`` inherits them and adds
the reading and writing of the file itself.
"""

from dataclasses import dataclass, field
from typing import Any

from ..domain.actions import ROLES
from ..shared.naming import log_filename
from .match_log_entry import MatchLogError, StepEntry


@dataclass
class LogSlots:
    """One sub-game's rows and the only writers allowed to fill them."""

    game_id: str
    sub_game: int
    role: str
    game_uid: str = ""
    config_sha256: str = ""
    entries: dict[int, StepEntry] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    """The sub-game's outcome, filled by the runner once the series settles."""

    settlement: dict[str, Any] = field(default_factory=dict)
    """``mutual_agreement``, likewise: no sub-game settles itself."""

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
