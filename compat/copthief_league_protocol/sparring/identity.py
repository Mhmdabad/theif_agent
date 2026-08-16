"""The locked-model docs this peer declares (SPEC section 7).

The doc never crosses the wire — only its hash does, as ``"<family>_sha256"`` in the negotiate
extras. The doc's *field set* is what has to agree, which is the whole reason the kit pins a
schema: two teams implementing the same model from the same spec will still declare different
hashes if they serialize different fields, and then refuse each other for no reason at all.

These docs are built with ``kitref.lock_doc``, so this peer's declarations are byte-identical to
the kit's registrations — the same hashes a second implementation reproduced on the wire during a
real cross-team series.
"""

from __future__ import annotations

from sparring import kitref
from sparring.rules.scent import BOOK_MODEL, REFERENCE_MODEL


def scent_doc(model: str) -> dict:
    if model == BOOK_MODEL:
        return kitref.lock_doc("scent_model", BOOK_MODEL, {
            "field_size": 5, "center_intensity": 0.9, "decay_rho": 0.1,
            "kernel": [list(r) for r in kitref.BOOK_KERNEL],
            "kernel_source": "book v3.0.0 figure 4 — printed values, verbatim lookup",
            "decay": "multiplicative",
            "update": "tau' = clamp((1 - rho) * tau + kernel_delta, 0, center_intensity)",
            "evaluation_order": "(1 - rho) * tau + delta, then clamp",
            "rounding_decimals": None, "clamp": [0.0, 0.9],
            "cadence": "per_full_turn", "order": "decay_then_deposit",
            "receiver_side_decay": False, "initial_field": "empty",
            "transmitted": False,
        }, {
            "note": "the clamp case: a saturated cell decays, then takes an adjacent deposit",
            "tau": 0.9, "delta": 0.62,
            "raw": (1 - 0.1) * 0.9 + 0.62,
            "clamped": 0.9,
        })
    return kitref.lock_doc("scent_model", REFERENCE_MODEL, {
        "field_size": 5, "emit_intensity": 0.9, "min_center_intensity": 0.5,
        "distance": "chebyshev", "falloff": "linear",
        "falloff_step": "emit_intensity / (field_size // 2 + 1)",
        "decay": "subtractive", "decay_per_step": 0.1,
        "update": "tau' = round(max(0, tau - decay_per_step), 3)",
        "rounding_decimals": 3, "clamp": [0.0, None],
        "cadence": "per_full_turn", "order": "deposit_then_decay",
        "receiver_side_decay": True, "initial_field": "empty",
        "transmitted": True,
    }, {
        "note": "emit at the centre of a 7x7 board, then one decay",
        "emit_center": [3, 3],
        "emit_field": kitref.smell_emit([3, 3], 0.9, 5, 7),
        "after_one_decay": kitref.smell_decay(kitref.smell_emit([3, 3], 0.9, 5, 7), 0.1),
    })


def wire_doc() -> dict:
    """``reference-v3`` — the only shape this peer speaks.

    ``bookletter-v3`` is detected and refused rather than supported: SPEC section 7 records four
    of its preimages as still unpinned, so a peer claiming to speak it would be claiming to bind
    what the kit says is not bound.
    """
    return kitref.lock_doc("wire_shape", "reference-v3", {
        "tools": ["negotiate", "receive_turn", "submit_audit", "receive_control"],
        "messages_per_half_turn": 1,
        "smell_grid_on_wire": True,
        "move_revealed": "at_audit",
        "replicated_engines": False,
        "phases": "all four of book ch.5, with Reveal deferred to the audit boundary",
        "rival_position_computable_live": False,
    }, {
        "note": "one turn message per half-turn; the move is sealed, the field is sent",
        "turn_message_keys": ["step", "commit", "hint", "smell_grid", "barrier_placed"],
    })


def info_mode_doc() -> dict:
    """``info_mode: belief`` — the registered doc, mirrored byte-exactly.

    This field set must match the kit's own registration in ``vectors/locked_model.json`` (the
    ``belief`` entry, PROMOTED 2026-08-04), because the hash is what crosses the wire and
    both-declare-and-differ refuses. ``test_wire_contract`` asserts the equality, so a drift
    between this copy and the registration fails in CI rather than at a handshake.
    """
    return kitref.lock_doc("info_mode", "belief", {
        "rival_position_in_observation": False,
        "sources": ["own_state", "rival_scent", "hints"],
        "enforcement": ("structural under wire_shape reference-v3 (the rival's position "
                        "never crosses the wire); an honor term under bookletter-v3, where "
                        "the wire carries it and only the brain's restraint withholds it"),
        "artifact_provable": {
            "mismatch": True,
            "violation": False,
            "why": "a mismatch is provable from the two negotiate records; a violation is "
                   "not, because a decision record does not disclose which information "
                   "produced it",
        },
    }, {
        "note": "the observation space the brain is entitled to read",
        "observation_keys": ["self", "barriers", "smell_grid", "hint"],
    })


def smell_binding_doc() -> dict:
    """``smell_binding: none`` — the registered doc, mirrored byte-exactly.

    Declaring the UNBOUND state out loud is the registration's whole purpose (SPEC §7.4): a
    silence cannot be told apart from never having heard of the family. Until this mirror
    existed the family was in ``LOCK_FAMILIES`` but ``Negotiation`` had no field for it, so the
    kit's own peer could not declare the fourth family it registers (anrbj666's E13).
    """
    return kitref.lock_doc("smell_binding", "none", {}, {
        "note": "the default and the whole of today's wire: the transmitted grid is "
                "unauthenticated. Registered so that `unbound` is a state a peer can "
                "declare rather than a silence it cannot distinguish from ignorance.",
        "sealed_record_keys_added": [],
    })


def locks(scent_model: str) -> dict[str, str]:
    """The hashes that actually cross the wire."""
    return {
        "scent_model": kitref.lock_hash(scent_doc(scent_model)),
        "wire_shape": kitref.lock_hash(wire_doc()),
        "info_mode": kitref.lock_hash(info_mode_doc()),
        "smell_binding": kitref.lock_hash(smell_binding_doc()),
    }
