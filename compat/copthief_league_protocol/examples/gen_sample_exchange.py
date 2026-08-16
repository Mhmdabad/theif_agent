"""Generate examples/sample_exchange.md — a worked exchange with REAL hashes, aligned to the
official book v3.0.0. Every hash is computed by the reference constructions in ``verify_vectors.py``
(stdlib only). Re-run to regenerate; reproduce the hashes with your own implementation to check
conformance on a realistic flow. Inputs are synthetic — no reference content is copied.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from verify_vectors import (  # noqa: E402
    _canonical_str,
    canonical_hash,
    ref_commit,
    ref_game_uid,
    ref_smell_emit,
    ref_terms_signature,
)

OUT = Path(__file__).parent / "sample_exchange.md"

# --- 1. Agreement -------------------------------------------------------------------------
TERMS = {
    "board_size": 7, "smell_grid_size": 5, "decay_per_step": 0.1, "emit_intensity": 0.9,
    "min_center_intensity": 0.5, "max_steps": 35, "barriers_max": 14, "setting": "Haifa",
    "hint_max_words": 15, "axis_origin_corner": "top-left", "axis_start_index": 0,
    "thief_start": [3, 3], "cop_start": [0, 0], "num_games": 1,
}
GROUP_A, GROUP_B = "team-aleph", "team-bet"
NONCE_A, NONCE_B = "aaaa1111bbbb2222cccc3333dddd4444", "5555eeee6666ffff7777000088889999"
SIG_A = ref_terms_signature(TERMS, NONCE_A)
SIG_B = ref_terms_signature(TERMS, NONCE_B)
GAME_UID = ref_game_uid(TERMS, GROUP_A, GROUP_B)

# --- 2. The thief's own sealed step records (commit-reveal) --------------------------------
STEP1 = {
    "step": 1, "state": "grid=7x7;self=[4, 3];barriers=[]", "position": [4, 3],
    "move": "MOVE:S", "intent": "truth", "hint": "I keep to the main avenues.",
}
STEP2 = {
    "step": 2, "state": "grid=7x7;self=[4, 2];barriers=[]", "position": [4, 2],
    "move": "MOVE:W", "intent": "lie", "hint": "אני ליד הנמל",  # "I'm near the harbour" — a bluff
}
NONCE_1, NONCE_2 = "112233445566778899aabbccddeeff00", "00ffeeddccbbaa998877665544332211"
COMMIT_1, COMMIT_2 = ref_commit(STEP1, NONCE_1), ref_commit(STEP2, NONCE_2)

# The scent the thief emits from [4, 2] this step (only value>0 crosses the wire).
SMELL = ref_smell_emit([4, 2], 0.9, 5, 7)

# --- 3. The MCP turn message the opponent receives (commit only; hint in free prose) -------
TURN2 = {
    "step": 2, "sender": "thief", "hint": STEP2["hint"], "smell_grid": SMELL,
    "commit": COMMIT_2, "capture_claim": None, "claim_response": None, "win_claim": None,
}

# --- pitfall demo -------------------------------------------------------------------------
ESCAPED = hashlib.sha256(
    (json.dumps(STEP2, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "|" + NONCE_2)
    .encode()
).hexdigest()

# --- 5. Settlement ------------------------------------------------------------------------
REPORT = {"game_uid": GAME_UID, "result": "capture", "winner_role": "police",
          "scores": {"team-aleph": 20, "team-bet": 5}, "first_meeting_between_groups": True}
REPORT_SHA = canonical_hash(REPORT)

md = f"""# Worked example — agreement, sealed steps, audit, settlement (book v3.0.0)

**Every hash below is real**, computed by the reference constructions in `verify_vectors.py`
(stdlib only). Re-run `gen_sample_exchange.py` to regenerate; reproduce the hashes with your own
implementation to check conformance on a realistic flow. This is not the game — see the book
(ch. references in `SPEC.md`). Inputs are synthetic; no reference content is copied.

Scenario: `{GROUP_A}` and `{GROUP_B}` agree terms, then the thief plays two hidden-position steps
and seals each under commit-reveal. Positions are never sent — only commits and scent.

## 1. Agreement and shared id (SPEC §4)

Both peers hold byte-identical `terms` (the must-match subset of `config/game.json`):

```json
{json.dumps(TERMS, indent=2, ensure_ascii=False)}
```

Each signs `SHA256(canonical_json(terms) | nonce)` with its own nonce; the opponent re-verifies
over the same terms. Note the float `0.1` in the canonical string — a language that emitted
`0.10000000000000001` would fail this gate and could not play:

```
canonical(terms) = {_canonical_str(TERMS)}
{GROUP_A} nonce   = {NONCE_A}
{GROUP_A} sig     = {SIG_A}
{GROUP_B} nonce   = {NONCE_B}
{GROUP_B} sig     = {SIG_B}
```

Both derive the same `game_uid` from shared inputs — no round-trip (sorted group ids, so order
does not matter):

```
game_uid = UUID(SHA256(canonical(terms) | "{GROUP_A}|{GROUP_B}")[:16])
         = {GAME_UID}
```

## 2. The thief's sealed steps (SPEC §3, commit-reveal)

Each step the thief seals its true record and sends **only** the commit; the nonce is revealed at
the end-of-game audit. `commit = SHA256(canonical_json(payload) | nonce)` — the nonce is
pipe-appended to the canonical string, not inside the object.

Step 1 (honest hint):

```json
{json.dumps(STEP1, indent=2, ensure_ascii=False)}
```
```
nonce  = {NONCE_1}
commit = {COMMIT_1}
```

Step 2 (a bluff — a Hebrew hint, `intent: "lie"`):

```json
{json.dumps(STEP2, indent=2, ensure_ascii=False)}
```
```
nonce  = {NONCE_2}
commit = {COMMIT_2}
```

The scent the thief emits from `[4, 2]` this step (radial, centre 0.9; only value > 0 is sent):

```json
{json.dumps(SMELL, indent=2, ensure_ascii=False)}
```

## 3. The MCP turn message the cop receives

Carried as arguments of an MCP tool call — the free-language `hint` (which the cop's LLM may read
and distrust), the emitted `smell_grid`, and the **commit only** (no position):

```json
{json.dumps(TURN2, indent=2, ensure_ascii=False)}
```

## 4. End-of-game audit (cross-team)

At audit both sides reveal all `(payload, nonce)` records; the **opponent** re-hashes each with its
own serializer and must reproduce the commit. Re-hashing the thief's revealed step 2 with the
correct canonical form (`ensure_ascii=False`) gives back `{COMMIT_2[:24]}...` — audit passes.

**The pitfall this kit exists for:** an implementation that hashed the same step with
`ensure_ascii=True` (escaping `אני ליד הנמל` to `\\uXXXX`) would compute

```
{ESCAPED}
```

— a different hash. The cop's audit of the thief's log would flag step 2 as tampering, and the
sub-game would be a **technical loss for both**. `vectors/commit_reveal.json` (case #2) pins this.

## 5. Settlement (SPEC §6)

Both teams build the same result JSON, canonicalize (§2), and email the **exact canonical bytes**
that were hashed — never a re-serialization (graders compare emails):

```json
{json.dumps(REPORT, indent=2, ensure_ascii=False)}
```
```
report canonical = {_canonical_str(REPORT)}
report_sha       = {REPORT_SHA}
```

Both email a byte-identical body only after agreeing; totals are derived from the sub-game results
and the game-count declaration, and the send stays a draft until a deliberate human send (so an
accidental early send never burns the one counted game vs this opponent).

## Notes for implementers (and their LLM assistants)

- The `hint` prose is interpreted by the receiving agent's LLM and may lie (step 2 bluffs). The
  commit may not: it is sealed programmatically and re-verified mechanically at audit.
- The `state` string carries **your own** position only (`self=...`) — never the opponent's; there
  is no shared board. Its exact form is `grid=NxN;self=[r, c];barriers=[...]` (Python list repr,
  with the space after the comma).
- The one cross-team requirement is the canonical form (§2): `sort_keys=True`,
  `ensure_ascii=False`, `separators=(",", ":")`. Get that right and your audits pass; get it wrong
  and you lose matches to false tamper flags.
"""

OUT.write_text(md, encoding="utf-8")
print(f"wrote {OUT.name} ({len(md)} chars); game_uid={GAME_UID}, commit2={COMMIT_2[:16]}...")
