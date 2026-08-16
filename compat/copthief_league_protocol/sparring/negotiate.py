"""The pre-game gate, and refusals a stranger can act on without asking us.

Every refusal here names *which* thing is wrong, because the difference decides whose side the fix
is on and how long it takes to find. The distinction that cost a real team two hours:

* **terms absent** — a greeting carrying no ``terms`` at all is a differently-shaped wire arriving
  under a reference wire. A wire-shape fault on the **sender's** side.
* **terms differing** — both sides speak this wire and their constitutions disagree. A config
  fault, and the diff says which key.

They look identical if you only report "handshake failed".

The locked-model and pairing decisions are the kit's own pinned functions
(``kitref.lock_decision``, ``kitref.pairing_decision``), checked against
``vectors/locked_model.json`` and ``vectors/pairing_declaration.json``. Both share one rule worth
restating: **omission never refuses**, in either direction. The unmodified reference peer declares
none of these fields, and a guard that fail-fasts on silence forfeits that game to itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from sparring import KIT_REPO_URL, kitref
from sparring.config import TERMS_KEYS, SparConfig
from sparring.proto.messages import Negotiation


class Refused(Exception):
    """A refusal, with a stable code so an operator can grep for it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Agreed:
    game_id: str
    game_uid: str
    opponent_group: str
    opponent_role: str | None
    terms: dict


def our_greeting(cfg: SparConfig, role: str, sub_game_number: int, nonce: str,
                 locks: dict[str, str], opponent_group: str | None = None) -> Negotiation:
    terms = cfg.terms()
    return Negotiation(
        terms=terms,
        nonce=nonce,
        signature=kitref.terms_signature(terms, nonce),
        group_id=cfg.group_id,
        role=role,
        sub_game_number=sub_game_number,
        identity={"group_id": cfg.group_id, "group_name": cfg.group_name,
                  "llm_model": "template", "mcp_servers": {},
                  "repos": {"cop": KIT_REPO_URL, "thief": KIT_REPO_URL}, "members": []},
        scent_model_sha256=locks.get("scent_model"),
        wire_shape_sha256=locks.get("wire_shape"),
        info_mode_sha256=locks.get("info_mode"),
        smell_binding_sha256=locks.get("smell_binding"),
        info_mode=cfg.info_mode,
        # The uid is a pure function of the terms and the two sorted group ids, so it can only
        # be declared once the opponent is known — sub-game 2 onward, or a configured pairing.
        # Omission never refuses (SPEC section 7.3), so declaring nothing on first contact is
        # legal in both directions.
        game_uid=(kitref.game_uid(terms, cfg.group_id, opponent_group)
                  if opponent_group else None),
    )


def verify_peer(cfg: SparConfig, ours: Negotiation, raw: dict) -> Agreed:
    """Check an inbound greeting, or refuse with a diagnosis."""
    if not isinstance(raw, dict):
        raise Refused("SPAR-N00", f"greeting is {type(raw).__name__}, not an object")

    terms = raw.get("terms")
    if terms is None:
        raise Refused(
            "SPAR-N01",
            "opponent greeting carries no `terms` at all. That is a bookletter-shaped greeting "
            "arriving under a reference wire — a wire-shape fault on the sender's side, not a "
            "constitution disagreement. This wire expects flat terms + nonce + signature "
            f"(SPEC section 4). Keys we did get: {sorted(raw)}")
    if not isinstance(terms, dict):
        raise Refused("SPAR-N02", f"`terms` is {type(terms).__name__}, not an object")

    missing = sorted(set(TERMS_KEYS) - set(terms))
    if missing:
        raise Refused("SPAR-N02", f"opponent terms are incomplete; missing {missing}")

    if terms != ours.terms:
        diff = [f"{k}: ours={ours.terms.get(k)!r} theirs={terms.get(k)!r}"
                for k in sorted(set(ours.terms) | set(terms))
                if ours.terms.get(k) != terms.get(k)]
        raise Refused(
            "SPAR-N03",
            "opponent terms do not value-equal ours — a constitution disagreement, not a wire "
            "fault.\n    " + "\n    ".join(diff) +
            "\n    If the values look identical, compare the canonical strings rather than the "
            "values: a float that differs only in repr is invisible in a diff and fatal to the "
            "signature.\n    ours  : " + kitref.canonical_str(ours.terms) +
            "\n    theirs: " + kitref.canonical_str(terms))

    nonce, signature = raw.get("nonce"), raw.get("signature")
    if not nonce or not signature:
        raise Refused("SPAR-N04", "greeting carries no nonce/signature pair to verify")
    if kitref.terms_signature(terms, nonce) != signature:
        raise Refused(
            "SPAR-N04",
            "the terms signature does not verify. Since the terms themselves matched, the "
            "difference is in the serialization — check `ensure_ascii=False` and the compact "
            "separators (SPEC section 2), the two places a clean-room port silently diverges.")

    # Locked models: refuse only when BOTH declare and disagree (SPEC section 7). A bare-string
    # `info_mode` (the pre-2026-08-01 form) is a different key and never reaches this comparison:
    # a string and a doc hash are uncomparable, and uncomparable is silence.
    for family, theirs_key in (("scent_model", "scent_model_sha256"),
                               ("wire_shape", "wire_shape_sha256"),
                               ("info_mode", "info_mode_sha256"),
                               ("smell_binding", "smell_binding_sha256")):
        ours_hash = getattr(ours, theirs_key)
        if kitref.lock_decision(ours_hash, raw.get(theirs_key)) == "refuse":
            raise Refused(
                "SPAR-N05",
                f"{family} lock mismatch: we declared {ours_hash}, they declared "
                f"{raw.get(theirs_key)}. Both peers declared and the hashes differ, so this is a "
                f"real disagreement about the model — not a missing declaration.")

    # Pairing: same game, complementary sides (SPEC section 7.2).
    mine = {k: v for k, v in (("sub_game_number", ours.sub_game_number), ("role", ours.role))
            if v is not None}
    theirs = {k: raw[k] for k in ("sub_game_number", "role") if k in raw}
    decision = kitref.pairing_decision(mine, theirs)
    if decision == "refuse:sub_game":
        raise Refused(
            "SPAR-N06",
            f"sub-game mismatch: we are playing sub-game {ours.sub_game_number}, they declared "
            f"{theirs.get('sub_game_number')}. One game cannot carry two indices — and the side "
            f"that fails a handshake runs ahead, because a failed handshake ends in seconds while "
            f"a real sub-game takes minutes.")
    if decision == "refuse:role":
        raise Refused(
            "SPAR-N07",
            f"role collision: both peers declared {ours.role!r}. The two sides of a game are "
            f"complementary; two of the same side can only deadlock. Two sparring peers hit "
            f"this whenever both keep the default role — restart exactly one side with "
            f"--role thief.")

    opponent = raw.get("group_id") or (raw.get("identity") or {}).get("group_id")
    if not opponent:
        raise Refused("SPAR-N08", "greeting names no group_id, so no game_id can be derived")

    # The uid declaration (SPEC section 7.3). We always derive; if they also declared, the two
    # derivations must agree — this is the ONLY moment a wrong-input uid can surface before two
    # reports are diffed the next morning, because the uid never crosses the wire again.
    derived_uid = kitref.game_uid(terms, ours.group_id, opponent)
    if kitref.uid_declaration_decision(derived_uid, raw.get("game_uid")) == "refuse":
        raise Refused(
            "SPAR-N10",
            f"game_uid mismatch: we derive {derived_uid} from the flat negotiated terms and the "
            f"sorted group ids; they declared {raw.get('game_uid')}. The terms already "
            f"value-equal, so their uid almost certainly came from a WIDER input than the "
            f"extracted flat terms — deterministic, self-consistent across all four of their "
            f"artifacts, and wrong only cross-team (WARNINGS section 2). Check the input to "
            f"their derive step, not the derivation.")

    return Agreed(
        game_id=kitref.game_id(ours.group_id, opponent),
        game_uid=derived_uid,
        opponent_group=opponent,
        opponent_role=theirs.get("role"),
        terms=terms,
    )
