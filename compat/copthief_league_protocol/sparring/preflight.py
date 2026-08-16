"""The startup gate: rules armed, no deliverable owed.

**This gate may assert anything about the RULES and nothing about a DELIVERABLE.** That sentence
is the contract, and it is enforced rather than remembered — ``guards/no_mail.py`` rule NM-7
fails the build if this module so much as mentions a destination, a credential, or a settlement
signature.

The distinction matters because a rehearsal mode that demanded a deliverable report would make a
sparring host refuse itself at startup: sparring is the one legitimate state where the whole
rulebook is armed and *nothing is owed*.

What it does assert:

1. the App. F binding table — fixed values immovable, minimums raisable only;
2. the signed terms round-trip, and both match ids derive and are stable;
3. **the kit's own vectors pass in this Python** — a runtime whose float repr or non-ASCII
   handling is off should never reach a wire;
4. no mail surface exists (and the manifest hash goes into the declaration artifact);
5. the structural checks in ``guards/purity.py``.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import dataclass

from sparring import kitref
from sparring.config import BINDING, TERMS_KEYS, RunMode, SparConfig
from sparring.guards import no_mail, purity
from sparring.rules.scent import MODELS


class PreflightRefused(Exception):
    """Raised with every problem at once — a configuration is fixed in one pass or not at all."""


@dataclass(frozen=True)
class PreflightReport:
    mail_scan_sha256: str
    vectors_passed: bool
    checks: int


def _binding_problems(cfg: SparConfig) -> list[str]:
    out: list[str] = []
    values = {**cfg.terms(), "num_agents": 2, "survival_threshold": cfg.survival_threshold}
    for key, (status, example) in BINDING.items():
        got = values.get(key)
        if got is None:
            continue
        if status == "fixed" and got != example:
            out.append(f"{key}={got!r} but App. F fixes it at {example!r} — a fixed value may not "
                       f"move at all; deviation disqualifies the team")
        elif status == "minimum" and isinstance(got, (int, float)) and got < example:
            out.append(f"{key}={got!r} is below App. F's minimum {example!r} — minimums may be "
                       f"raised by mutual agreement, never lowered")
    return out


def assert_sparring_ready(cfg: SparConfig, *, check_vectors: bool = True) -> PreflightReport:
    problems: list[str] = []

    if cfg.mode is not RunMode.SPARRING:
        problems.append(f"unknown run mode {cfg.mode!r}")

    problems.extend(_binding_problems(cfg))

    terms = cfg.terms()
    missing = sorted(set(TERMS_KEYS) - set(terms))
    extra = sorted(set(terms) - set(TERMS_KEYS))
    if missing or extra:
        problems.append(f"the signed terms must be exactly the 14 keys; missing={missing} "
                        f"unexpected={extra}")

    if cfg.scent_model not in MODELS:
        problems.append(f"unknown scent model {cfg.scent_model!r}; expected one of {MODELS}")

    # Both ids must derive, and derive stably. Cheap here; expensive to discover at settlement.
    nonce = "0" * 32
    sig = kitref.terms_signature(terms, nonce)
    if sig != kitref.terms_signature(terms, nonce):
        problems.append("the terms signature is not stable across two computations")
    uid_a = kitref.game_uid(terms, cfg.group_id, "peer")
    uid_b = kitref.game_uid(terms, "peer", cfg.group_id)
    if uid_a != uid_b:
        problems.append("game_uid is not order-independent — the pair must sort (SPEC section 4)")
    if kitref.game_id(cfg.group_id, "peer") != kitref.game_id("peer", cfg.group_id):
        problems.append("game_id is not order-independent — sort the pair, never name self first")

    try:
        scan = no_mail.assert_absent()
    except no_mail.Violation as exc:
        problems.append(str(exc))
        scan = ""

    try:
        purity.assert_pure()
    except AssertionError as exc:
        problems.append(str(exc))

    checks = 0
    passed = True
    if check_vectors:
        # The kit's checker prints a full roster; swallow it here and keep only the verdict.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = kitref.verify_core_vectors()
        passed = rc == 0
        # Count the per-check lines only — the trailing "ALL VECTORS PASS" is a verdict, not a
        # check, and counting it would overstate by one.
        checks = sum(1 for ln in buf.getvalue().splitlines() if ln.startswith("  PASS"))
        if not passed:
            problems.append(
                "the kit's own vectors do not reproduce in this Python. Something about this "
                "runtime's JSON — float repr, or ensure_ascii handling — differs from the pinned "
                "form, and a peer that reaches a wire in that state fails its opponent's audit "
                "and zeroes both sides. Run `python verify_vectors.py` to see which.")

    if problems:
        raise PreflightRefused("sparring preflight refused:\n  " + "\n  ".join(problems))

    return PreflightReport(mail_scan_sha256=scan, vectors_passed=passed, checks=checks)
