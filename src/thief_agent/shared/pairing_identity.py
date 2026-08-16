"""Pre-game identity checks shared with the cohort interop convention."""

from ..infra.declaration import Team
from ..infra.handshake import Greeting, HandshakeError, Peering
from .naming import game_id_for

__all__ = ["validate_pairing_identity"]


def validate_pairing_identity(
    game_id: str, us: Team, them: Team, ours: Greeting, peering: Peering
) -> None:
    """Refuse stale config or a game id not derived from the wire identities."""
    wire_us, wire_them = ours.group_id, peering.theirs.group_id
    if us.name != wire_us:
        raise HandshakeError(
            f"our configured group_name {us.name!r} differs from our announced group_id {wire_us!r}"
        )
    if them.name != wire_them:
        raise HandshakeError(
            f"opponent config names {them.name!r}, but the peer announced {wire_them!r}"
        )
    expected = game_id_for(wire_us, wire_them)
    if game_id != expected:
        raise HandshakeError(f"game_id must be the sorted group pair {expected!r}, got {game_id!r}")
