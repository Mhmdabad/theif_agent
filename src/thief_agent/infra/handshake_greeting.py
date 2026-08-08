"""The greeting two strangers trade, and whether the pair can play at all."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .protocol import ROLES
from .tunnel import NotPublicError, host_is_public, normalise
from .validation import InvalidPayloadError, require_mapping, require_str


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
