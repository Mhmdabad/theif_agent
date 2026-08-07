"""Commit-Reveal sealing, in the wire form the cohort uses.

Every step a peer seals its true record under
``commit = SHA256(canonical_json(payload) | nonce)`` and sends **only** the
commit. Nonces are withheld until the end-of-game audit, where both sides
re-verify every step — so no position or action can be rewritten afterwards.

**This formula is not ours to choose.** It has to match the opponent's byte for
byte, or two peers who both played honestly produce a ``TAMPERED`` verdict on a
clean match — voided, no appeal, zero for both sides. The shape here follows the
course reference implementation, which is the only thing resembling a shared
standard across the cohort.

Three details carry that compatibility, and each is easy to get silently wrong:

``ensure_ascii=False``
    ``json.dumps`` defaults to ``True``, escaping non-ASCII to ``\\uXXXX``.
    Identical bytes for an English hint, different bytes the moment a hint
    carries a non-ASCII character — and hints are free natural language.

The nonce is **appended after a pipe**, not folded into the payload
    ``SHA256(canonical | "|" | nonce)``. Putting it inside the object changes
    both the canonical string and the digest.

``sort_keys=True`` with tight separators
    So key order and incidental whitespace cannot change the digest.
"""

import hashlib
import secrets
from typing import Any

from ..shared.config import canonical_bytes
from .actions import ROLES
from .board import BoardState, Position

NONCE_BYTES = 16
"""Matches the reference. ``secrets.token_hex(16)`` gives a 32-char nonce."""


class CryptoError(ValueError):
    """Raised when a revealed record does not match its commitment."""


def nonce() -> str:
    """A fresh 128-bit nonce, from the CSPRNG and never from :mod:`random`.

    The rulebook names the module: ``secrets``, *not* ``random``, which it
    calls too predictable. That is not stylistic advice.

    A nonce does two jobs. It makes repeating an action produce a different
    digest, and it defeats a dictionary attack — the move space is tiny, five
    moves and a handful of barrier cells, so without a nonce an opponent hashes
    every possibility and cracks each commitment in microseconds.

    Both jobs need the value to be **unguessable**, and :mod:`random` is
    reproducible by construction: it is a Mersenne Twister whose entire future
    follows from its state, and the state follows from enough observed output.
    A series hands the opponent hundreds of nonces at the final reveal. Anything
    that lets them predict the next one lets them pre-image our commitments and
    read our move before we make it — which is the whole thing this mechanism
    exists to prevent.

    Sixteen bytes because the reference uses sixteen. Collision resistance is
    not the point at this size — unpredictability is — but a shared length is
    one less thing for two implementations to disagree about.
    """
    return secrets.token_hex(NONCE_BYTES)


def canonical(payload: dict[str, Any]) -> str:
    """The canonical JSON text a commitment is taken over.

    Delegates rather than re-deriving. This module used to serialise with
    ``ensure_ascii=False`` while :func:`~..shared.config.canonical_bytes` left
    the default — two canonical forms in one codebase, agreeing on every
    English payload and disagreeing on the first hint with a non-ASCII
    character in it.
    """
    return canonical_bytes(payload).decode("utf-8")


def commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commitment for ``payload`` under ``nonce``.

    The nonce joins the record as a field and the whole thing is serialised
    once, which is what the rulebook's ``|`` operator means here.

    Raises:
        CryptoError: if the payload already carries a ``nonce``. Merging would
            silently drop one of the two, and the one dropped decides whether
            the commitment can ever be reopened.
    """
    if "nonce" in payload:
        raise CryptoError("payload already has a 'nonce'; pass it once, as the argument")
    return hashlib.sha256(canonical_bytes({**payload, "nonce": nonce})).hexdigest()


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
        "state": board_terms(state, role),
        "role": role,
        "move": move,
        "intent": intent,
        "hint": hint,
        "barrier_placed": list(barrier_placed) if barrier_placed else None,
        "scent": dict(scent) if scent is not None else None,
    }


def seal(payload: dict[str, Any]) -> dict[str, str]:
    """Draw a fresh nonce and commit to ``payload``.

    Returns the nonce alongside the commit. Only the commit crosses the wire at
    commit time; the nonce is withheld until the final audit, so an opponent
    cannot reverse-engineer the record while the match is still running.
    """
    fresh = nonce()
    return {"nonce": fresh, "commit": commit_of(payload, fresh)}


def verify(payload: dict[str, Any], nonce: str, commit: str) -> None:
    """Re-derive the commitment and compare.

    Raises:
        CryptoError: on any mismatch. There is no near-miss — SHA-256 is
            sensitive to every bit, so a difference is proof of tampering and
            costs the responsible team the match.
    """
    actual = commit_of(payload, nonce)
    if not secrets.compare_digest(actual, commit):
        raise CryptoError(f"commit mismatch: declared {commit[:16]}…, recomputed {actual[:16]}…")


def audit(records: list[dict[str, Any]]) -> None:
    """Re-verify every revealed record.

    Raises:
        CryptoError: naming the first failing step, since the match is void
            from that point and the step number is what the two teams have to
            agree on when reconciling the result.
    """
    for index, record in enumerate(records):
        try:
            verify(record["payload"], record["nonce"], record["commit"])
        except KeyError as exc:
            raise CryptoError(f"record {index} is missing {exc.args[0]!r}") from exc
        except CryptoError as exc:
            step = record.get("payload", {}).get("step", index)
            raise CryptoError(f"tampering at step {step}: {exc}") from exc
