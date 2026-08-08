"""What a step commits to, assembled before the nonce is folded in.

Split out of :mod:`.crypto` so the sealing formula and the record shape sit in
separate files without either growing past the module budget. Nothing here
hashes anything: these functions only decide **which fields** go into the
commitment and in what form. :mod:`.crypto` re-exports every name below, so
``from ..domain.crypto import step_record`` keeps working and the wire format
is unchanged.

:class:`CryptoError` lives here rather than next to the hashing because both
halves raise it and the record half is the one with no other dependency.
"""

from typing import Any

from .actions import ROLES
from .board import BoardState, Position


class CryptoError(ValueError):
    """Raised when a revealed record does not match its commitment."""


def board_terms(state: BoardState, role: str) -> dict[str, Any]:
    """The part of the board the opponent can check at the audit.

    Anti-replay is what the rulebook asks ``State`` for: it pins a commitment
    to one specific step so an old one cannot be reused in a new context. Grid
    size, step number, our own cell and the barrier set do that, and every one
    of them is independently verifiable by the other side once the match ends.

    **Our belief about their position is deliberately absent.** Including it
    would look more complete and be strictly worse: neither peer can check the
    other's belief, so a sealed belief is a number we could have written after
    the fact. Sealing something unverifiable does not make it true, it only
    makes the audit unable to say anything about it.

    Positions become lists because that is what survives JSON. A tuple and a
    list serialise identically going out and come back as a list, so a peer
    that re-hashed a parsed record would get a different digest from one that
    hashed its own.
    """
    if role not in ROLES:
        raise CryptoError(f"role must be one of {sorted(ROLES)}, got {role!r}")
    mine = state.cop if role == "police" else state.thief
    return {
        "grid_size": state.grid_size,
        "step": state.step,
        "self": list(mine),
        "barriers": sorted(list(cell) for cell in state.barriers),
    }


def step_record(
    state: BoardState,
    role: str,
    move: str,
    intent: str,
    hint: str,
    barrier_placed: Position | None = None,
    scent: dict[str, float] | None = None,
    *,
    game_uid: str = "series-123",
    sub_game: int = 2,
) -> dict[str, Any]:
    """Everything one step commits to, before the nonce is folded in.

    The four fields the rulebook names, plus the four it says the real record
    also carries. ``barrier_placed`` is here because a barrier is an action
    with permanent consequences — it is the one move that changes the board for
    the rest of the match, and a cop that could re-describe where it built
    afterwards would have the most valuable rewrite available to either side.

    Only the cop ever passes it. The field is present in both agents anyway, so
    the two sides serialise the same shape and a thief's ``null`` is a fact
    about the turn rather than a difference in format.

    **The scent field is sealed too, and it is the whole point of sealing.**
    The trail is the one witness the rulebook calls unfalsifiable, and it is
    disclosed a phase later than the commitment — so without binding it here, a
    peer could read the opponent's reveal and only then decide what trail to
    claim it had left. Sealed, the field is fixed before anyone has spoken, and
    a single cell edited afterwards changes the digest and fails the audit.

    Sealed **in full** rather than as a digest of itself. A digest would bind
    just as tightly and would leave the log unable to prove anything on its
    own: the Replay App re-hashes the record it finds in the file, and a record
    naming a field nobody kept is a record a third party cannot check.

    ``None`` is a fact about the turn, not an omission — the key is always
    present, so the two sides serialise one shape whether or not a series was
    negotiated with scent binding in force.
    """
    return {
        "game_uid": game_uid,
        "sub_game": sub_game,
        "state": board_terms(state, role),
        "role": role,
        "move": move,
        "intent": intent,
        "hint": hint,
        "barrier_placed": list(barrier_placed) if barrier_placed else None,
        "scent": dict(scent) if scent is not None else None,
    }
