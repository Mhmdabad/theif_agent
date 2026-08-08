"""The address book as the declaration records it, and the merge that writes it."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.naming import declaration_filename
from .handshake_greeting import Greeting, HandshakeError
from .handshake_peering import Peering
from .protocol import ROLES
from .validation import require_mapping

ADDRESS_KEY = "mcp_addresses"
"""Where addresses live in the declaration. One key, so merging is unambiguous."""


@dataclass
class AddressBook:
    """Both peers' MCP addresses, in the shape the declaration records them."""

    entries: dict[str, dict[str, Any]]

    @classmethod
    def of(cls, ours: Greeting, theirs: Greeting, sub_game: int = 1) -> "AddressBook":
        """Build from a checked pair. Keyed by role, which is unique by :func:`check`.

        ``since_sub_game`` is recorded so the declaration says *when* an address
        took effect. Without it a rotated series looks, at audit, exactly like
        one that used the final address from the start.
        """
        return cls(
            {
                g.role: {**g.to_dict(), "reachable": g.reachable, "since_sub_game": sub_game}
                for g in (ours, theirs)
            }
        )

    @classmethod
    def peered(cls, peering: "Peering") -> "AddressBook":
        """Build from a :class:`Peering`, carrying its sub-game number through."""
        return cls.of(peering.ours, peering.theirs, peering.sub_game)

    @property
    def complete(self) -> bool:
        """Whether both roles are present. A one-sided book is not a match."""
        return set(self.entries) == set(ROLES)

    def to_fragment(self) -> dict[str, Any]:
        """The declaration entry this stage contributes."""
        return {ADDRESS_KEY: {role: dict(entry) for role, entry in sorted(self.entries.items())}}


def record(directory: Path, game_id: str, book: AddressBook) -> Path:
    """Merge the addresses into ``declaration_<game_id>.json``.

    Merged rather than written, because the declaration accumulates across
    stages: hardware statements, the model in use and the token ceiling arrive
    later, and a stage that rewrote the file would drop them without a trace.

    Raises:
        HandshakeError: if the book is one-sided. A declaration naming a single
            peer is evidence of nothing.
    """
    if not book.complete:
        raise HandshakeError(
            f"declaration needs both roles, have {sorted(book.entries)}; "
            "a one-sided address record proves nothing at audit"
        )
    path = directory / declaration_filename(game_id)
    existing: dict[str, Any] = {}
    if path.exists():
        loaded = json.loads(path.read_text())
        existing = require_mapping(loaded, "declaration")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**existing, **book.to_fragment()}, indent=2, sort_keys=True) + "\n")
    return path
