# Worked example — agreement, sealed steps, audit, settlement (book v3.0.0)

**Every hash below is real**, computed by the reference constructions in `verify_vectors.py`
(stdlib only). Re-run `gen_sample_exchange.py` to regenerate; reproduce the hashes with your own
implementation to check conformance on a realistic flow. This is not the game — see the book
(ch. references in `SPEC.md`). Inputs are synthetic; no reference content is copied.

Scenario: `team-aleph` and `team-bet` agree terms, then the thief plays two hidden-position steps
and seals each under commit-reveal. Positions are never sent — only commits and scent.

## 1. Agreement and shared id (SPEC §4)

Both peers hold byte-identical `terms` (the must-match subset of `config/game.json`):

```json
{
  "board_size": 7,
  "smell_grid_size": 5,
  "decay_per_step": 0.1,
  "emit_intensity": 0.9,
  "min_center_intensity": 0.5,
  "max_steps": 35,
  "barriers_max": 14,
  "setting": "Haifa",
  "hint_max_words": 15,
  "axis_origin_corner": "top-left",
  "axis_start_index": 0,
  "thief_start": [
    3,
    3
  ],
  "cop_start": [
    0,
    0
  ],
  "num_games": 1
}
```

Each signs `SHA256(canonical_json(terms) | nonce)` with its own nonce; the opponent re-verifies
over the same terms. Note the float `0.1` in the canonical string — a language that emitted
`0.10000000000000001` would fail this gate and could not play:

```
canonical(terms) = {"axis_origin_corner":"top-left","axis_start_index":0,"barriers_max":14,"board_size":7,"cop_start":[0,0],"decay_per_step":0.1,"emit_intensity":0.9,"hint_max_words":15,"max_steps":35,"min_center_intensity":0.5,"num_games":1,"setting":"Haifa","smell_grid_size":5,"thief_start":[3,3]}
team-aleph nonce   = aaaa1111bbbb2222cccc3333dddd4444
team-aleph sig     = d6850d74fef0c3f80861b8f6a67e6047c46d5ed1b0043df5b6bf2985adad1e8b
team-bet nonce   = 5555eeee6666ffff7777000088889999
team-bet sig     = 531d979076517b313ca56384a29b540c0a3ced2260240bfbaa1e05e969be8121
```

Both derive the same `game_uid` from shared inputs — no round-trip (sorted group ids, so order
does not matter):

```
game_uid = UUID(SHA256(canonical(terms) | "team-aleph|team-bet")[:16])
         = 1e73c318-5b29-4a7b-1c60-ecb8286265f0
```

## 2. The thief's sealed steps (SPEC §3, commit-reveal)

Each step the thief seals its true record and sends **only** the commit; the nonce is revealed at
the end-of-game audit. `commit = SHA256(canonical_json(payload) | nonce)` — the nonce is
pipe-appended to the canonical string, not inside the object.

Step 1 (honest hint):

```json
{
  "step": 1,
  "state": "grid=7x7;self=[4, 3];barriers=[]",
  "position": [
    4,
    3
  ],
  "move": "MOVE:S",
  "intent": "truth",
  "hint": "I keep to the main avenues."
}
```
```
nonce  = 112233445566778899aabbccddeeff00
commit = aa6420e2d3a907d6c140856caecbb351b4d5ad98e381549c28268669af378dcc
```

Step 2 (a bluff — a Hebrew hint, `intent: "lie"`):

```json
{
  "step": 2,
  "state": "grid=7x7;self=[4, 2];barriers=[]",
  "position": [
    4,
    2
  ],
  "move": "MOVE:W",
  "intent": "lie",
  "hint": "אני ליד הנמל"
}
```
```
nonce  = 00ffeeddccbbaa998877665544332211
commit = e40a0f60590223a3e1acad70fc96e1adda70d2c5e26093735e1ac051435a06fe
```

The scent the thief emits from `[4, 2]` this step (radial, centre 0.9; only value > 0 is sent):

```json
{
  "2,0": 0.3,
  "2,1": 0.3,
  "2,2": 0.3,
  "2,3": 0.3,
  "2,4": 0.3,
  "3,0": 0.3,
  "3,1": 0.6,
  "3,2": 0.6,
  "3,3": 0.6,
  "3,4": 0.3,
  "4,0": 0.3,
  "4,1": 0.6,
  "4,2": 0.9,
  "4,3": 0.6,
  "4,4": 0.3,
  "5,0": 0.3,
  "5,1": 0.6,
  "5,2": 0.6,
  "5,3": 0.6,
  "5,4": 0.3,
  "6,0": 0.3,
  "6,1": 0.3,
  "6,2": 0.3,
  "6,3": 0.3,
  "6,4": 0.3
}
```

## 3. The MCP turn message the cop receives

Carried as arguments of an MCP tool call — the free-language `hint` (which the cop's LLM may read
and distrust), the emitted `smell_grid`, and the **commit only** (no position):

```json
{
  "step": 2,
  "sender": "thief",
  "hint": "אני ליד הנמל",
  "smell_grid": {
    "2,0": 0.3,
    "2,1": 0.3,
    "2,2": 0.3,
    "2,3": 0.3,
    "2,4": 0.3,
    "3,0": 0.3,
    "3,1": 0.6,
    "3,2": 0.6,
    "3,3": 0.6,
    "3,4": 0.3,
    "4,0": 0.3,
    "4,1": 0.6,
    "4,2": 0.9,
    "4,3": 0.6,
    "4,4": 0.3,
    "5,0": 0.3,
    "5,1": 0.6,
    "5,2": 0.6,
    "5,3": 0.6,
    "5,4": 0.3,
    "6,0": 0.3,
    "6,1": 0.3,
    "6,2": 0.3,
    "6,3": 0.3,
    "6,4": 0.3
  },
  "commit": "e40a0f60590223a3e1acad70fc96e1adda70d2c5e26093735e1ac051435a06fe",
  "capture_claim": null,
  "claim_response": null,
  "win_claim": null
}
```

## 4. End-of-game audit (cross-team)

At audit both sides reveal all `(payload, nonce)` records; the **opponent** re-hashes each with its
own serializer and must reproduce the commit. Re-hashing the thief's revealed step 2 with the
correct canonical form (`ensure_ascii=False`) gives back `e40a0f60590223a3e1acad70...` — audit passes.

**The pitfall this kit exists for:** an implementation that hashed the same step with
`ensure_ascii=True` (escaping `אני ליד הנמל` to `\uXXXX`) would compute

```
3aafa814229a5b302030701d5a5b885bd8b8d5316c3e05f45009e200f2671d18
```

— a different hash. The cop's audit of the thief's log would flag step 2 as tampering, and the
sub-game would be a **technical loss for both**. `vectors/commit_reveal.json` (case #2) pins this.

## 5. Settlement (SPEC §6)

Both teams build the same result JSON, canonicalize (§2), and email the **exact canonical bytes**
that were hashed — never a re-serialization (graders compare emails):

```json
{
  "game_uid": "1e73c318-5b29-4a7b-1c60-ecb8286265f0",
  "result": "capture",
  "winner_role": "police",
  "scores": {
    "team-aleph": 20,
    "team-bet": 5
  },
  "first_meeting_between_groups": true
}
```
```
report canonical = {"first_meeting_between_groups":true,"game_uid":"1e73c318-5b29-4a7b-1c60-ecb8286265f0","result":"capture","scores":{"team-aleph":20,"team-bet":5},"winner_role":"police"}
report_sha       = f5a15f2875c0f78fbaa9422c539d85b2a09320a3dc6685e6820efc95d2aa6167
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
