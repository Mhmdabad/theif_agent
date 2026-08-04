"""Trading addresses before the first move, and writing them down.

Two peers who have never met know one thing about each other: a URL. This
module is where that URL is exchanged, checked, and recorded in the pre-game
declaration — the file that fixes everything which does not change during a
match, so that afterwards there is no argument about who was supposed to be at
which address.

**Checking is the part that earns its keep.** :mod:`.tunnel` refuses to
*advertise* an address an opponent could not route to; this module refuses to
*accept* one. The asymmetry matters: a peer can only verify its own tunnel by
trusting itself, but the address it is handed is a claim by someone with no
obligation to be careful. A loopback URL accepted here means every call we make
goes to our own machine, the deadline expires, and the match ends in a
technical loss scoring **zero for both sides** — including the side that made
the mistake.

The rule for that check is not "always demand a public address". It is
symmetric, and it has to be: during local development both agents run on one
box against ``127.0.0.1``, which is explicitly permitted while coding. So the
condition is **we may not demand more reachability than we ourselves offer**.
A peer advertising a tunnel refuses a loopback opponent, because it genuinely
cannot reach one. A peer still on loopback accepts a loopback opponent, because
that is the local test loop working as intended — and if the opponent is public
while we are not, that is fine too: they can be reached, and our own exposure is
their problem to complain about, not ours to pre-empt.

The declaration is **merged, not overwritten**. It accumulates across stages —
hardware, model and token ceiling arrive later — and a stage that rewrote the
file wholesale would silently drop whatever a previous one had recorded.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..shared.naming import declaration_filename
from .protocol import ROLES
from .tunnel import NotPublicError, host_is_public, normalise
from .validation import InvalidPayloadError, require_mapping, require_str

ADDRESS_KEY = "mcp_addresses"
"""Where addresses live in the declaration. One key, so merging is unambiguous."""


class HandshakeError(ValueError):
    """Raised when the greeting we were sent cannot be played against."""


@dataclass(frozen=True, slots=True)
class Greeting:
    """What one peer tells the other before the series starts.

    Deliberately small. Everything here is fixed for the whole match and goes
    verbatim into the declaration; anything that varies per sub-game belongs in
    the negotiated configuration instead, where it is hashed and signed.
    """

    role: str
    group_id: str
    public_url: str
    protocol_version: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise HandshakeError(f"role must be one of {sorted(ROLES)}, got {self.role!r}")
        if not self.group_id.strip():
            raise HandshakeError("group_id must be set; it identifies the team in the declaration")
        try:
            object.__setattr__(self, "public_url", normalise(self.public_url))
        except NotPublicError as exc:
            raise HandshakeError(str(exc)) from exc

    @property
    def reachable(self) -> bool:
        """Whether this address could be routed to from another machine."""
        return host_is_public(urlparse(self.public_url).hostname or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "group_id": self.group_id,
            "public_url": self.public_url,
            "protocol_version": self.protocol_version,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Greeting":
        """Parse an inbound greeting.

        Raises:
            HandshakeError: on anything malformed. The opponent is untrusted
                from the first byte, and a greeting is the first byte.
        """
        try:
            body = require_mapping(data, "greeting")
            return cls(
                role=require_str(body, "role"),
                group_id=require_str(body, "group_id"),
                public_url=require_str(body, "public_url"),
                protocol_version=require_str(body, "protocol_version"),
            )
        except InvalidPayloadError as exc:
            raise HandshakeError(str(exc)) from exc


def check(ours: Greeting, theirs: Greeting) -> None:
    """Decide whether these two peers can play each other.

    Raises:
        HandshakeError: naming the reason, because both teams must **agree** a
            result before either may report it, and "handshake failed" with no
            cause is far harder to agree on than a stated mismatch.
    """
    if theirs.protocol_version != ours.protocol_version:
        raise HandshakeError(
            f"opponent speaks protocol {theirs.protocol_version!r}, we speak "
            f"{ours.protocol_version!r}; the wire contract must match exactly"
        )
    if theirs.role == ours.role:
        raise HandshakeError(
            f"both peers claim the role {theirs.role!r}; a game with two "
            f"{theirs.role}s has no capture target and no way to end"
        )
    if ours.reachable and not theirs.reachable:
        raise HandshakeError(
            f"we advertise {ours.public_url} but were given {theirs.public_url}, "
            "which routes nowhere from here. Every call would time out and the "
            "sub-game would end in a technical loss scoring zero for both sides"
        )


def check_rotation(current: Greeting, fresh: Greeting) -> None:
    """Decide whether ``fresh`` is the same opponent at a new address.

    Free-tier tunnels issue a new URL on every restart, so a six-sub-game
    series can outlive the tunnel it started on. Between sub-games that is a
    routine event and re-handshaking beats restarting the whole series.

    What must **not** change is who we are playing. A greeting that alters the
    role or the team identity is not a rotated tunnel; it is a different peer
    arriving in the middle of our series, and quietly following it would mean
    finishing a match against someone the declaration does not name.

    Raises:
        HandshakeError: if anything but the address moved.
    """
    for field, was, now in (
        ("role", current.role, fresh.role),
        ("group_id", current.group_id, fresh.group_id),
        ("protocol_version", current.protocol_version, fresh.protocol_version),
    ):
        if was != now:
            raise HandshakeError(
                f"a rotated tunnel may change the address and nothing else, but "
                f"{field} went from {was!r} to {now!r}; this is a different peer"
            )


@dataclass(frozen=True, slots=True)
class Peering:
    """The two addresses in force, and the sub-game they were agreed for.

    The sub-game number is what makes a rotation checkable. An address change
    **between** sub-games is a tunnel restart; the same change **during** one
    is indistinguishable from an opponent redirecting our traffic after seeing
    what we committed to. Carrying the number means the difference is a
    comparison rather than a matter of trust.
    """

    ours: Greeting
    theirs: Greeting
    sub_game: int

    def rotate(self, ours: Greeting, theirs: Greeting, sub_game: int) -> "Peering":
        """Adopt fresh addresses for a later sub-game.

        Raises:
            HandshakeError: if either peer changed into someone else, or if the
                sub-game did not advance.
        """
        if sub_game <= self.sub_game:
            raise HandshakeError(
                f"addresses may only change between sub-games; sub-game {sub_game} "
                f"does not follow {self.sub_game}. Mid-game it is indistinguishable "
                "from redirecting our traffic after seeing our commit"
            )
        check_rotation(self.ours, ours)
        check_rotation(self.theirs, theirs)
        check(ours, theirs)
        return Peering(ours, theirs, sub_game)

    def relocations(self, later: "Peering") -> dict[str, tuple[str, str]]:
        """Which addresses actually moved, as ``role -> (was, now)``.

        A re-handshake usually changes nothing — the tunnel outlived the
        sub-game. Reporting only the addresses that really moved is what tells
        a routine re-greeting apart from one that re-pointed live traffic, and
        it is the line a transport log wants to carry.
        """
        return {
            was.role: (was.public_url, now.public_url)
            for was, now in ((self.ours, later.ours), (self.theirs, later.theirs))
            if was.public_url != now.public_url
        }


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
