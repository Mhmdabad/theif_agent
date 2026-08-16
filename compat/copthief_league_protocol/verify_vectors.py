"""League interop-kit conformance checker — stdlib only, no dependencies.

Re-implements every byte-level construction that two independent implementations of the
official assignment (Dr. Yoram Segal, *Distributed Cops-and-Robbers over a Peer-to-Peer
Network*, book v3.0.0) MUST agree on, and verifies the fixtures under ``vectors/``.

This kit is NOT the game spec — the book is. It pins only the serialization details the book
leaves to inter-team agreement, which are exactly where two clean-room codebases silently
diverge and lose a match. See SPEC.md for the mapping to the book's chapters.

Two ways to use it:

1. ``python verify_vectors.py`` — confirms the reference constructions reproduce every fixture.
2. Port the ``ref_*`` functions' *behavior* into your own codebase, then point your test suite at
   the same JSON fixtures. If your implementation reproduces every CORE vector, your hashes are
   byte-compatible with every other conformant team: your agreement signature will verify, both
   sides derive the same ``game_uid``, and the post-game audit of your revealed log (which the
   opponent re-hashes) passes instead of raising a false ``tamper_forfeit``.

The ENHANCEMENT vectors cover opt-in mechanics that are *not* required by the book (SPEC Appendix
A); a pair of teams conforms to them only if they agree to and both sign them into config/game.json.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import uuid
from pathlib import Path

VECTORS = Path(__file__).parent / "vectors"


# --- the one canonical form (book ch.5; reference domain/crypto.py) -----------------------
#
# json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
#
# Note ensure_ascii=FALSE: non-ASCII (Hebrew hints, emoji, non-English map areas) is emitted as
# native UTF-8, NOT \uXXXX-escaped. An implementation that escapes will produce a different hash
# for any payload containing non-ASCII — and since the opponent re-hashes your revealed payloads
# (which include your free-language `hint`) at audit, that mismatch reads as tampering and voids
# the match for BOTH sides. This is the single most important fact in this kit.


def _canonical_str(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_bytes(obj: object) -> bytes:
    return _canonical_str(obj).encode("utf-8")


def canonical_hash(obj: object) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


# --- CORE constructions (must match cross-team) ------------------------------------------


def ref_commit(payload: dict, nonce: str) -> str:
    """Per-step / agreement commit: SHA-256 over canonical(payload) with the nonce pipe-appended.

    commit = SHA256( canonical_json(payload) + "|" + nonce )

    The nonce is NOT inside the hashed object; it is concatenated to the canonical string. Each
    peer seals its own payload and sends only the commit; nonces are revealed at the end-of-game
    audit, where BOTH peers re-hash every revealed (payload, nonce) and must reproduce the commit.
    """
    return hashlib.sha256(f"{_canonical_str(payload)}|{nonce}".encode()).hexdigest()


def ref_terms_signature(terms: dict, nonce: str) -> str:
    """Pre-game agreement signature — identical construction to a commit, over the agreed terms.

    The opponent recomputes it over the terms it received (which must value-equal its own) using
    the signer's nonce; any canonicalization difference (ensure_ascii, float repr, key naming)
    makes the signature fail and the peers refuse to start.
    """
    return ref_commit(terms, nonce)


def ref_game_uid(terms: dict, group_a: str, group_b: str) -> str:
    """Deterministic shared game id both peers reproduce without a round-trip.

    game_uid = UUID( SHA256( canonical(terms) + "|" + "|".join(sorted([group_a, group_b])) )[:16] )
    """
    pair = sorted([group_a, group_b])
    seed = f"{_canonical_str(terms)}|{'|'.join(pair)}"
    return str(uuid.UUID(bytes=hashlib.sha256(seed.encode()).digest()[:16]))


def ref_game_id(group_a: str, group_b: str) -> str:
    """The human-readable match id that names all four submission artifacts.

    game_id = "-vs-".join(sorted([group_a, group_b]))

    SORTED — the same pair term that goes into ``ref_game_uid``. Both peers therefore derive one
    identical string with no round-trip and no convention to settle. A peer that names *itself*
    first instead ("<us>-vs-<them>") produces a different id on each side, so one match yields two
    sets of artifact filenames and the two teams' reports cannot be joined by ``game_id`` at all.
    """
    return "-vs-".join(sorted([group_a, group_b]))


def ref_smell_emit(center, intensity, grid_size, board_size):
    """Radial scent emission around a cell (book ch.4; reference domain/smell.py).

    half = grid_size // 2 ; falloff = intensity / (half + 1)
    value(cell) = round(max(0.0, intensity - falloff * chebyshev(cell, center)), 3)

    Returns the wire/snapshot form {"r,c": value} for cells inside the board with value > 0.
    """
    half = grid_size // 2
    falloff = intensity / (half + 1)
    out: dict[str, float] = {}
    for dr in range(-half, half + 1):
        for dc in range(-half, half + 1):
            r, c = center[0] + dr, center[1] + dc
            if 0 <= r < board_size and 0 <= c < board_size:
                value = round(max(0.0, intensity - falloff * max(abs(dr), abs(dc))), 3)
                if value > 0.0:
                    out[f"{r},{c}"] = value
    return out


def ref_smell_decay(values: dict, decay: float) -> dict:
    """One game-step decay: every intensity drops by the constant, clamped at 0 (rounded to 3)."""
    return {k: round(max(0.0, v - decay), 3) for k, v in values.items()}


def ref_report_consensus_signature(report: dict) -> str:
    """Settlement consensus signature (reference report_writer.py, verified at sha 960499fd).

    A SECOND canonical form, unlike every other hash in the release: sort_keys=True,
    ensure_ascii=False, but DEFAULT (spaced) separators — json.dumps' (', ', ': ').
    The signature is computed over the report BEFORE the Hebrew signature key
    is inserted (sign-then-insert), so the field is excluded from its own preimage.
    Verify an emailed report by popping the signature key, re-serializing spaced,
    and re-hashing. Found by Alon's team (alonengel / anrbj666).
    """
    spaced = json.dumps(report, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(spaced.encode("utf-8")).hexdigest()


# --- LOCKED-MODEL DECLARATIONS (SPEC section 7) -------------------------------------------
#
# One document schema serving three named-parameter families. A peer that wants to bind a
# choice publishes a doc, hashes it, and declares the hash at negotiate time as
# "<family>_sha256". The doc itself never crosses the wire — only the hash — so the schema
# exists to make two teams' hashes COMPARABLE. Two correct implementations of the same model
# that hash different field sets refuse each other for no reason; that is the failure this
# section removes.

LOCK_FAMILIES = ("scent_model", "wire_shape", "info_mode", "smell_binding")
LOCK_DOC_KEYS = ("family", "name", "params", "example")


def ref_lock_doc(family: str, name: str, params: dict, example: dict) -> dict:
    """A locked-model doc: exactly four keys, canonicalized by the section-2 form.

    Keeping the key set closed is the whole point — `params` and `example` carry everything
    model-specific, so the envelope is identical across families and versions.
    """
    if family not in LOCK_FAMILIES:
        raise ValueError(f"unknown family {family!r}; expected one of {LOCK_FAMILIES}")
    return {"family": family, "name": name, "params": params, "example": example}


def ref_lock_hash(doc: dict) -> str:
    """The declared value: SHA-256 over the compact canonical doc (section 2).

    Same construction Alon's team already ships as `scent_model_sha256` — a bare hash over a
    compact-canonical spec dict. The kit adds only the field set underneath it.
    """
    if tuple(sorted(doc)) != tuple(sorted(LOCK_DOC_KEYS)):
        raise ValueError(f"lock doc must have exactly {LOCK_DOC_KEYS}, got {tuple(sorted(doc))}")
    return canonical_hash(doc)


def ref_lock_decision(ours: str | None, theirs: str | None) -> str:
    """The refusal rule: refuse ONLY when both peers declare a family and disagree.

    Omission is never refusal. A peer that declares nothing (the unmodified reference peer
    declares nothing at all) stays playable — a lock that fail-fasts on a missing declaration
    cannot play the lecturer's own tooling, which is a self-inflicted forfeit, not a safeguard.
    """
    if ours is None or theirs is None:
        return "play"
    return "play" if ours == theirs else "refuse"


# --- PAIRING DECLARATION (SPEC section 7.2) ----------------------------------------------
#
# Two fields ride the negotiate extras BESIDE `terms`, never inside it: the terms are a flat
# signed set, so adding a key there breaks the signature (section 4). They answer the one
# question the signed terms cannot: "are you the peer I think I am talking to, in the game I
# think we are playing?" Identical terms give identical game_uids, so by the time an artifact
# exists a mispairing is already invisible — the handshake is the only place it can be seen.

def ref_pairing_decision(ours: dict, theirs: dict) -> str:
    """Accept, or refuse with a reason, on the two declared pairing fields.

    ``ours`` / ``theirs`` are the declared extras: ``{"sub_game_number": int, "role": str}``,
    either key possibly absent. Returns "play", "refuse:sub_game" or "refuse:role".

    Three rules, in the order they bite:

    1. **Sub-game mismatch refuses.** One game cannot carry two indices. Two peers that disagree
       here settle the same game under different numbers and their two reports contradict.
    2. **Role collision refuses.** The two sides of a game are complementary; two of the same
       side can only deadlock, and the deadlock costs a whole turn budget to discover.
    3. **Omission never refuses** — in either direction, and a value that cannot be compared is
       treated as silence. This is the same rule section 7 uses for locked models, for the same
       reason: the unmodified reference peer declares neither field, so a guard that fail-fasts
       on silence forfeits that game to itself. Refusing over a peer's type or spelling choice
       would likewise turn a cosmetic wire difference into a lost game.
    """
    ours_sg, theirs_sg = ours.get("sub_game_number"), theirs.get("sub_game_number")
    if isinstance(ours_sg, int) and isinstance(theirs_sg, int) and ours_sg != theirs_sg:
        return "refuse:sub_game"
    ours_role, theirs_role = ours.get("role"), theirs.get("role")
    if isinstance(ours_role, str) and isinstance(theirs_role, str) and ours_role == theirs_role:
        return "refuse:role"
    return "play"


# --- UID DECLARATION (SPEC section 7.3, PROPOSED) ----------------------------------------
#
# The `game_uid` never crosses the wire: each peer derives it from the flat negotiated terms and
# the two sorted group ids, so neither has anything to compare against. A peer that derives it
# from the wrong input — a whole config rather than the extracted terms — therefore produces a
# uid that is perfectly deterministic, self-consistent across all four of its artifacts, and
# wrong only against the opponent. That divergence is invisible until two reports are diffed,
# which happens after the games are over.
#
# Declaring the derived uid at negotiate closes the window: the disagreement surfaces before a
# single move instead of the next morning.

def ref_uid_declaration_decision(ours: str | None, theirs: str | None) -> str:
    """Refuse only when both peers declare a derived uid and the values differ.

    Deliberately the same rule as ``ref_lock_decision`` and ``ref_pairing_decision`` — omission
    never refuses, in either direction — and it delegates rather than restating it, so the three
    declarations cannot drift apart. The reference peer declares nothing at all, and a guard that
    fail-fasts on silence forfeits that game to itself.

    A value that is not a string is treated as silence for the same reason: refusing over a
    representation choice would turn a cosmetic difference into a lost game.
    """
    if not isinstance(ours, str) or not isinstance(theirs, str):
        return "play"
    return ref_lock_decision(ours, theirs)


# --- SMELL BINDING (SPEC section 7.4) ----------------------------------------------------
#
# Under `wire_shape: reference-v3` the smell grid rides the wire unauthenticated: it is the one
# per-step observable that no commitment covers. A stale, malformed or forged grid is therefore
# detectable only by a receiver's own physics check, whose refusals are provable to nobody but
# the refuser. `smell_binding:commit_grid_v1` binds the grid to the sealed step record, so the
# same machinery that already protects moves protects the field — a mismatch becomes provable at
# the mutual audit, where it can be sanctioned rather than merely logged.
#
# What it does NOT buy is privacy: an honest, correctly bound grid inverts to the sender's cell
# exactly as an unbound one does. Localization is `info_mode`'s problem, or a pairwise
# nothing-on-the-wire arrangement's — never this binding's.

def ref_smell_grid_sha256(grid: dict) -> str:
    """The digest a bound sender seals: SHA-256 over the compact canonical grid (section 2).

    The argument is the grid **as transmitted** — the exact wire value, not a re-derived or
    re-rounded copy. Two consequences worth pinning:

    * an empty grid is `{}` and hashes as `{}`; it is a legal, meaningful input, not a gap;
    * the keys are `"r,c"` STRINGS, so canonical JSON sorts them lexicographically —
      `"10,1"` precedes `"2,3"`. An implementation that sorts its grid numerically before
      serializing produces a different digest for the same field on any board wider than ten.
    """
    return canonical_hash(grid)


def ref_bind_record(record: dict, grid: dict) -> dict:
    """Add the binding key to a sealed step record.

    Deliberately nothing more than a key insertion: the digest enters the step's commit preimage
    through the existing section-3 construction, so binding adds no new hash form and does not
    touch the commit algorithm. That is also why it is a commit-preimage change and must never
    debut in a counted game — both peers change what they seal on the same turn or neither does.
    """
    return {**record, "smell_grid_sha256": ref_smell_grid_sha256(grid)}


def ref_binding_audit(sealed: dict, archived_grid: dict | None) -> str:
    """The audit-side verdict on one bound step.

    ``sealed`` is the revealed step record; ``archived_grid`` is the grid the verifier's own
    peer archived as received for that step. Returns:

    * ``"unbound"``  — the record carries no digest. Not a failure: a peer that never heard of
      the family plays exactly as today, the same way omission never refuses in section 7.
    * ``"ok"``       — the archived grid re-hashes to the sealed digest.
    * ``"bound_mismatch"`` — it does not. The sender sealed one field and transmitted another,
      which is audit-grade, not merely evidence-grade.

    ``archived_grid = None`` means no grid was archived for a step whose sender claims to have
    bound one, and that is a mismatch too: there is nothing that can re-hash to the digest. It is
    not the empty-grid case — a sender that transmitted ``{}`` sealed the digest OF ``{}``, and
    that re-hashes cleanly. Absence and emptiness are different inputs here, on purpose.
    """
    digest = sealed.get("smell_grid_sha256")
    if digest is None:
        return "unbound"
    if archived_grid is None:
        return "bound_mismatch"
    return "ok" if ref_smell_grid_sha256(archived_grid) == digest else "bound_mismatch"


# --- THE WIRE SURFACE (SPEC section 7.5) -------------------------------------------------
#
# The tool NAMES have been published since the first release, inside the `wire_shape:
# reference-v3` locked document. What was never published is the SHAPE of what those tools
# carry, so a team could learn that `receive_turn` exists and still have nothing to build
# against. best2934 lost a scheduled friendly to exactly that gap (issue #45): two peers with
# fourteen agreed terms, verifying signatures and green tunnels, whose tool surfaces turned out
# to be disjoint except for `negotiate`.
#
# Validation is behaviour, not bytes, so it is pinned as a decision function like section 7.1.

TURN_REQUIRED = ("step", "sender", "hint", "smell_grid", "commit", "timestamp")
TURN_OPTIONAL = ("barrier_placed", "capture_claim", "claim_response", "win_claim")


def ref_turn_validate(raw: dict) -> str:
    """Whether an inbound TurnMessage is admissible, and if not, which field refused it.

    Returns ``"accept"`` or ``"<field>: <reason>"``. A receiver MUST validate before any
    state change: the message is adversarial input, and a partially-applied bad turn is
    unrecoverable. Every problem is named rather than the first one, so a peer fixes its
    encoder in one round trip instead of six.

    Unknown keys are TOLERATED and ignored — the extension seam. Missing required keys are
    not: a receiver that defaults them invents a move the sender never sealed.
    """
    problems: list[str] = []
    step = raw.get("step")
    if not isinstance(step, int) or isinstance(step, bool) or step < 0:
        problems.append("step: required non-negative int")
    for name in ("sender", "timestamp"):
        value = raw.get(name)
        if not isinstance(value, str) or not value:
            problems.append(f"{name}: required non-empty str")
    if not isinstance(raw.get("hint"), str):
        problems.append("hint: required str (may be empty)")
    grid = raw.get("smell_grid")
    if not isinstance(grid, dict) or not all(
        isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
        for k, v in grid.items()
    ):
        problems.append("smell_grid: required dict of 'r,c' -> number")
    commit = raw.get("commit")
    if not (isinstance(commit, str) and len(commit) == 64
            and all(c in "0123456789abcdef" for c in commit)):
        problems.append("commit: required 64-char lowercase hex")
    for name in ("barrier_placed", "capture_claim"):
        cell = raw.get(name)
        if cell is not None and not (
            isinstance(cell, (list, tuple)) and len(cell) == 2
            and all(isinstance(i, int) and not isinstance(i, bool) for i in cell)
        ):
            problems.append(f"{name}: optional [row, col] of ints, or null")
    return "accept" if not problems else "; ".join(problems)


# --- AT-LEAST-ONCE DELIVERY (SPEC section 7.1) -------------------------------------------
#
# Both registered wire shapes ride HTTP, which is at-least-once. A push whose ack is lost is
# retried by a correct client, so the same message arrives twice — by design, not only on bad
# networks. The receiver's answer is behaviour, not bytes, which is why this is pinned as a
# decision function with a truth table rather than as a hash.

def ref_delivery_decision(state: dict, arrival: dict) -> str:
    """What a receiver must do with an inbound turn message.

    ``state``  = {"played": {step: commit}, "buffered": [steps], "window": int, "next": step}
    ``arrival``= {"step": int, "commit": str}

    Returns one of:

    * ``"absorb"``    — a redelivery of something already played. State is unchanged; this is the
      only answer that costs nothing. Note the key: **the commit, not (kind, step)**. A commit is
      the one field a redelivery cannot vary, so keying on it collapses a retry while keeping a
      *second, different* commit for a played step distinguishable — and that case is tampering
      evidence, which must stay loud. A (kind, step) key collapses both, silently.
    * ``"equivocation"`` — a different commit for a step already played. Two commitments for one
      step is exactly what commit-reveal exists to catch. Transport tolerance does not extend
      here: the rules layer is not tolerant.
    * ``"apply"``     — the next expected step; apply it and drain anything buffered behind it.
    * ``"buffer"``    — an out-of-order arrival inside the reorder window; hold and replay in
      step order.
    * ``"violation"`` — past the window bound. Let the window be the flood rule; a second
      threshold beside it is unreachable and only adds a way to disagree.

    A receiver with **no** reorder window (``window`` 0) turns an ordinary retry race into a
    protocol violation, which under App. E rule 35 is a self-inflicted technical loss that zeroes
    both teams. Zero tolerance is not a tightening here.
    """
    played, step, commit = state["played"], arrival["step"], arrival["commit"]
    if str(step) in played or step in played:
        seen = played.get(str(step), played.get(step))
        return "absorb" if seen == commit else "equivocation"
    if step == state["next"]:
        return "apply"
    if step < state["next"]:
        # Below `next` and never played: this step can never become applicable — `next` only
        # advances past steps that were accepted, so a stale index that was not accepted is
        # malformed (step 0, a voided attempt's leftover), not late. An earlier revision let it
        # fall through to "buffer", where it sat forever and two conformant receivers could
        # legitimately diverge on it — found by anrbj666's 2026-08-04 audit.
        return "discard"
    if step - state["next"] <= state["window"]:
        return "buffer"
    return "violation"


def ref_deadline_decision(deadline_at: float, now: float, arrived: bool, tolerated: bool) -> str:
    """Whether a turn deadline has expired — evaluated on EVERY lap, not only on empty polls.

    Returns "expired" or "waiting".

    One clock per *expected* message. A redelivered or early push proves the opponent is alive
    but does not discharge what it owes, so it renews nothing: ``tolerated`` traffic never moves
    ``deadline_at``. And the deadline is judged here even on a lap where a message *did* arrive —
    a receiver that only checks its clock on an empty poll never checks it under a flood, so a
    stall attempt would burn the receiver's budget instead of the sender's.
    """
    del arrived, tolerated  # neither can renew or defer the deadline; that is the contract
    return "expired" if now >= deadline_at else "waiting"


# --- book-v3 scent model (SPEC section 5.1; tier declared in gen_vectors.TIERS) -----------
#
# The book's ch.4 model, as distinct from the reference's (section 5). Printed figure 4 is a
# 5x5 emission kernel; the update is multiplicative and runs once per FULL turn.

BOOK_KERNEL = (
    (0.04, 0.14, 0.20, 0.14, 0.04),
    (0.14, 0.42, 0.62, 0.42, 0.14),
    (0.20, 0.62, 0.90, 0.62, 0.20),
    (0.14, 0.42, 0.62, 0.42, 0.14),
    (0.04, 0.14, 0.20, 0.14, 0.04),
)


def ref_book_kernel_delta(dr: int, dc: int) -> float:
    """The deposit at offset (dr, dc) from the emitting agent — a VERBATIM table lookup.

    Not a closed form on purpose. The printed values are reproducible by a radial Gaussian,
    but only inside a narrow sigma window that the book never prints, and the window differs
    by quantization rule (see `closed_form_probe` in vectors/scent_book_v3.json). Two teams
    each fitting their own Gaussian get different fields; the printed table is the only thing
    both can land on.
    """
    if abs(dr) > 2 or abs(dc) > 2:
        return 0.0
    return BOOK_KERNEL[dr + 2][dc + 2]


def ref_book_update(tau: float, delta: float, rho: float, center_intensity: float) -> float:
    """One cell, one full turn: tau' = clamp((1 - rho) * tau + delta, 0, center_intensity).

    Evaluation order is load-bearing and pinned exactly as written. The model does NO
    rounding, so the algebraically-equivalent `tau - rho * tau + delta` differs from this in
    the last bit for many inputs (75 of 534 probed) — enough to break a byte-comparison of two
    recomputed fields. Compute it in this order, or compare fields with a tolerance.

    The upper clamp is NOT in the book's printed formula, which shows only `max(0, ...)`; it
    comes from the book's own declaration that tau is a continuous value in [0, 0.9]. Without
    it a cell that decays and is re-deposited on exceeds the centre intensity (the 1.43 case).
    """
    return min(max(0.0, (1 - rho) * tau + delta), center_intensity)


def ref_book_full_turn(field: dict, center, rho: float, center_intensity: float,
                       board_size: int) -> dict:
    """One FULL turn of one agent's own trail: decay everything, deposit the kernel, clamp.

    Cadence is the book's: the update runs once per full turn, after both agents have moved —
    not once per half-turn step. Decay and deposit are a single expression, so decay applies
    to the pre-existing field only (decay-then-deposit). The reference model does the reverse
    (deposit, then decay before sending), which is one of the two models' real divergences.

    Each side recomputes the rival's field from revealed actions; nothing is received, so
    there is no receiver-side decay pass.
    """
    cells = set(field) | {
        f"{center[0] + dr},{center[1] + dc}"
        for dr in range(-2, 3) for dc in range(-2, 3)
        if 0 <= center[0] + dr < board_size and 0 <= center[1] + dc < board_size
    }
    out: dict[str, float] = {}
    # Sorted by (row, col): set iteration order varies between runs, and while key order cannot
    # change a hash (canonicalization sorts), it would make the committed fixture drift in CI.
    for key in sorted(cells, key=lambda k: tuple(int(x) for x in k.split(","))):
        r, c = (int(x) for x in key.split(","))
        value = ref_book_update(field.get(key, 0.0), ref_book_kernel_delta(r - center[0], c - center[1]),
                                rho, center_intensity)
        if value > 0.0:
            out[key] = value
    return out


# --- ENHANCEMENT constructions (opt-in; NOT required by the book) -------------------------


def ref_share_commit(share: str) -> str:
    """SPEC Appendix A — joint-seed coin flip: commitment to one team's seed share."""
    return canonical_hash({"seed_share": share})


def ref_joint_seed(share_group_1: str, share_group_2: str) -> str:
    """SPEC Appendix A — the joint seed from both revealed shares (group_1 first)."""
    return canonical_hash({"shares": [share_group_1, share_group_2]})


def ref_derive_starts(seed: str, index: int, n: int) -> tuple[list[int], list[int], int]:
    """SPEC Appendix A — optional seeded asymmetric starts (a fairness alternative to the book's
    fixed configured starts). 4 digest bytes per cell, minimum-Chebyshev deterministic re-draw."""
    cells = n * n
    d_min = min(max(-(-n // 3), 2), n - 1)  # ceil(n/3), clamped to [2, n-1]
    for draw in range(64):
        digest = hashlib.sha256(f"{seed}:{index}:{draw}".encode()).digest()
        cop = int.from_bytes(digest[0:4], "big") % cells
        thief = int.from_bytes(digest[4:8], "big") % cells
        cop_rc = [cop // n, cop % n]
        thief_rc = [thief // n, thief % n]
        if max(abs(cop_rc[0] - thief_rc[0]), abs(cop_rc[1] - thief_rc[1])) >= d_min:
            return cop_rc, thief_rc, draw
    return [0, 0], [n - 1, n - 1], 64


# --- fixture checks -----------------------------------------------------------------------


_CHECKS = 0
_ROSTER: list[tuple[str, str]] = []  # (fixture, tier), in the order checked

# Display order for the run summary; a tier absent from the roster is simply not printed.
_TIER_ORDER = ("CORE", "PROMOTED", "PROPOSED", "ENH")


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _CHECKS
    _CHECKS += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")
    return ok


def _load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


def _section(name: str) -> dict:
    """Load a fixture and print its banner, taking the tier from the fixture's own ``status``.

    The tier is declared once, in ``gen_vectors.py``'s TIERS registry, and read back here — so
    this file cannot fall out of step with what the fixture says it is. It did once:
    ``multiplicative_book_v1`` was promoted in the fixture on 2026-07-20 while this checker went
    on printing ``[PROPOSED]`` beside it until 2026-07-26. What the tiers mean and what a
    promotion requires: docs/GOVERNANCE.md.
    """
    data = _load(name)
    tier = data.get("status")
    if tier is None:
        raise SystemExit(
            f"{name}: fixture declares no `status`. Regenerate with `python gen_vectors.py` — "
            f"the tier comes from that file's TIERS registry, never from a literal here."
        )
    _ROSTER.append((name, tier))
    print(f"[{tier}] {name}")
    return data


def run() -> int:
    failures = 0

    for i, v in enumerate(_section("canonical_json.json")["vectors"]):
        got = _canonical_str(v["object"])
        ok = got == v["canonical"] and canonical_hash(v["object"]) == v["sha256"]
        failures += not check(f"canonical #{i} ({v.get('note', '')})", ok, f"got {got!r}")

    cr = _section("commit_reveal.json")
    for i, v in enumerate(cr["vectors"]):
        got = ref_commit(v["payload"], v["nonce"])
        failures += not check(f"commit #{i} ({v.get('note', '')})", got == v["commit"], f"got {got}")
    # The release's three published commit constructions over the same sealed record (the audit-
    # snippet form consumes only its nonce|move fields) — all pinned and mutually distinct
    # (SPEC 'Commit-reveal': the contradiction, resolved).
    dv = cr["divergent_forms"]
    got_ref = ref_commit(dv["payload"], dv["nonce"])
    got_ch5 = canonical_hash({**dv["payload"], "nonce": dv["nonce"]})
    got_audit = hashlib.sha256(f"{dv['nonce']}|{dv['payload']['move']}".encode()).hexdigest()
    ok = (
        got_ref == dv["reference_form"]
        and got_ch5 == dv["book_ch5_listing_form"]
        and got_audit == dv["book_audit_snippet_form"]
        and len({got_ref, got_ch5, got_audit}) == 3
    )
    failures += not check("divergent forms: pinned + mutually distinct", ok)

    for i, v in enumerate(_section("terms_signature.json")["vectors"]):
        got = ref_terms_signature(v["terms"], v["nonce"])
        failures += not check(f"terms signature #{i}", got == v["signature"], f"got {got}")

    gu = _section("game_uid.json")
    for i, v in enumerate(gu["vectors"]):
        got = ref_game_uid(v["terms"], v["group_a"], v["group_b"])
        failures += not check(f"game_uid #{i}", got == v["game_uid"], f"got {got}")
        got_id = ref_game_id(v["group_a"], v["group_b"])
        failures += not check(f"game_id #{i} ({v['note']})", got_id == v["game_id"], f"got {got_id}")
    # Both ids must be order-independent, or the two peers name one match two different ways.
    uids = {v["game_uid"] for v in gu["vectors"]}
    ids = {v["game_id"] for v in gu["vectors"]}
    failures += not check("swapping the group order changes neither id",
                          len(uids) == 1 and len(ids) == 1)
    # The four artifact filenames derive from game_id (book App. F table 20).
    fn = gu["artifact_filenames"]
    gid = gu["vectors"][0]["game_id"]
    failures += not check(
        "artifact filenames derive from game_id",
        fn["declaration"] == f"declaration_{gid}.json"
        and fn["result"] == f"result_{gid}.json"
        and fn["config"] == f"config_{gid}_g<NN>.json"
        and fn["log"] == f"log_{gid}_g<NN>.json")

    ph = _section("pheromone.json")
    for i, v in enumerate(ph["emit"]):
        got = ref_smell_emit(v["center"], v["intensity"], v["grid_size"], v["board_size"])
        failures += not check(f"smell emit #{i}", got == v["field"], f"got {got}")
    for i, v in enumerate(ph["decay"]):
        got = ref_smell_decay(v["before"], v["decay"])
        failures += not check(f"smell decay #{i}", got == v["after"], f"got {got}")

    rc = _section("report_consensus.json")
    sig_key = rc["signature_key"]
    for i, v in enumerate(rc["vectors"]):
        got = ref_report_consensus_signature(v["report"])
        ok = got == v["signature"]
        # sign-then-insert: popping the signature key from the signed report re-yields the preimage
        stripped = {k: val for k, val in v["signed_report"].items() if k != sig_key}
        ok = ok and stripped == v["report"] and v["signed_report"][sig_key] == v["signature"]
        # the compact (§2) form must NOT reproduce the signature — the spaced form is load-bearing
        ok = ok and canonical_hash(v["report"]) == v["compact_form_sha256"] != v["signature"]
        failures += not check(f"consensus signature #{i} ({v.get('note', '')})", ok, f"got {got}")

    lm = _section("locked_model.json")
    schema_keys = tuple(lm["doc_schema"]["keys"])
    for entry in lm["registered"]:
        doc = entry["doc"]
        ok = (
            tuple(sorted(doc)) == tuple(sorted(schema_keys))
            and doc["family"] in lm["doc_schema"]["families"]
            and entry["declared_as"] == f"{doc['family']}_sha256"
            and ref_lock_hash(doc) == entry["sha256"]
        )
        failures += not check(f"lock doc {doc['family']}/{doc['name']}", ok)
    # Distinct registrations must hash distinctly, or a lock cannot tell them apart.
    hashes = [e["sha256"] for e in lm["registered"]]
    failures += not check("registrations mutually distinct", len(set(hashes)) == len(hashes))
    # Every registration states its own tier, on the same terms as the fixtures (GOVERNANCE.md).
    failures += not check(
        "every registration declares a status and its evidence",
        all(e.get("status") in _TIER_ORDER and e.get("evidence") for e in lm["registered"]))
    # The promotion evidence is itself a check: the hashes a second implementation put on the wire
    # must equal the docs registered here, or the claim in `evidence` is not true of this tree.
    observed = lm["live_reproduction"]["observed_declarations_matching_registrations"]
    by_name = {e["doc"]["name"]: e for e in lm["registered"]}
    failures += not check(
        "the live-declared hashes equal the registered docs",
        observed["scent_model_sha256"] == by_name["multiplicative_book_v1"]["sha256"]
        and observed["wire_shape_sha256"] == by_name["reference-v3"]["sha256"]
        and observed["info_mode_sha256"] == by_name["belief"]["sha256"])
    failures += not check(
        "the three registrations that evidence names are the promoted ones",
        by_name["multiplicative_book_v1"]["status"] == "PROMOTED"
        and by_name["reference-v3"]["status"] == "PROMOTED"
        and by_name["belief"]["status"] == "PROMOTED")
    # The declaration example was the one hash-bearing block this checker never touched
    # (anrbj666's audit, D5): only regen-diff protected it. Now it is asserted like the rest.
    example = lm["declaration_example"]
    failures += not check(
        "the declaration example's hashes equal the registered docs",
        example["scent_model_sha256"] == by_name["multiplicative_book_v1"]["sha256"]
        and example["wire_shape_sha256"] == by_name["reference-v3"]["sha256"]
        and example["info_mode_sha256"] == by_name["belief"]["sha256"])
    for i, v in enumerate(lm["refusal_rule"]):
        got = ref_lock_decision(v["ours"], v["theirs"])
        failures += not check(f"refusal rule #{i} ({v['note']})", got == v["decision"], f"got {got}")
    # Omission must never refuse — the property that keeps no-doc peers playable.
    silent = [v for v in lm["refusal_rule"] if v["ours"] is None or v["theirs"] is None]
    failures += not check("omission is never refusal",
                          bool(silent) and all(v["decision"] == "play" for v in silent))

    pd = _section("pairing_declaration.json")
    for i, v in enumerate(pd["refusal_rule"]):
        got = ref_pairing_decision(v["ours"], v["theirs"])
        failures += not check(f"pairing #{i} ({v['note']})", got == v["decision"], f"got {got}")
    # Omission must never refuse — the property that keeps the unmodified reference peer, which
    # declares neither field, playable. Asserted as a property over every case rather than by
    # filtering for the silent ones: a peer that declared nothing is playable against ANY
    # declaration, in either direction.
    failures += not check(
        "omission is never refusal, in either direction",
        all(ref_pairing_decision(v["ours"], {}) == "play"
            and ref_pairing_decision({}, v["theirs"]) == "play"
            for v in pd["refusal_rule"]))
    # Both fields must be independently capable of refusing, or one of them is decoration.
    reasons = {v["decision"] for v in pd["refusal_rule"]}
    failures += not check("both fields can refuse, and refusals name which",
                          {"refuse:sub_game", "refuse:role"} <= reasons)

    ud = _section("uid_declaration.json")
    for i, v in enumerate(ud["refusal_rule"]):
        got = ref_uid_declaration_decision(v["ours"], v["theirs"])
        failures += not check(f"uid decl #{i} ({v['note'][:58]})", got == v["decision"], f"got {got}")
    failures += not check(
        "omission is never refusal (uid declaration)",
        all(ref_uid_declaration_decision(v["ours"], None) == "play"
            and ref_uid_declaration_decision(None, v["theirs"]) == "play"
            for v in ud["refusal_rule"]))
    # The worked example is the whole point: two VALID uids from one derivation over two inputs.
    we = ud["worked_example"]
    failures += not check(
        "the wrong input yields a different, equally valid uid",
        we["from_flat_terms"] != we["from_a_wider_config"] and we["identical"] is False)
    # And that the "right" one really is the section-4 derivation over the flat set, rather than
    # a value the fixture asserts about itself.
    a, b = we["group_ids"]
    failures += not check(
        "the right uid is the section-4 derivation over the flat terms",
        ref_game_uid(we["flat_terms"], a, b) == we["from_flat_terms"])
    failures += not check(
        "the wrong uid is the SAME derivation over a wider object",
        ref_game_uid(we["wider_config"], a, b) == we["from_a_wider_config"])
    failures += not check(
        "the flat set is the signed 14 keys",
        len(we["flat_terms"]) == 14
        and set(we["flat_terms"]) == set(_load("terms_signature.json")["vectors"][0]["terms"]))

    sb = _section("smell_binding.json")
    for i, v in enumerate(sb["digest"]["vectors"]):
        got = ref_smell_grid_sha256(v["grid"])
        failures += not check(f"grid digest #{i} ({v['note'][:58]})", got == v["sha256"], f"got {got}")
    # The empty grid is an INPUT with a real digest, not a gap. A bound sender that transmits
    # nothing seals this value, and its audit passes — which is what makes the binding inert
    # rather than broken under a nothing-on-the-wire arrangement.
    failures += not check(
        "the empty grid has a real digest, and it is the digest of `{}`",
        any(v["grid"] == {} and v["sha256"] == hashlib.sha256(b"{}").hexdigest()
            for v in sb["digest"]["vectors"]))
    # Grid keys are strings, so canonical JSON sorts them lexicographically. Pinned as a property
    # rather than as a value: a numeric sort is the one way two correct implementations disagree.
    wide = {"2,3": 0.9, "10,1": 0.3}
    failures += not check(
        "grid keys sort lexicographically, so '10,1' precedes '2,3'",
        _canonical_str(wide).index('"10,1"') < _canonical_str(wide).index('"2,3"')
        and ref_smell_grid_sha256(wide) == ref_smell_grid_sha256({"10,1": 0.3, "2,3": 0.9}))
    sr = sb["sealed_record"]
    got_unbound = ref_commit(sr["unbound"]["record"], sr["nonce"])
    got_bound = ref_commit(sr["bound"]["record"], sr["nonce"])
    failures += not check(
        "the sealed record commits under the unchanged section-3 construction",
        got_unbound == sr["unbound"]["commit"] and got_bound == sr["bound"]["commit"])
    # If adding the key left the commit where it was, the grid would be bound to nothing.
    failures += not check(
        "adding the binding key MOVES the commit — the grid is really bound",
        got_unbound != got_bound and sr["commit_moves"] is True)
    failures += not check(
        "the sealed digest is the digest of the transmitted grid",
        sr["bound"]["record"]["smell_grid_sha256"] == ref_smell_grid_sha256(sr["grid"])
        and ref_bind_record(sr["unbound"]["record"], sr["grid"]) == sr["bound"]["record"])
    for i, v in enumerate(sb["audit_rule"]):
        got = ref_binding_audit(v["sealed_record"], v["archived_grid"])
        failures += not check(f"binding audit #{i} ({v['note'][:56]})", got == v["verdict"], f"got {got}")
    # Omission is playable here too: a peer that seals no digest is `unbound`, never a failure —
    # the same property section 7's refusal table and section 7.2's pairing table both carry.
    failures += not check(
        "an unbound peer is never failed by the binding",
        all(ref_binding_audit({k: val for k, val in v["sealed_record"].items()
                               if k != "smell_grid_sha256"}, v["archived_grid"]) == "unbound"
            for v in sb["audit_rule"]))
    # The declaration rides the same mechanism as the other three families, or it is a new one.
    lm_names = {e["doc"]["name"] for e in lm["registered"] if e["doc"]["family"] == "smell_binding"}
    failures += not check(
        "both binding registrations exist under the section-7 schema",
        set(sb["declaration"]["registered"]) == lm_names
        and all(e["declared_as"] == sb["declaration"]["declared_key"]
                for e in lm["registered"] if e["doc"]["family"] == "smell_binding"))

    dc = _section("delivery_contract.json")
    for i, v in enumerate(dc["arrivals"]):
        got = ref_delivery_decision(dc["state"], v["arrival"])
        failures += not check(f"delivery #{i} ({v['note'][:60]})", got == v["decision"], f"got {got}")
    # The load-bearing distinction: same commit absorbs, a DIFFERENT commit for a played step is
    # equivocation. A receiver keyed on (kind, step) collapses both and loses the evidence.
    by_dec = {v["decision"] for v in dc["arrivals"]}
    failures += not check("redelivery absorbs but equivocation stays loud",
                          {"absorb", "equivocation"} <= by_dec)
    nw = dc["no_reorder_window"]
    got = ref_delivery_decision(nw["state"], nw["arrival"])
    failures += not check("no reorder window turns a retry race into a violation",
                          got == nw["decision"] == "violation", f"got {got}")
    for i, v in enumerate(dc["deadline_rule"]):
        got = ref_deadline_decision(v["deadline_at"], v["now"], v["arrived"], v["tolerated"])
        failures += not check(f"deadline #{i} ({v['note'][:60]})", got == v["decision"], f"got {got}")
    # Tolerated traffic must not buy the sender time: same clock, same verdict either way.
    failures += not check(
        "tolerated traffic never renews the deadline",
        ref_deadline_decision(100.0, 99.0, True, True) == ref_deadline_decision(100.0, 99.0, False, False)
        and ref_deadline_decision(100.0, 100.0, True, True) == "expired")

    tm = _section("turn_message.json")
    for i, v in enumerate(tm["validation"]):
        got = ref_turn_validate(v["message"])
        failures += not check(f"turn validation #{i} ({v['note'][:58]})",
                              got == v["verdict"], f"got {got}")
    # The two halves that make this fixture worth having: unknown keys must pass (or the wire
    # can never be extended) and missing required keys must not (or a receiver invents a move
    # the sender never sealed). Asserted as a property, not left to the rows above.
    accepted = [v for v in tm["validation"] if v["verdict"] == "accept"]
    failures += not check("an unknown key is tolerated",
                          any("unknown_field" in v["message"] for v in accepted))
    failures += not check("a missing required key is refused",
                          all(ref_turn_validate({k: val for k, val in accepted[0]["message"].items()
                                                 if k != req}) != "accept"
                              for req in TURN_REQUIRED))
    # The tool surface is the thing best2934 could not find (issue #45): assert the fixture and
    # the `wire_shape: reference-v3` locked document name the SAME four tools, so the two places
    # a team might look can never disagree.
    wire_doc = next(e["doc"] for e in lm["registered"]
                    if e["doc"]["family"] == "wire_shape" and e["doc"]["name"] == "reference-v3")
    failures += not check("fixture and reference-v3 lock doc agree on the tool surface",
                          set(tm["tools"]) == set(wire_doc["params"]["tools"]),
                          f'fixture {sorted(tm["tools"])} vs doc {sorted(wire_doc["params"]["tools"])}')
    failures += not check("negotiate, receive_turn and submit_audit are all REQUIRED",
                          all(tm["tools"][name].startswith("REQUIRED")
                              for name in ("negotiate", "receive_turn", "submit_audit")))
    failures += not check("receive_control is OPTIONAL",
                          tm["tools"]["receive_control"].startswith("OPTIONAL"))

    sb = _section("scent_book_v3.json")
    rho = sb["field_walk"]["rho"]
    peak = sb["field_walk"]["center_intensity"]
    board = sb["field_walk"]["board_size"]
    failures += not check("kernel matches book figure 4 verbatim",
                          sb["kernel"] == [list(r) for r in BOOK_KERNEL])
    failures += not check("model doc hashes as registered",
                          ref_lock_hash(sb["model"]) == next(
                              e["sha256"] for e in lm["registered"]
                              if e["doc"]["name"] == sb["model"]["name"]))
    for i, v in enumerate(sb["emit"]):
        got = ref_book_full_turn({}, v["center"], rho, peak, board)
        failures += not check(f"book emit #{i} ({v['note']})", got == v["field"], f"got {got}")
    for name in ("pure_decay", "clamp"):
        v = sb["scalar_traces"][name]
        got = ref_book_update(v["tau"], v["delta"], rho, peak)
        failures += not check(f"scalar trace {name}", got == v["after"], f"got {got!r}")
    tau = 0.0
    for i, s in enumerate(sb["scalar_traces"]["chain"]["steps"]):
        tau = ref_book_update(tau, s["delta"], rho, peak)
        failures += not check(f"chain turn {i + 1}", tau == s["tau"], f"got {tau!r}")
    fork = ref_book_update(sb["scalar_traces"]["chain"]["steps"][1]["tau"], 0.14, rho, peak)
    failures += not check("chain fork (delta 0.14)",
                          fork == sb["scalar_traces"]["chain"]["fork_at_turn_3_with_delta_0_14"])
    field: dict = {}
    for v in sb["field_walk"]["turns"]:
        field = ref_book_full_turn(field, v["center"], rho, peak, board)
        failures += not check(f"field walk turn {v['turn']}", field == v["field"])
    # The two named scent models must NOT agree — that is why they are two registrations.
    dv = sb["divergence_vs_reference"]
    ref_field = ref_smell_emit(dv["center"], 0.9, 5, board)
    book_field = ref_book_full_turn({}, dv["center"], rho, peak, board)
    ok = (ref_field == dv["subtractive_chebyshev_v1"] and book_field == dv["multiplicative_book_v1"]
          and ref_field != book_field and dv["identical"] is False)
    failures += not check("named models pinned + observably different", ok)
    # The kernel is pinned verbatim BECAUSE a fitted Gaussian is not safely reproducible.
    # RECOMPUTED, not read back: an earlier revision of this check trusted the fixture's own
    # stored booleans — "a value the fixture asserts about itself", the exact pattern refused
    # elsewhere in this file (found by anrbj666's 2026-08-04 audit). Each probe sigma is now
    # re-expanded into the 5x5 Gaussian, quantized per its mode, and compared against the
    # printed kernel here — and cross-checked: each sigma must FAIL under the other mode's
    # quantization, which is what "the windows are disjoint" actually claims.
    probe = sb["closed_form_probe"]
    kernel = sb["kernel"]

    def _quantized(sigma2: float, mode: str) -> list[list[float]]:
        rows = []
        for i in range(5):
            row = []
            for j in range(5):
                v = 0.9 * math.exp(-((i - 2) ** 2 + (j - 2) ** 2) / (2 * sigma2))
                row.append(round(v, 2) if mode == "round" else math.floor(v * 100) / 100)
            rows.append(row)
        return rows

    s_round = probe["round"]["sigma_squared"]
    s_trunc = probe["trunc"]["sigma_squared"]
    failures += not check(
        "closed-form probe RECOMPUTES: each sigma reproduces the kernel under its own "
        "quantization and fails under the other's, windows disjoint",
        _quantized(s_round, "round") == kernel
        and _quantized(s_trunc, "trunc") == kernel
        and _quantized(s_round, "trunc") != kernel
        and _quantized(s_trunc, "round") != kernel
        and probe["windows"]["round"][1] < probe["windows"]["trunc"][0])
    op = sb["ordering_probe"]
    ok = any(not c["equal"] for c in op["cases"]) and all(
        ((1 - rho) * c["tau"] + c["delta"] == c["pinned_order"])
        and (c["tau"] - rho * c["tau"] + c["delta"] == c["alternative_order"])
        for c in op["cases"])
    failures += not check("ordering probe: evaluation order is load-bearing", ok)

    for i, v in enumerate(_section("joint_seed.json")["vectors"]):
        ok = (
            ref_share_commit(v["share_group_1"]) == v["commit_group_1"]
            and ref_share_commit(v["share_group_2"]) == v["commit_group_2"]
            and ref_joint_seed(v["share_group_1"], v["share_group_2"]) == v["seed"]
        )
        failures += not check(f"joint seed #{i}", ok)

    for i, v in enumerate(_section("derive_starts.json")["vectors"]):
        cop, thief, draws = ref_derive_starts(v["seed"], v["index"], v["n"])
        ok = cop == v["cop"] and thief == v["thief"] and draws == v["draws"]
        failures += not check(f"starts #{i} n={v['n']} index={v['index']}", ok, f"got {cop},{thief},{draws}")

    # The roster and totals are derived from what actually ran, so no document has to carry a
    # count that can go stale. Prose links vectors/INDEX.md and quotes this line instead.
    counts = {tier: sum(1 for _, t in _ROSTER if t == tier) for tier in _TIER_ORDER}
    composition = ", ".join(f"{n} {tier}" for tier, n in counts.items() if n)
    print(f"\n{_CHECKS} checks across {len(_ROSTER)} fixtures — {composition}")
    print("ALL VECTORS PASS" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
