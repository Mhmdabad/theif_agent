# Cop–Thief League Interop Kit — for the official book v3.0.0

**Status:** aligned to the official assignment — *Distributed Cops-and-Robbers over a Peer-to-Peer
Network*, Dr. Yoram Reuven Segal, **book v3.0.0 / code v3.0.0** (University of Haifa, Orchestration
of AI Agents). This document tracks that release; if the book revises, this follows.

**This is not the game spec — the book is.** The book fixes the transport (MCP/FastMCP), the game
(hidden positions, the pheromone scent, capture, scoring), the commit-reveal, the `config/game.json`
constitution, and the Gmail-API reporting. What this kit adds is the one thing the book does not
ship: **conformance test vectors** for the byte-level constructions two independent implementations
must agree on. Plus a small set of clearly-marked **opt-in enhancements** (Appendix A) a pair of
teams may agree to and sign into their config.

**Why it matters (the one-line version):** the book says "hash the canonical JSON," but two
clean-room codebases that serialize even slightly differently — an escaped `א` vs a native
`א`, a `0.1` vs `0.10000000000000001` — will fail each other's audit, and both score a **technical
loss**. This kit lets you certify, alone and before match day, that your bytes match everyone
else's. Pass `python verify_vectors.py`, port the checks into your own suite, and you can finish a
clean game with any team that did the same.

---

## 0. Relationship to the book

The book is authoritative and self-contained. This kit only *pins bytes* and *proposes optional
extras*. Pointers into the release (chapter numbers are v3.0.0):

| The book fixes… | …so this kit does not restate it |
|---|---|
| MCP tool-call transport over FastMCP + tunneling (ch.2) | — |
| Hidden positions / Zero-Knowledge "local truth" (ch.1, ch.5) | — |
| Stigmergy scent field: emission + decay (ch.4) | pins the math with vectors (§5) |
| Commit-reveal SHA-256, per-step, revealed at audit (ch.5) | pins the serialization with vectors (§3) |
| Strategy is pure code; the LLM only writes the free-language hint (ch.6) | — |
| Fixed scoring + diversity + computational fairness (ch.9, App. F) | — |
| `config/game.json` as the signed shared "constitution" (ch.3, App. B) | pins the signature/id bytes (§4) |
| Gmail-API reporting, both teams send identical JSON (ch.9, App. A) | pins report canonicalization + the emailed-bytes rule (§6) |
| Two GitHub repos + academic README (ch.9, App. C) | — |

Nothing here weakens a mandatory rule. Per the book's own principle ("anything not explicitly
written is open to agreement, but the parameter-table minimums may only be raised, never lowered"),
this kit lives entirely in the "open to agreement" space and in self-certification.

## 1. The interop surface

These are the only places where two independent implementations must produce **byte-identical**
output, or the game cannot start / audit / settle. Each is backed by a vector:

1. **Canonical JSON** (§2) — the serialization under every hash. `vectors/canonical_json.json`.
2. **Commit-reveal** (§3) — your revealed log is re-hashed by the *opponent* at audit.
   `vectors/commit_reveal.json`.
3. **Agreement signature** (§4) — the pre-game gate; a byte difference means the peers refuse to
   play. `vectors/terms_signature.json`.
4. **`game_uid` and `game_id`** (§4) — both peers derive the same two shared ids with no
   round-trip, because both sort the group pair. `vectors/game_uid.json`.
5. **Pheromone field** (§5) — each peer emits its own, but a wrong port breaks your belief map.
   `vectors/pheromone.json`.
6. **Report canonicalization + consensus signature** (§6) — both teams must email byte-identical
   report JSON, and the consensus signature inside it uses a **second (spaced) serialization**.
   `vectors/report_consensus.json`.
7. **Locked-model declarations** (§7) — where the signed terms cannot carry a choice, a pair
   declares the hash of a described model. The doc schema must match or the hashes are not
   comparable. `vectors/locked_model.json`.

Four more places are **behaviour** rather than bytes — a conforming peer answers the same way, and
answering differently costs a game just as surely as a hash mismatch. Three are pinned as truth
tables rather than digests: the locked-model refusal rule (§7, `vectors/locked_model.json`), the
at-least-once receiver contract (§7.1, `vectors/delivery_contract.json`) and the pairing
declaration (§7.2, `vectors/pairing_declaration.json`). The fourth has no vector because it is a
message a peer must **send**: a rule-46/47 ending is visible only to the thief, so a thief that
does not say it forks the game (§3.1).

Everything else (your strategy, your GUI, your prompts, your infra) is private and needs no
cross-team agreement.

## 2. Canonical JSON

Every hash in the protocol is `SHA-256` over the UTF-8 bytes of:

```python
json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
```

Three details are load-bearing, and each is where a clean-room port silently diverges:

- **`ensure_ascii=False` (native UTF-8).** Non-ASCII — Hebrew hints, emoji, non-English map areas —
  is emitted as raw UTF-8, **not** `\uXXXX`-escaped. This is the single most important fact in the
  kit, because of §3: the opponent re-hashes your revealed `hint` text at audit. Escape it and every
  non-ASCII step fails, costing both sides the match. `vectors/canonical_json.json` pins a Hebrew
  string and an astral-plane emoji.
- **Floats are permitted, and must be shortest round-trip repr.** The protocol carries floats
  (`decay_per_step: 0.1`, `emit_intensity: 0.9`, hardware `ram_gb: 31.8`). Python's `json` emits
  the shortest round-trip form (`0.1`, not `0.10000000000000001`); any conforming implementation
  must do the same, or the terms signature (§4) fails. The kit does **not** forbid floats (an
  earlier draft did — that was wrong for this game). It pins the expected canonical strings so you
  can check your language.
- **Sorted keys, no whitespace** (`separators=(",", ":")`). Construction order in your code is
  irrelevant; canonicalization sorts.

Reference: `verify_vectors.py:_canonical_str`.

## 3. Commit-reveal conformance

Each step, a peer seals its own turn record and sends **only** the commit; nonces are revealed at
the end-of-game audit, where both peers re-hash every revealed record. The construction:

```
commit = SHA256( canonical_json(payload) + "|" + nonce )
```

Note the nonce is **pipe-appended to the canonical string**, not placed inside the hashed object.
`vectors/commit_reveal.json`.

> **A contradiction in the book, resolved here** (documented per the book's own academic-freedom
> clause, which requires naming the contradiction and the choice). The v3.0.0 release publishes
> three inconsistent commit constructions: the ch.5 listing seals the nonce **inside** the
> canonical JSON object; the audit-chapter snippet re-hashes `f"{nonce}|{move}"`; and the official
> reference implementation (`domain/crypto.py`) computes `SHA256(canonical(payload)|nonce)`. The
> book's clarification page makes printed listings illustrative and non-binding, and the
> binding-rules layer mandates the *mechanism* (commit-reveal over SHA-256 per step), not the
> preimage — so the choice is formally open. But it is an **interop constraint**: the opponent's
> audit re-hashes your revealed records, so both sides must use the same form or the audit voids
> the match. This kit pins the **reference form** — it is what the lecturer's own tooling runs and
> what most teams will build against. It is also the only one of the three that is
> cryptographically sufficient: the audit-snippet form consumes only `nonce` and `move`, so it
> binds neither `state` nor `intent` — a record's position or bluff verdict could be rewritten
> after the fact without changing that hash. If your commits don't verify, the `divergent_forms`
> entry in `vectors/commit_reveal.json` hashes the same sealed record under all three
> constructions (the audit-snippet form, by its nature, over just the record's `nonce` and
> `move`), so you can identify which one you implemented. A pair that knowingly prefers a
> different form must sign it into `config/game.json` and document it.

- **Self-verify** needs no cross-team agreement — you re-hash your own payloads. **Audit is
  cross-team**: your opponent runs `verify(payload, nonce, commit)` over *your* revealed records,
  canonicalizing them with *their* serializer. If your serializers disagree on any record — and
  records contain your free-language `hint`, which may be Hebrew — their recompute misses your
  commit, the audit flags it as tampering, and the sub-game is a technical loss for both. §2's
  `ensure_ascii=False` is what prevents this.
- **The payload schema itself is not an interop constraint.** Each peer reveals its own full record
  and the other just re-hashes it; you do not reconstruct your opponent's payload. So the exact key
  set (the book's core `{state, move, intent, nonce}` vs. the reference's richer record that also
  carries `verdict`, `hint`, `step`, `sub_game`, `role`, timing, tokens) does not need to match
  across teams — only each side's own seal↔reveal must be self-consistent, and your canonical form
  must be §2. Order enforcement and replay resistance come from `step` (and `sub_game`, `role`)
  being inside the signed payload, not from any transcript chain.
- **`state` is a string, self-only.** The reference encodes it as
  `f"grid={n}x{n};self={[row, col]};barriers={sorted_barriers}"` (Python list repr, note the space
  after the comma). It carries *your own* position only — never the opponent's (hidden-position
  model) — so there is no shared board frame both sides must reproduce.

### 3.1 Endings only one side can see — the `caught: true` final

**What settles a capture.** Three families, all from the book, all equal in standing:

1. **Co-location** — the cop claims a cell and the thief is on it.
2. **Rule 46** — a barrier is placed on the thief's own cell.
3. **Rule 47** — the thief has no legal move: **every orthogonal neighbour** is a barrier or off
   the board. `STAY` does not rescue it; the rule is about movement, not about intent.

A physics gate that encodes only the first will refuse every legitimate cornering the league
plays. *(Settled jointly with **anrbj666** on issue #37, and matching both independent engines'
`boxed_in` predicate.)*

**Families 2 and 3 are facts only the THIEF can observe** — they are properties of its own hidden
position — and the cop cannot infer them. So they must be **said**, on the wire, or the game
forks: the thief settles CAPTURE from its own knowledge while the cop, having learned nothing,
waits out its budget and settles TIMEOUT. Two honest peers then describe one sub-game two ways,
which is the contradictory-report shape App. E rule 35 zeroes. This is not hypothetical — it was
reproduced live between two copies of this kit's own sparring peer, deterministically, three
times, with no fault injected (issue #37, found by **anrbj666**).

**The construction is the league's existing vocabulary, not an extension.** The thief's
game-ending final carries

```json
"claim_response": {"claim": [<thief's own final cell>], "caught": true}
```

which is the same `caught: true` final every implementation already emits on a co-location
capture — the one whose `smell_grid` this SPEC already exempts from the one-advance law
("The zero-step final convention", §7). A conforming cop already settles CAPTURE on any
thief-sent `caught: true`. **Nothing new is registered; a thief that stays silent here is simply
not conforming.**

**Answer or concession, and why the cop must check.** A `caught: true` that *echoes the cell the
cop claimed* is an **answer** — the co-location shape. One that *names any other cell* is a
**concession** — a rule-46/47 ending. Both settle CAPTURE immediately; they differ at the audit,
and both must be corroborated rather than believed, because both are worth points the evidence
may not support:

| | pays the thief | pays the cop | who profits from a false one |
|---|---|---|---|
| capture | 5 | 20 | — |
| timeout / technical loss / tamper forfeit | 0 | 0 | — |
| a false **concession** | +5 over the zeroed row it replaces | +20 | the thief |
| a false **answer** | +5 | +20 | **both peers** — so neither can be left to catch it |

So, cop side, at the audit and not at settlement:

- a **concession**'s cell must be captured under the cop's **own** barrier record — on a barrier
  (rule 46) or boxed in by them (rule 47) — never under the barrier list the thief reports, which
  is the thief's own claim;
- an **answer**'s cell must be where the thief's revealed trail ends;
- either failing **voids the corroboration**, and the capture must never be counted clean. *How*
  the sanction is applied is the implementation's: this kit settles the row `tamper_forfeit`, on
  the same path a false survival claim takes; an implementation may instead record it as
  **disputed-capture evidence** in the artifacts and leave the sanction to the pair or the league
  — *"reported, never a unilateral rewrite: the logs decide"* (rule 35). Both routes reach the
  same refusal; only one side imposing it is not required, and an earlier revision of this
  paragraph mandated the kit's own mechanism as though it were the law. *(anrbj666's sceptical
  read of this section, issue #37 — the distinction is theirs and their engine takes the second
  route.)*

**And it degrades.** A peer whose revealed payloads carry no `position` at all is using a legal
schema — §3 above says the payload schema is not an interop constraint — so it gets the checks
the evidence supports and a note for the one it cannot, **never an accusation**. Treating your
own payload schema as an interop constraint is how a checker comes to call an honest, sealed,
counted series *tampered*; that mistake has been made once in this kit and must not get a second
home.

**If you widen where the trail comes from, widen only what you CHECK.** A verifier may reasonably
try more than one source for the revealed position — `position` first, then the reference's
`state` spelling (§3) where a peer emits it, then degrade. That is legitimate under the rule
above, with one hard condition: **the parse must be strict, and anything it cannot parse
confidently must degrade rather than resolve to a cell.** A loose parse that mis-reads a
malformed `state` into the *wrong* cell does not widen verification — it invents a new way to
accuse an honest peer, wearing a helpful hat. Note also that a peer sealing a `state_digest`
rather than the reference's spelling has nothing to parse at all, and is fully conforming: its
half is proven by reconstructing the digest from the revealed pair at audit.

*Credit: **anrbj666** (Alon Engel, Renat Karimov) — the live reproduction, the mechanism, the
construction and the corroboration implementation, the sanction/mechanism distinction above, and
the mis-parse condition on widening the trail source; **imreeyal** — the corroboration
requirement, the answer-path symmetry and the degradation contract. Settled on issue #37,
2026-08-05.*

## 4. Agreement signature, `game_uid` and `game_id`

Before play, each peer signs the agreed terms and both derive a shared id — the pre-game gate that
refuses to start on any mismatch.

- **Signature** = the §3 construction over the terms: `SHA256(canonical_json(terms)|nonce)`.
  **The separator is a SINGLE `|` (U+007C) and nothing else** — not a bare concatenation, not
  `||`. Spelled out because the formula loses the argument against a reader's habits: all three
  readings are plausible in prose, only one reproduces the vector, and the two wrong ones fail
  **every** handshake with nothing to go on but "signature mismatch" — which reads as the
  opponent being broken, or as the terms disagreeing, and sends both sides diffing fourteen
  values that already agree. It is invisible to self-testing, too: sign and verify with the
  same wrong separator and every local test passes. Implementations SHOULD name the expected
  construction in the refusal itself rather than only refusing. *(Raised by **best2934**, kit
  issue #45, after running all three forms against the vector's own numbers.)* Each
  peer signs the terms with its own nonce; the opponent re-verifies over the terms it received
  (which must value-equal its own) using the signer's nonce. `vectors/terms_signature.json`. The
  `terms` are the subset of `config/game.json` both sides must match on (board, scent params,
  scoring bounds, starts, step cap, setting, axes) — the book's App. F table; the exact extraction
  is the reference's `terms_from_config`.
- **`game_uid`** = `UUID( SHA256( canonical(terms) + "|" + "|".join(sorted([g_a, g_b])) )[:16] )`,
  identical for both peers because it is a pure function of shared inputs (sorted group ids →
  order-independent). `vectors/game_uid.json`.
- **`game_id`** = `"-vs-".join(sorted([g_a, g_b]))` — **sorted**, the same pair term that goes
  inside `game_uid`. It names the four submission artifacts:
  `declaration_<game_id>.json`, `config_<game_id>_g<NN>.json`, `log_<game_id>_g<NN>.json`,
  `result_<game_id>.json` (per-sub-game files carry the zero-padded `_g<NN>` suffix, per the
  book's App. F files table and the reference's own `docs/sample-run/`), keeping files from
  different matches from ever mixing.

> **Sort the pair; do not name yourself first.** The reference derives both ids from
> `sorted([g_a, g_b])`, so neither peer has to be told which order to use and there is no
> convention for a pairing to settle. A peer that instead builds `"<us>-vs-<them>"` produces a
> *different* `game_id` on each side of the same match: two sets of artifact filenames, and two
> final reports that cannot be joined by `game_id` at all.
>
> **Observed live, and worse than it first looked.** In the 2026-07-25 cross-team series *both*
> join keys diverged at once — the `game_id` because each side named itself first, and the
> `game_uid` because one side derived it from a wider object than the flat negotiated terms (§6).
> Two reports that agreed on every game value could be joined by **neither** key. An earlier
> revision of this document said the uid "still joined them"; it did not, and the correction is
> anrbj666's.
>
> **Status: reference-derived, and independently matched by two implementations.** anrbj666's
> `build_game_id` sorts the pair in their own code, written before this section pinned it, and the
> imreeyal implementation adopted the sorted derivation on 2026-07-27. Two implementations now
> agree on it without having agreed it with each other, which is the strongest form this evidence
> takes (see [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)).
>
> `vectors/game_uid.json` pins both ids, a swapped-group case proving each is order-independent,
> and the four filenames derived from them.

## 5. Pheromone field

The scent (book ch.4) is each peer's own emission, transmitted as `{"r,c": intensity}` and absorbed
by the opponent — so it is not re-derived cross-team. But a wrong port makes your belief map behave
unlike the book's, so the kit pins the math as a self-test. `vectors/pheromone.json`.

- **Radial emission** around a cell: `half = grid_size // 2`, `falloff = intensity / (half + 1)`,
  and each in-bounds cell gets `round(max(0, intensity - falloff * chebyshev(cell, center)), 3)`.
  Only cells with value > 0 cross the wire. On the default `grid_size=5`, centre `0.9`, falloff is
  `0.3` per Chebyshev ring (`0.9 → 0.6 → 0.3`).
- **Decay per game-step**: every known intensity drops by the constant, clamped at 0 and rounded to
  3 places: `round(max(0, v - decay), 3)`.
- **Emission requires the centre to meet `min_center_intensity`** (default `0.5`); the field is
  merged into the trail by max, and decays each step, producing the fading trail the book's
  heatmap visualizes.

> **Book-vs-reference divergence, documented:** the book's ch.4 prose gives *multiplicative* decay
> (`τ ← max(0, (1−ρ)·τ + Δτ)`, ρ = 0.10) and its emission figure traces a smooth (Gaussian-like)
> radial surface; the reference implements **subtractive** decay (`v − decay`, clamped, rounded)
> and **linear** Chebyshev falloff. Both are now **named registrations** (§7) rather than one
> pinned form and one footnote: this section is `subtractive_chebyshev_v1`, the book's model is
> `multiplicative_book_v1` (§5.1). Unlike §3 this cannot void a game *under this section's wire*
> — scent maps are transmitted, not re-derived cross-team — but the two produce visibly different
> trails, so a pair that wants the book's physics locks it explicitly and both sides declare it.

### 5.1 `multiplicative_book_v1` — the book's own model (PROMOTED)

The book's ch.4 model, registered as a named alternative. `vectors/scent_book_v3.json`. Status is
**PROMOTED** (2026-07-20): the kit's bar ([`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)) — a second
independent implementation reproducing the fixtures — was met by **anrbj666**'s clean-room
reproduction (issue #6): byte-exact on the kernel,
both emit cases, all three walk turns, both scalar traces, and every ordering-probe case with
zero tolerance, from an implementation built from the book alone, predating these vectors. The spec facts were
contributed by **anrbj666 (Alon Engel, Renat Karimov)**, whose implementation follows the book
rather than the reference; every value in the fixture is re-derived here from book v3.0.0 ch.4 and
the App. F binding table.

- **Update**, once per cell per **full turn** — after *both* agents have moved, which is the book's
  own cadence (ch.4: the systemic decay runs "at the end of every full turn"), not once per
  half-turn step:
  `τ′ = clamp((1 − ρ)·τ + Δτ, 0, center_intensity)`, with ρ = 0.10 and `center_intensity` = 0.9.
- **`Δτ` is a verbatim 5×5 lookup** — the printed figure-4 kernel, centre `0.90`, orthogonal `0.62`,
  diagonal `0.42`, then `0.20 / 0.14 / 0.04`. See the note below on why it is not a formula.
- **The upper clamp is not in the printed formula.** The book prints only `max(0, ·)`, but also
  declares τ to be a continuous value in `[0, 0.9]`; without the upper bound a saturated cell that
  decays and is deposited on again reaches `0.9·0.9 + 0.62 = 1.43`, outside the book's own range.
  The fixture pins that case.
- **No rounding**, an empty starting field, decay-then-deposit within the single expression, and
  **no receiver-side pass** — each side recomputes the rival's field from revealed actions rather
  than receiving it. The reference model differs on every one of those four: it rounds to 3 places,
  deposits before decaying, and decays a received copy on receipt.
- **App. F fixes all three parameters** (`קבוע`): centre intensity `0.9`, decay rate `0.10`, field
  size `5×5`. So what a scent registration selects is the *model form*, never the numbers — a doc
  that alters one of those three is refused by the binding table, not by the lock.

> **Why the kernel is pinned verbatim, and an open question settled.** Figure 4 *is* an exact radial
> Gaussian at printed precision — but only for σ² inside a narrow window the book never prints, and
> the window that reproduces the table under round-to-2dp (`[1.3178, 1.3327]`) is **disjoint** from
> the one that works under truncation (`[1.3436, 1.3538]`). Two teams that each "use a Gaussian"
> in good faith can therefore produce different fields, silently. The 25 printed values are the only
> thing both can reach, so the kit pins them and treats the closed form as commentary.
> `closed_form_probe` in the fixture carries both quantizations and both windows. (This reconciles
> a genuine disagreement between the two teams building this registration: anrbj666 read the figure
> as an exact Gaussian and were right about the shape; we read it as matching no clean formula and
> were right about the reproducibility. The pinning follows from theirs *and* ours.)

> **Evaluation order is load-bearing here in a way it is not elsewhere in the kit.** Because this
> model rounds nothing *and* each side recomputes the other's field instead of receiving it, two
> implementations that agree on every parameter can still disagree in the last bit: `(1−ρ)·τ + Δτ`
> and `τ − ρ·τ + Δτ` are the same algebra and different IEEE-754 doubles (75 of 534 probed inputs).
> A byte-comparison of two recomputed fields will then false-flag. Pin the order as written, or
> compare fields with a tolerance — `ordering_probe` in the fixture shows the divergence.

## 6. Report canonicalization and settlement

Both teams independently build the final result JSON, and both email it — the grader compares the
**emails**, not just the hashes. Two rules carry over from EX06 and cost real points when ignored:

- **The emailed body must be the exact canonical bytes** (§2) — never a pretty-printed
  re-serialization. In EX06 two teams' report hashes matched but one team's *email* was a
  re-serialization, and it nearly scored 0.
- **Derived, not declared.** Totals and the diversity flag are derived from the per-sub-game
  results and the game-count declarations by the fixed scoring table (book ch.9), so agreement on
  sub-games implies agreement on totals. **On a series tie, this kit ADDS the App. F tie score
  (2) into each side's `total_score`** — see the tie rule immediately below, which is a
  documented book-versus-reference contradiction and not a settled fact.

- **The tie rule is a book-versus-reference contradiction. Name it, choose, and declare it.**
  The two authorities disagree about *where* the tie score lands, and the disagreement is
  invisible until a series happens to tie:

  - **The book says SERIES level, on the accumulated score.** Ch.9's *כלל התיקו / Tie Rule*:
    "if the **accumulated** score of **all the sub-games** between a pair of groups ends in a tie
    — [tie score] … so that no encounter remains without a scoring decision." The binding
    parameters table says the same in the row that fixes the value — App. F **table 17**, row 5:
    "[tie score] — score to each side **when the accumulated score against an opponent ends in a
    tie** — 2, fixed." Since the binding table is the only binding source for quantitative
    values, this is the stronger authority.
  - **The reference implements a PER-SUB-GAME award that then sums.** Its own published example
    result (`4-final-result.txt`) has sub-game 3 at `"result": "tie"` with `"score": {2, 2}`, a
    `total_score` of `32 / 12` that is the plain sum of the three rows (`20+10+2`, `5+5+2`), and
    `"series_tie": false`. There is **no** series-level adjustment anywhere in it.

  *An earlier revision of this section asserted the series-level award and attributed it to "the
  reference's own aggregate behaviour, observed live against it". That attribution was wrong —
  the reference's own artifact disproves it — and the same revision claimed a raw-sum report
  would differ from "a reference-shaped opponent's report", which inverts the truth: a
  reference-shaped report carries exactly the raw sum. The rule survived the correction; only its
  authority changed, from the one source that contradicts it to the two that state it. Found by
  **best2934** (Tomer Levy, Eyal Koloshi, Alon Issman) reading the reference we had cited, kit
  issue #45; the contradiction was adjudicated by the course staff under the book's
  academic-freedom clause, which makes either behaviour implementable **provided the choice is
  documented and justified**.*

  **This kit's choice, documented as the clause requires: series-level, ADDITIVE.** The reasons,
  in the order that decides them — (1) rule 35 charges **both** teams for contradictory reports,
  so a reading held alone costs an innocent opponent; (2) every league implementation checked so
  far sums additively (imreeyal, anrbj666, best2934); (3) *replacing* inverts the ordering the
  rule claims to protect — a fought 25–25 series would pay 2 while a single narrow sub-game win
  pays 20, so a team would rank higher for one victory than for six draws (argument due to
  best2934).

  **What is still open, and should be declared rather than assumed:** the book fixes the tie
  score at the series level but does not say whether it *replaces* the summed scores or is
  *added* to them, and the reference answers a different question entirely. Three behaviours are
  therefore live in the league — `series_add` (this kit), `series_replace` (the book's other
  reading), `per_subgame` (the reference) — and two conformant teams can legitimately compute
  different totals for one tied series. **Agree it before the first window, like the scent
  model.** A pair that does not will discover it only if a series ties, which is rare enough
  never to surface in a friendly and expensive enough to matter when it does.

  **Do not apply two mechanisms to the same points.** §6.2's `ties` counts tie-*scored* rows —
  the reference's per-sub-game concept — and this section's award is a series-level one. Under
  `series_add` a tied row already carries its 2 into the sum, and the series award is a further
  2 on top; that is the intended reading here, but a pair that reads one field the reference's
  way and the other this way will double-count without either side seeing it.
- **The report's `game_uid` must be derived from the flat negotiated terms.**
  The uid is a pure function of the **flat 14-key negotiated terms** and both group ids (§4) — the
  reference computes `derive_game_ids(terms_from_config(...), ...)`, where `terms_from_config`
  *extracts* those keys. Two counted reports naming one match by two uids is the contradiction
  App. E rule 35 zeroes **both** teams for.
  Two ways to get it wrong, and the second is far harder to catch: a **freshly minted** id, which
  announces itself because it appears nowhere in your logs; and a **deterministic id derived from
  the wrong input** — the whole `game.json` rather than the extracted terms — which is stable,
  reproducible and identical across all four of your artifacts, so they join each other perfectly
  and only the *cross-team* join fails.
  Observed live on 2026-07-25: one side's uid came from its whole config rather than the flat
  terms. Its artifacts were internally self-consistent and every game value in the two teams'
  reports agreed exactly; nothing on either side had reason to look. *(An earlier revision of this
  document called that uid "minted", which was wrong — the correction is anrbj666's.)* The
  divergence was silent for six sub-games because the uid never crosses the wire; §7.3 proposes
  closing that.
- **Stage interlock — gate on the RECIPIENT, not on draft mode.** Under the diversity rule (only
  the *first* meeting with an opponent counts), an accidental early real send can burn your one
  counted game. The reference's own gate is `email.mode = "draft"` — but rule 30's **send-only**
  scope cannot create drafts, so a safety gate that depends on drafting depends on a broader
  permission than the rules allow (the contradiction anrbj666's audit caught between this
  bullet's earlier wording and WARNINGS §6). The gate that works under rule 30 is structural and
  recipient-shaped: the lecturer's address is *unreachable* outside a doubly-armed counted run,
  and a run that owes a report refuses to start with nowhere to send it (WARNINGS §3; the
  playbook's Stage 0).

> **The consensus signature uses a second canonical form** (found by Alon's team —
> alonengel / anrbj666 — and verified against the reference at sha `960499fd`,
> `report_writer.py`). `consensus_signature` serializes with `sort_keys=True,
> ensure_ascii=False` and **default (spaced) separators** — unlike every other hash in the
> release, which uses the compact §2 form. And the signature is computed over the report
> **before** the `חתימת_קונסנזוס_משותפת` key is inserted (sign-then-insert), so the field is
> excluded from its own preimage; verification = pop the signature key, re-serialize spaced,
> re-hash. Two teams that disagree on either detail fail settlement at the exact moment they
> must agree on the result. `vectors/report_consensus.json` pins both details and includes a
> compact-form contrast hash. Counting the three commit constructions (§3), this is the
> release's fourth serialization variant — pinned as-is because it is what the lecturer's own
> tooling computes.

**The consensus *scope* — what the `mutual_agreement` hash is computed over.** The vector above
pins the serialization; the preimage is a choice the book leaves open, and the wrong choice can
*never* match. The scope that works, settled by the imreeyal↔anrbj666 pairing (two-team
convention, offered as the default — it is the reference's own `symmetric_outcome`, verbatim):

```
{ game_id,
  aggregate,                      # total_score, sub_games_won, ties, winner_group, series_tie
  sub_games: [trimmed rows] }     # each row keeps ONLY sub_game_number, roles, result,
                                  #   winner_group, score
```

— everything two honest teams must agree on and **nothing they may legitimately differ on**. A
whole-body-minus-signature scope is per-side *by construction* (its own timestamps and token
counts sit inside), so two conformant teams computing it can never produce equal hashes. The
trimmed scope was proven live on 2026-08-03/04: both implementations emitted **byte-identical**
`mutual_agreement.sha256` values across a validation window and the counted series, and the hash
moved when the outcome pattern moved — behaving as a consensus, not a cache. Enriching the
preimage with `game_uid` and the `github_commit` columns was agreed by both teams as worth doing
and is **PROPOSED** — no implementation computes it yet; until one does, the trimmed scope above
is the interoperable default.

*An earlier revision of this row list (2026-08-04 → 2026-08-13) carried a sixth key, `tie`, and
still called the row the reference's "verbatim". Both halves were wrong, and the error sat in
every carrier at once — this list, the bundle generator's tuple, the bundle's shipped hash and
the bundle README. The reference's `emit.py` deliberately writes `tie` into the document row and
leaves it OUT of the hash preimage; every hash ever settled live — the reference's own sample
run, the 2026-08-03/04 window this very section cites, every filed counted series — reproduces
only under the five-key row. Nothing ever played signed six. The convention was documented the
same day the filed bytes disproved it and never re-validated against them (the §6.2 scoring
failure shape, one shelf over). Found by anrbj666 against the reference's own artifact,
2026-08-13; independently reproduced by imreeyal the same day. The row is now pinned to the
reference's artifact by `tools/probes/probe_s6_consensus_scope.py`, which recomputes the shipped
bundle hash from the five-key scope on every CI run — the trim loses nothing, since `tie` is
derivable as `winner_group == null` and the tie COUNT already sits in the signed aggregate. The
document row keeps `tie` (§6.2, the playbook's table); only the hash row never had it.*

### 6.1 One report per team, result-only (settled convention, documented tension)

What the report email *contains* is a two-team convention with evidence, not a book quote — say
so in your docs and match it rather than re-deriving it the hard way:

- **One email per team per counted series**, to the league address, containing the **result JSON
  as the body and the same file as the single named attachment** (body = rule 34's text reading,
  attachment = its file reading; WARNINGS §6). The reference's own `emit_series` returns only the
  result "for emailing", and its sender puts exactly that in the body.
- **The other three artifact types — declaration, configs, logs — are published in the repos,
  never mailed.** The result's `links.github` (rule 49) is how the grader reaches them.
- **The documented tension:** the book's §9.3.3 prose describes the emailed JSON as carrying
  identity and hardware, which the results template does not — those live in the declaration
  artifact. Both league teams read the results file (whose full example §9.3.3 itself provides)
  as the emailed report and resolved the prose against it, under the academic-freedom clause.
  This is a settled choice with the contradiction on record — not an unread section.

Both teams' counted-series mails (2026-08-04) had this shape, verified by diffing the received
mails in both directions.

### 6.2 The league fields inside the result

Three fields in `final_result` are **graded inputs** to the league standings — the lecturer
weighs them, and rule 35 punishes two reports that disagree on them exactly as it punishes a
score mismatch:

| Field | Shape (as played) | Meaning |
|---|---|---|
| `games_played_including_this` | per-group map, e.g. `{"<gid>": 1, …}` | each team's own counted-game count, **including** this series |
| `first_meeting_between_groups` | boolean | whether this pairing has a prior *counted* series (rule 52: only the first counts) |
| `diversity_reward_applied` | per-group map of booleans | whether the App. F diversity reward attaches — see below |

What the book fixes (App. F, table 18 — binding): the diversity reward is **10 points for a
victory over a group not previously played** — *"ניקוד על ניצחון מול יריבה חדשה"* — a reward for
**winning** against a new opponent, not for merely meeting one; a team passes the league
component with a **minimum of 2 counted games against different groups** and may count **at most
10**. So `diversity_reward_applied` is derived: winner of a first-meeting series → `true`, loser
→ `false`, and both teams derive the same values from the same outcome (§6's derived-never-
declared rule).

What feeds the other two fields is each team's **own committed ledger** of counted games — and
the fields sit deliberately **outside** the `mutual_agreement` scope (§6 above): your count is
your own declared claim, your opponent cannot verify it, and a consensus hash over unverifiable
claims would manufacture disagreements. Exchange the counts you will declare *before* the
counted T (PAIRING-PLAYBOOK Stage 6) so the two reports still agree.

**The disqualification hazard** is the ledger, not the fields: see WARNINGS §5a. Rules 37–38
make a false declaration project-fatal, and a ledger that does not advance after every counted
series makes the *next* series declare a false first meeting automatically.

**Definitions the fields depend on** (each was undefined until anrbj666's pass-five audit
proved two readings existed — every one of these is a rule-35 contradiction waiting for the
pair that splits it):

- **Posture.** The derivation sentence above binds **counted** reports. An *uncounted*
  (friendly) report carries the fields **disarmed** regardless of outcome — counts unbumped,
  `diversity_reward_applied` all-false, `first_meeting_between_groups` declared truthfully —
  because arming them in a game that does not count is a false declaration under rules 37–38
  (PAIRING-PLAYBOOK stage 4d). A winner beside an unclaimed reward in a friendly is therefore
  correct, not a contradiction.
- **`null` in `games_played_including_this` means UNCLAIMED, and it is legal.** A count is a
  team's own unverifiable claim about its own standing, so an emitter that cannot know its
  opponent's count MUST declare `null` for that group rather than fabricate one — and `null`
  is **not** `0`, which is a claim that the opponent has played no counted game. Two reports of
  one match therefore **agree** when their non-null claims are compatible **per group**:
  `{"a": 3, "b": null}` beside `{"a": null, "b": 5}` is two teams each stating their own count,
  not a contradiction, and `tools/check_artifacts.py` joins it. Only two **different non-null**
  numbers for the **same** group are the rule-35 disagreement. This is the one league field
  where a per-side difference is legal, precisely because it is the one field neither side can
  observe about the other — the other two are pair-observable and must be byte-identical. The
  exchange before the counted T (above) is what usually makes both sides fully non-null; a
  friendly against a peer whose ledger you have not been told is where the nulls belong.
  *(Three documents disagreed about this until anrbj666's pass six: the playbook's must-be-
  identical table, the checker's join, and this section, which had never said the word.)*
- **Where the two App. F awards land is asymmetric.** The **+2 tie** award is ADDED into
  `total_score` (above). The **+10 diversity** award is **not**: it is applied by the league
  table *from* the `diversity_reward_applied` flag and never enters the report's totals — the
  played counted series' result carries the pure sum (90) beside `diversity_reward_applied:
  true`, and `tools/check_artifacts.py` refuses a +10 baked into totals, with a diagnosis.
- **`counted_games_played` vs `games_played_including_this`.** The first (declaration /
  greeting identity) is the count of counted games **before** this one — exclusive. The second
  (result) **includes** this one. For a counted report the identity is
  `games_played_including_this == counted_games_played + 1`; two teams splitting the
  exclusive/inclusive reading declare counts off by one under rules 37–38.
- **`ties`** is the count of sub-games *scored as a tie* (the course's own example scores one
  2/2). A **zeroed** sub-game (timeout, technical loss, tamper forfeit) is a sanction, not a
  tie, and is credited to nobody — so the row-accounting identity is
  `sub_games_won[a] + sub_games_won[b] + ties + zeroed == num_sub_games`, and the naive
  identity without the zeroed term fails any series with a technical loss. `ties` sits inside
  the consensus preimage, so a pair that reads it differently breaks
  `mutual_agreement.sha256` with no document to resolve it — this paragraph is that document.
  (The kit's sparring peer's own outcome set cannot produce a tie-scored sub-game and its
  `ties` is honestly always 0 — disclosed here per WARNINGS §5b.)
- **`tokens_total_series`** is the per-group sum of the per-sub-game `tokens` rows beside it —
  an internal identity `check_artifacts` now enforces. The *declaration's*
  `max_tokens_per_game` carries a genuine ambiguity the book does not settle (per sub-game or
  per series — a 6× difference): state your pair's reading in the Stage-1 exchange rather than
  discovering it at an audit.

## 7. Locked-model declarations

The book leaves several choices to inter-team agreement but freezes the signed terms as a flat
14-key set — so a pair cannot record a choice by adding a key to `config/game.json` without
breaking the terms signature (§4). Teams have independently converged on the same workaround:
publish a description of the choice, hash it, and declare **only the hash** in the negotiate
extras. This section pins the document underneath that hash. `vectors/locked_model.json`.

**Without a pinned schema the mechanism backfires.** A bare hash over an ad-hoc dict means two
teams that implement the *same* model from the *same* spec still declare different hashes — they
serialized different field sets — and refuse each other for no reason at all. The hash is only as
useful as the agreement on what goes into it.

**One schema, four families.** A locked-model doc has exactly four keys:

```json
{"family": "scent_model", "name": "multiplicative_book_v1", "params": {...}, "example": {...}}
```

`family` ∈ `scent_model` | `wire_shape` | `info_mode` | `smell_binding`; `name` is the registered
name; `params` carries the model-specific values; `example` carries a worked case. Everything
variable lives in the last two, so the envelope never changes as families are added — `smell_binding`
(§7.4) was added without touching a single byte of the six docs that preceded it, which is the
property the closed envelope exists to give.

- **Hash:** `sha256(canonical_json(doc))` — the compact §2 form, the same construction anrbj666's
  team already ships for `scent_model_sha256`. Adopting the schema changes the *bytes hashed*,
  not the mechanism.
- **Declaration:** the doc never crosses the wire; only `"<family>_sha256"` does, in the negotiate
  extras. The kit registers eight docs: two scent models (§5, §5.1), two wire shapes, two info
  modes, two smell bindings (§7.4).
- **Refusal rule: refuse only when BOTH peers declare a family and the hashes differ.** Omission is
  never refusal — in either direction. A lock that fail-fasts on a *missing* declaration cannot
  start a game against the unmodified reference peer, which declares nothing at all; that is a
  self-inflicted forfeit, not a safeguard. The fixture pins the rule as a five-row truth table
  because it is behaviour, not bytes, and it is the part implementations get wrong.
- **A declaration binds a choice; it does not widen what may be chosen.** App. F's fixed values and
  minimums are unaffected — a doc that lowers a minimum is refused by the binding table regardless
  of what the peers agreed.

**`info_mode` needs one honest annotation.** The mode (`belief` — the rival's position is outside
the observation space — versus `exact`) is a negotiated term like the others, but its enforceability
is asymmetric, and the registration says so. A **mismatch** is provable from the two negotiate
records. A **violation** — a brain consuming exact positions while declaring `belief` — is *not*
provable from any artifact, because a decision record does not disclose which information produced
it. Under wire shape `reference-v3` the belief mode is enforced **structurally**, since the rival's
position never crosses the wire; under `bookletter-v3`, which puts it on the wire, the same words
are an **honor term**. Declaring the mode is still worth doing — it makes the intent explicit and a
mismatch catchable before the game — but a pair should know which of the two it is relying on.

**What a scent model's `transmitted` flag means — and what it does not.** Two of the registered
scent models carry a `transmitted` parameter, and read literally it contradicts the wire it runs on.
`multiplicative_book_v1` declares `transmitted: false`, because the book's model has each side
recompute the rival's field rather than receive it. But wire shape `reference-v3` makes `smell_grid`
a **required key of every turn message** — the reference's own message type gives it no default, and
both known independent implementations fault on an absent key. A wire that mandates the field and a
lock that forbids sending it cannot both hold.

The reading this kit pins:

> **`transmitted` constrains what a peer may RELY ON, not what crosses the wire.**

- **`transmitted: true`** — the field on the wire is the model's own protocol data. A receiver may
  absorb it and feed it to inference, subject to its own validation.
- **`transmitted: false`** — the model defines **no receiver-side meaning** for the field. A peer
  MAY still populate the wire key, because the *wire shape* owns whether the key exists and the
  scent model does not; and a receiver MUST NOT treat its content as protocol data it can rely on,
  because nothing in the **model's** semantics vouches for it. A **pair** may vouch where the model
  does not: a declared `info_mode` whose registered sources include the field (this registry's
  `info_mode:belief` does), or a `smell_binding` registration authenticating its bytes, restores
  receiver-side reliance as a **deliberate pairwise arrangement** — the mirror of the `{}`
  arrangement, for pairs that say what they rely on rather than pairs that want nothing relied on.

**The `{}` convention.** An arrangement in which a peer sends nothing under a `transmitted: false`
model is expressed as `smell_grid: {}` — **never by dropping the key**. That keeps the reference
wire's closed key set intact (absent faults, empty is legal, verified against the reference schema
and both independent implementations) and costs no one a code change.

*Implementer's note, behaviour rather than bytes:* a receiver-side physics or validity check must
treat an empty field as **absence of data, not impossible data**. A transition check that demands an
emitter for every frame will refuse an entire game against a peer doing exactly what the lock
permits. Both known implementations have shipped or fixed to this gate; the failure mode is real,
and anrbj666 found it in their own checker.

**The zero-step final convention.** The same reading has a second form of "nothing to rely on": a
game-ending caught=true final message. That message is mid-round and action-free, so its
`smell_grid` may legitimately be a **zero-step re-send** of the last boundary's field, unchanged —
which the frame-to-frame law (exactly one decay+deposit step) can never explain. It is exempt: a
receiver-side transition check MUST NOT apply the one-advance law to the game-ending final. A
re-sent boundary adds nothing a peer could rely on, exactly as an empty field does — and a check
that refuses it plants a structural false refusal into the evidence of **every capture ending,
forever** (anrbj666 found and fixed this in their own receiver; the other implementation's final
advances the field one step instead, which the exemption must — and does — tolerate equally: the
rule is "do not judge the final", not "expect any particular final").

Three reasons for this reading over the literal one. First, the literal one ("nothing crosses the
wire") is unimplementable against the reference schema without either breaking the closed key set or
defining `{}` semantics anyway — at which point the rely-on reading has been adopted in fact.
Second, it matches what every implementation in the league does today, so nothing on the wire moves
and no declared hash changes. Third, it scopes the alternative cleanly: a pair that genuinely wants
nothing on the wire adopts that as a deliberate pairwise arrangement — `{}` on send — instead of the
registry pretending the flag already required it.

Whether any pairwise arrangement under this section satisfies the course rulebook is the pair's own
duty to establish; this registry pins wire semantics between consenting implementations and
adjudicates nothing about the book.

This is a clarification of what the registered docs already say. **No `params` value changes and no
registration is re-hashed**; `vectors/locked_model.json` is untouched by it.

*Credit: **anrbj666** (Alon Engel, Renat Karimov) — the `REQUIRED_KEYS` collision observation, the
`{}` convention, the empty-field checker trap, the zero-step-final exemption (both found and fixed
in their own client), the pair-vouching clause, which caught this section's own draft contradicting
the registry's `info_mode:belief` document before either team signed it, and the book-adjudication
scope sentence. **Imreec** — the send/receive split probe that surfaced the ambiguity, the rely-on
reading, and the cross-checks against both implementations. Settled jointly, Rounds 16–19,
2026-07-29/31.*

**Every registration now carries its own `status` and the evidence for it**, on the terms in
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) — read them off `vectors/locked_model.json` rather than
from prose. (A summary sentence here once restated the tiers and went stale within a week —
anrbj666's audit caught it contradicting the fixture, the checker and this very section 25 lines
apart. The fixture is the register; prose is not.)

`bookletter-v3` is a **documented deviation** from the book's formal model that a pair may lock by
explicit mutual sign-off. Its commit layer reproduces under §3 over the full 7-field payload, but
four preimages — `state_digest`, `end_state_digest`, `config_sha256`, and whether a signed 14-key
`terms_signature` accompanies it — are not yet pinned, so its `params` record them as
`unpinned_preimages` and its hash will change when they are settled. That is the intended
behaviour: a lock should not claim to bind what it does not.

> **The mechanism itself has now been exercised end-to-end, and that is the stronger claim.**
> Across the six-sub-game cross-team series of 2026-07-25, a second independent implementation
> declared `scent_model_sha256` and `wire_shape_sha256` **byte-identical to this kit's registered
> docs** — which is the entire point of pinning the schema, since a bare hash over an ad-hoc dict
> would have differed while describing the same model. The lock also demonstrably *refused*: an
> earlier attempt that evening aborted on a scent-model mismatch before a single game was played.
> `vectors/locked_model.json` carries the observed hashes in `live_reproduction`, and the checker
> asserts they still equal the registered docs — so the evidence for the promotion is itself a
> check rather than a sentence.
>
> Two honest limits from that first run — one since discharged. **`info_mode` travelled as a bare
> string** (`"belief"`) on 2026-07-25, not as a doc hash, so at that point the `belief` / `exact`
> registrations were not reproduced — only the intent was. **Superseded from 2026-08-01:** both
> implementations declared `info_mode_sha256` **byte-identical to this registry's `belief` doc**
> in every handshake of the five-friendly campaign and the 2026-08-04 counted series, both role
> directions — the same evidence class that promoted `wire_shape: reference-v3`, and the `belief`
> registration is now `PROMOTED` on it (`vectors/locked_model.json` carries the observed hash and
> the checker asserts it still equals the registered doc). The other limit stands: a **fourth
> family, `hardware_spec_sha256`, was observed on the wire and is deliberately not registered
> here** — the doc underneath it is unknown to us, and registering a family whose field set we
> have not seen would reintroduce exactly the ad-hoc-dict problem this section exists to remove.

**What the `wire_shape` lock does *not* cover: turn order.** Under `reference-v3` the thief
takes the first game turn of every sub-game — that is the reference implementation's own
behaviour, observed live against it, not a rule the book's binding table states anywhere. The
lock hashes a doc that never mentions intra-turn order (`bookletter-v3` negotiates it
explicitly as `commit_order`; `reference-v3` inherits the reference's behaviour), so **two
peers can match on every declared hash and still deadlock**, each waiting for the other's
first move — both time out, both blame the other, and rule 35 zeroes contradictory reports.
This is not hypothetical: the kit's own sparring peer shipped playing police-first under a
`reference-v3` declaration and was caught exactly this way on 2026-08-04, after a handshake in
which every lock matched. State turn order in your first-contact message
([PAIRING-PLAYBOOK](docs/PAIRING-PLAYBOOK.md) stage 1); a matching lock that hides a fatal
disagreement is worse than no lock.

### 7.1 At-least-once delivery — the receiver contract (PROMOTED)

Status is **PROMOTED** (2026-07-26). It was implemented independently by two teams on 2026-07-22
and then exercised by both across a full **six-sub-game cross-team series over public tunnels on
2026-07-25**, with mutual audits clean in both directions. `vectors/delivery_contract.json` pins
the contract as a decision table — this is behaviour, not bytes, so it is checked the way §7's
refusal rule is.

Both registered wire shapes ride an HTTP transport that is **at-least-once, not
exactly-once**. A push that is delivered but whose acknowledgement is lost is retried by a
correctly-written client, so **the same message arrives twice**. Two of a peer's pushes can
also be in flight at once, so a retry can arrive after a later message.

This is not an edge case reserved for bad networks. A client that retries an in-game push on
the turn budget — the behaviour that stops a network flap from costing you the game — is a
duplicate sender **by design**.

A receiver has three available answers, and two of them cost points:

| Receiver behaviour | Outcome on a redelivery |
|---|---|
| refuse the repeated step as a protocol violation | a flaky tunnel becomes a technical loss; under App. E rule 35 the missing or contradictory report that follows zeroes **both** teams |
| apply the message again | belief, scent field and history are updated twice from one real move — no error is raised, and the divergence surfaces later as an audit or physics disagreement between two honest peers |
| absorb it | the game state is identical to a single delivery; play continues |

**Recommended receiver contract** — implemented independently by two teams as of 2026-07-22,
and adopted as a numbered decision in their joint wire-shape ADR:

1. **Deduplicate on the `commit`, not on `(kind, step)`.** The commit is the one field a
   redelivery cannot vary. Keying on it collapses a retry while keeping a *second, different*
   commit for an already-played step distinguishable — that case is tampering evidence and
   must stay loud. A `(kind, step)` key collapses both, silently.
2. **Buffer a bounded number of out-of-order arrivals** and replay them in order; treat
   anything past the bound as a violation. Let the window be the flood rule — a second
   threshold beside it is unreachable.
3. **Never let tolerated traffic renew a turn deadline.** One clock per *expected* message, so
   a stall attempt burns the sender's budget rather than the receiver's. Note that the deadline
   must also be evaluated on laps where a message *did* arrive: a receiver that only checks its
   clock on an empty poll never checks it under a flood.

**Transport tolerance, no rules tolerance.** None of the above relaxes the commit-reveal
guarantees. Equivocation still collapses the game.

**Behaviour of the reference implementation.** Teams building from the reference should know
that its turn handler (`peer/turn_handler.py`, `TurnHandler.process`) does not carry a
step-continuity check: an inbound message is appended to history and applied unconditionally,
so a redelivery is processed a second time (belief diffusion, smell observation, field
absorption, decay). The book does not specify duplicate handling, so this is an unspecified
area rather than a deviation — but it is worth patching before a counted series, because the
resulting state divergence is silent and is most likely to be discovered as a disagreement in
the audit, when it can no longer be attributed.

*Reported by the copthief league teams (Imreec, anrbj666), 2026-07-22, from a live
duplicate-delivery drill over a public tunnel and a reading of the reference source.*

### 7.2 Pairing declaration — `sub_game_number` and `role` (PROMOTED)

Two fields ride the negotiate extras **beside `terms`, never inside it** — the terms are a flat
signed set, so adding a key there breaks the signature (§4). They answer the one question the
signed terms cannot: *am I talking to the peer I think I am, in the game I think we are playing?*

```json
{"terms": {…}, "nonce": "…", "signature": "…", "role": "police", "sub_game_number": 3}
```

- **`sub_game_number`** — the index of the sub-game *this* peer believes it is playing, taken from
  its sealed step-0 record rather than re-read from a config default. A re-read default is exactly
  what desynchronises.
- **`role`** — `police` or `thief`, the side this peer plays in that sub-game.

**Why the handshake is the only place this can be caught.** Identical terms give identical
`game_uid`s, and the uid is what joins the artifacts. So by the time an artifact exists, a
mispairing is already invisible: two peers that disagree about which sub-game they are in will
both seal, both settle, and both write consistent-looking files under the same uid.

**Refusal rule** — `vectors/pairing_declaration.json` pins it as a truth table:

| Case | Decision |
|---|---|
| same sub-game, complementary roles | play |
| sub-game numbers differ | **refuse** — one game cannot carry two indices |
| both declare the same role | **refuse** — two of the same side can only deadlock |
| either side omits either field | play |
| a declared value cannot be compared (wrong type) | play — treated as silence |

**Omission never refuses**, in either direction — the same rule §7 uses for locked models, for the
same reason: the unmodified reference peer declares neither field, so a guard that fail-fasts on
silence forfeits that game to itself. A value that cannot be compared is silence too; refusing over
a peer's type or spelling choice would turn a cosmetic wire difference into a lost game.

> **Why it is worth two fields.** The cost compounds. A failed handshake ends in about 60 s while a
> real sub-game takes minutes, so the side that failed runs **ahead** and never resynchronises.
> Observed live: one side on sub-game 4 while the other was still on sub-game 2. That is two teams
> describing different series — precisely the shape App. E rule 35 zeroes for **both**. A related
> failure the same rule catches: an orphaned peer left holding the port answers a sub-game the real
> peer was supposed to play, so one game is sealed under two different indices and nothing anywhere
> notices.

Status is **PROMOTED** (2026-07-26): both fields were declared **and asserted** by two independent
implementations across the full six-sub-game cross-team series of 2026-07-25 — the opponent's
inbound greetings carry both, top-level, alternating correctly with the role swap.

### 7.3 `game_uid` declaration (PROPOSED)

**The `game_uid` never crosses the wire.** Each peer derives it from the flat negotiated terms and
the two sorted group ids (§4), which is the point — no round-trip is needed. But it also means
neither peer has anything to compare against, so a peer that derives it from the **wrong input**
produces a uid that is deterministic, self-consistent across all four of its own artifacts, and
wrong only against its opponent.

That is not a hypothetical failure mode. It happened across a full six-sub-game series on
2026-07-25 and was **silent the entire time** — one side had derived the uid from its whole
configuration rather than from the extracted flat terms. It surfaced the next morning, when two
reports were diffed.

The proposed closure is one more field in the negotiate extras, in exactly the shape of §7.2:

```json
{"terms": {…}, "nonce": "…", "signature": "…", "role": "police",
 "sub_game_number": 3, "game_uid": "1e73c318-5b29-4a7b-1c6…"}
```

| Case | Decision |
|---|---|
| both declare, values equal | play |
| both declare, values differ | **refuse** — two derivations of one game disagree; check your terms input |
| either side omits it | play |
| a declared value cannot be compared | play — treated as silence |

**Omission never refuses**, in either direction — the same rule §7 and §7.2 use, for the same
reason: the unmodified reference peer declares nothing, and a guard that fail-fasts on silence
forfeits that game to itself. `vectors/uid_declaration.json` pins the table, and carries a worked
example of the failure: the same derivation over the flat terms and over a wider config produces
**two valid, stable uuids**, which is precisely why the wrong one is hard to notice.

Status is **PROPOSED**, but no longer single-sided: from the 2026-08-01 warm-up through the
**2026-08-04 counted series**, *both* implementations declared the derived uid top-level at
negotiate in every handshake, both role directions, values matching by independent derivation
(the observable: the opponent's inbound greetings in the archived records carry `game_uid`
beside `role` and `sub_game_number`). What keeps this short of `PROMOTED` is the refusal half of
the table: no live mismatch has ever fired it, and only one implementation's test suite pins the
refuse row — a behaviour fixture promotes on *decisions*, not on the happy path (see
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)). Do not assume an opponent refuses on mismatch.

*Finding credited to both teams: **Imreec** observed that the divergence was silent for the whole
series; **anrbj666**'s root-cause analysis established the mechanism — and corrected our first
published diagnosis, which had wrongly called the uid "minted".*

### 7.4 `smell_binding` — anchoring the transmitted grid to the sealed record (PROPOSED)

Under wire shape `reference-v3` the smell grid is the **one per-step observable that no commitment
covers**. The move is sealed and re-hashed at the audit; the grid beside it is not. So a peer that
transmits a stale, malformed or fabricated field is caught — if at all — only by the receiver's own
physics check, and that refusal is provable to nobody but the receiver that made it. Both teams
ship such a check today; both know it is evidence-grade at best.

`smell_binding` is a fourth locked-model family (§7's envelope, §7's truth table:
both-declare-and-differ refuses, omission never refuses). It answers *is this field authenticated?*
`vectors/smell_binding.json` pins the digest, the sealed record and the audit rule.

**If you are onboarding today, the thing to do about this section is: nothing.** Play unbound —
every cross-team game played so far has been, **zero implementations exist**
([GOVERNANCE](docs/GOVERNANCE.md)), declaring nothing refuses nothing, and no opponent may treat
your silence as a fault. This section is a design for a first and a second implementation to
build to *later*; it is not a requirement of anyone.

**`smell_binding:none`** — `params: {}`. The unbound default: byte-identical to today's wire, and
registered only so that "unbound" is a state a peer can **declare** rather than a silence that
cannot be told apart from never having heard of the family.

**`smell_binding:commit_grid_v1`** — the sender's sealed per-step record gains exactly one key:

```
smell_grid_sha256 = sha256(canonical_json(smell_grid_as_transmitted))
```

- `smell_grid_as_transmitted` is the **exact wire value** of that step's `smell_grid` — never a
  re-derived, re-rounded or re-ordered copy. The grid's keys are `"r,c"` **strings**, so the
  canonical form sorts them lexicographically and `"10,1"` precedes `"2,3"`: an implementation that
  sorts its grid numerically before serializing agrees on every board narrower than eleven and
  silently disagrees on every board wider than ten. The fixture pins that case.
- An **empty grid is an input, not a gap**: `{}` has a real digest, a sender that transmits nothing
  seals *that* value, and its audit passes. Under an arrangement where nothing crosses the wire the
  binding is therefore **inert** — the digest is constant — and still harmless.
- The key sits inside the sealed record, so it enters the step's commit preimage through the
  **existing §3 construction**. No new hash form, no change to the commit algorithm, no change to
  the wire. The fixture asserts that adding the key *moves* the commit; if it did not, the grid
  would be bound to nothing.
- At the mutual audit the standard re-hash proves record integrity as it does today, and a verifier
  additionally recomputes `sha256(canonical_json(archived_inbound_grid))` per step and compares.

**What it buys, and what it does not.** It buys **authenticity**: a stale, malformed or forged frame
becomes provable at the mutual audit instead of evidence-grade-only in one team's dispute file. The
in-play transition check stays the early-warning layer; the binding upgrades its refusals from
*provable only to us* to sanctionable. It does **not** buy **privacy**. An honest, correctly bound
field inverts to the sender's cell exactly as an unbound one does — two consecutive transmitted
frames determine a single emitter cell, **224 of 224 frame pairs, under both registered scent
models, including saturated dwells** (anrbj666's finding, 2026-07-27, reproduced independently by
Imreec before adoption). **That number is the measured size of the oracle the `info_mode:belief`
declaration exists to fence**: both known implementations declare belief mode and wall the
inversion out of play behind a verdict-only validator, pinned by a test on each side — the
measurement quantifies what the fence holds back, not a capability in use. Signing a frame does
not un-leak it. Localization is `info_mode`'s problem, or a pairwise nothing-on-the-wire
arrangement's; never this binding's.

**Interop.** The wire is unchanged — the grid rides where it always rode and only the sealed record
grows a key, so a reference-shaped peer indexes its own keys, ignores the extra one, declares
nothing, and plays unbound. The binding is meaningful only where grids actually cross the wire — see
the `transmitted` clarification in §7 above: the flag constrains what a peer may rely on, not what
crosses the wire, and a peer sending nothing sends `smell_grid: {}` rather than dropping the key.
Under such an arrangement the binding is inert, since `{}` hashes constantly, and still harmless.

Status is **PROPOSED**, and at the weak end of it: this is published so that a *first* and a
*second* implementation can both build to it — nobody has shipped it. Promotion needs the usual bar
in [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) **plus a live warm-up drill**, because it changes a
commit preimage: both peers change what they seal on the same turn or neither does, and under App. E
rule 35 a mid-series divergence there zeroes **both** teams. It never debuts in a counted game.

*Proposed by **anrbj666** (Alon Engel, Renat Karimov) — bind the grid to the sealed record so that
the machinery already protecting moves protects the field. Scoped by **Imreec** — authenticity, not
privacy — from the frame-inversion measurement that showed a bound field leaks the sender's cell
exactly as an unbound one does. Agreed by both teams 2026-07-29 as worth doing on its own merits.*

### 7.5 The wire surface — which tools, carrying what (PROMOTED)

`vectors/turn_message.json`.

**Compare tool lists before you compare anything inside them.** Two peers can agree every one of
the fourteen terms, verify each other's signatures, settle the scent lock, the parity and the step
semantics, bring up both tunnels — and still be unable to exchange a single move, because they
never once compared the *names of the calls*. That is not hypothetical: it cost **best2934** and
**imreeyal** a scheduled friendly on 2026-08-08 (issue #45), with everything else already agreed.
Their surfaces intersected in exactly one name, `negotiate`.

The `wire_shape: reference-v3` locked document has always carried the tool list in its `params`.
What it did not carry — and what this section adds — is the **shape of what those tools carry**, so
a team could learn that `receive_turn` exists and still have nothing to build against.

| tool | status | carries |
|---|---|---|
| `negotiate` | REQUIRED | flat terms + nonce + signature + `identity`; either side may open (§4) |
| `receive_turn` | REQUIRED | one `TurnMessage`, one message per half-turn |
| `submit_audit` | REQUIRED | one `AuditPayload` per sub-game: the sealed chain **with nonces** |
| `receive_control` | OPTIONAL | a status channel touching no game state; answering 200 is conformant |

**The transport is symmetric push.** Each side CALLS the other's `receive_turn` with its own turn
and polls its own inbox for the other's. Neither peer can be purely passive: there is nowhere else
for a turn to go. This is one HTTP call per turn, not a client stack.

**Two things are deliberately NOT on this wire**, and both have cost a window:

- **No step-0 tool and no step-0 turn.** The hardware/model declaration rides in `negotiate` under
  `identity`; the sealed step-0 record is disclosed inside `submit_audit`. A peer that waits for a
  `declare_step0` call waits forever.
- **No `hello`.** A liveness probe should be `tools/list`, not a tool *call*. A peer that
  implements none of your names is still **up**, and `negotiate` is the authority on whether you
  may play. Collapsing "you do not implement this" into "you are not there" is how one team spent
  five minutes reporting a live opponent as absent.

`step` numbering is per-peer and a step is a **round** — see the fixture's field notes, and read
§4's `max_steps` alongside them: two peers reading "35" as *rounds* and as *half-turns* agree on
every signed term and still desync, and no gate either of them builds will say a word about it.

Validation happens **before any state change**. The fixture pins seven cases including the two
load-bearing ones: an unknown key is tolerated (the extension seam) and a missing required key is
refused rather than defaulted (a defaulted `commit` is a move the sender never sealed).

*Raised by **best2934** (Tomer Levy, Eyal Koloshi, Alon Issman) after the disjoint-surface friendly,
who asked to be pointed at a published contract rather than reverse-engineer payload shapes from a
live game — "that is how a series ends in a rule 35 void". They were right, and the gap was ours.*

## 8. Conformance

A team is **interop-ready** when:

1. **Core vectors pass** — `python verify_vectors.py` reproduces every `[CORE]` fixture, and your
   own implementation reproduces them too (port the checks into your suite): canonical JSON with
   `ensure_ascii=False`, the commit construction, the terms signature, `game_uid` and `game_id`,
   the pheromone math, **the report consensus signature** (§6 — the one that fails settlement at
   the exact moment both teams must agree; this list once omitted it, caught by anrbj666's
   audit), and — if you declare any locked model — the doc schema and the refusal rule.
2. **The behaviour tables answer the same way** — your receiver's verdict on every row of
   `delivery_contract.json` and `pairing_declaration.json`. These cost games exactly as byte
   mismatches do, and unlike bytes they cannot be caught by comparing a hash with a partner.
3. **Cross-team audit is clean** — feed your opponent's revealed log to your verifier and your log
   to theirs; both audits pass with zero `tamper_forfeit`. This is the real test §1 exists for.
4. **Report bytes match** — the emailed body equals the canonical bytes that were hashed, and the
   `game_uid` inside is derived from the flat negotiated terms — not from a wider config, and not
   freshly minted (§4, §6).

Each fixture declares its own tier — `CORE`, `PROMOTED`, `PROPOSED` or `ENH` — and
`verify_vectors.py` prints it. What those tiers claim, and what it takes to move a fixture between
them, is defined once in **[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)**; the roster is generated at
[`vectors/INDEX.md`](vectors/INDEX.md). In short: `CORE` is the interop floor and everything else is
opt-in, `[ENH]` binds only a pair that signed it into `config/game.json`, and `PROPOSED` becomes
`PROMOTED` when a **second independent implementation reproduces it** and the evidence is cited in
this repo.

CI regenerates all vectors and the worked example on every push and fails on any drift.

## Appendix A — agreed enhancements (opt-in, not required by the book)

The book's default rule is "no rule unless written," and it invites teams to agree on extras and to
exploit undefined gaps — provided the agreement is signed into `config/game.json` and does not
weaken any mandatory minimum. These are ours; a pair uses one only if both sign it in.

- **Transcript interlock DAG (`prev` / `prev_recv`).** The book's commits are independent per step —
  strong against *editing* one step, but a full log can be re-forged offline (there is no
  cross-link). Optionally add to each sealed record `prev` = SHA-256 of your previous sent record's
  exact bytes and `prev_recv` = SHA-256 of the last opponent record you accepted. The two logs
  interlock into one DAG: a re-forged history contradicts the opponent's later records that
  acknowledged it, so earliest divergence is provable from the two committed logs. Requires storing
  verbatim record bytes. (Design credit: anrbj666, issue #1.)
- **Seeded asymmetric starts + joint-seed coin flip.** The book fixes `cop_start`/`thief_start` in
  the config. A pair that prefers randomized-but-fair starts can instead derive them from a joint
  seed generated by commit-reveal so neither side picks a favorable one:
  `share_commit = SHA256(canonical({"seed_share": r}))`, reveal, `seed = SHA256(canonical({"shares":
  [r1, r2]}))`; then `derive_starts(seed, index=game*16+attempt, n)` with a minimum-Chebyshev
  distance (no instant captures) and a deterministic re-draw. `vectors/joint_seed.json`,
  `vectors/derive_starts.json`.
- **Synchronized fixture scheduling.** The league is self-organized (book ch.9), and only the first
  meeting with each opponent counts. To keep scheduling luck out of it, a group of teams can agree a
  deterministic round-robin (circle method over the sorted roster) so round `r` fixes everyone's
  `r`-th opponent, derivable by anyone from the roster.
- **Demo staging beyond `draft`.** Run one or two full fixture rounds as a dress rehearsal with
  reports routed to a league test mailbox (schema + byte-identity auto-checked) before anyone's
  first counted game. Complements the reference's `email.mode = "draft"`.

## Appendix B — league services (optional, passive)

None of these run game logic, so the peer topology and trust model are unchanged and any outage
falls back to direct peer play.

- **Sparring peer — ships in [`sparring/`](sparring/), run it yourself.** A conformant practice
  implementation that plays a full six-sub-game series, with mutual audits and all four artifacts,
  needing no dependencies: `python -m sparring.cli selfplay`. Local rather than hosted, on purpose
  — you get it on your own schedule, with no third party in the path.

  It plays a **live series over MCP between two separate processes** — handshake per sub-game,
  sealed turns, mutual audit, four artifacts, both sides deriving one shared `game_uid` — and CI
  runs a two-server version of exactly that on every push. `python -m sparring.cli selfplay` needs
  no dependencies at all; `SPAR_PEER=<your MCP url> docker compose -f
  sparring/docker-compose.await.yml up` stands one up that awaits your implementation and dials it
  back. `SPAR_PEER` is load-bearing: MCP pushes one way per session, so a peer that only listens
  answers tools and plays nothing — without it the compose runs the tools-only mode.

  It is an **uncounted warm-up** (App. E rule 52): nothing is owed by either side, no report is
  produced, and it has no mail code at all — a property checked at startup rather than promised.
  Its group id is reserved with the `sparring-` prefix, so a practice artifact can never be
  mistaken for a league pairing: `game_id` is built from the group ids.

  It is a third independent implementation of the **game layer** — rules, engine, state machine,
  wire, receiver contract, artifacts, written from this document and the book. Its byte-level
  constructions are imported from `verify_vectors.py` rather than rewritten, so it cannot drift
  from the published vectors and equally cannot catch a bug inside them. Playing a real team
  remains the true test.
- **Lobby via a league GitHub repo.** Roster as one JSON file per team (maintained by PR); each
  scheduled match gets an Issue carrying its `config/game.json` and, at settlement, both teams'
  report hashes and links to their committed artifacts. Registration + scheduling + a public
  coordination trail, zero hosting, no single owner, graceful fallback to a hand-exchanged config.

## Appendix C — provenance, and the relationship to the book

This kit was born (as a full protocol draft, v0.1–v0.3) from the EX06 inter-group bonus, where two
independent implementations played live over Cloudflare tunnels and settled on a byte-identical
report hash. Issue #1 (partner team anrbj666) contributed two review passes, including the
transcript-DAG idea now in Appendix A. When the official book v3.0.0 published, the game's actual
rules and transport were fixed by the book, so this repo re-scoped from "a candidate standard" to
"a conformance kit + agreed-enhancements layer on top of the book."

The constructions here were confirmed byte-for-byte against the official reference implementation
(`github.com/rmisegal/Game-P2P-Cop-Chase`, code v3.0.0): the canonical form, the
`SHA256(canonical|nonce)` commit, the terms signature, the `game_uid` derivation, and the pheromone
math. The book (© Dr. Segal) and the reference code (Educational-Use-only) are cited and linked,
never copied — every vector in this repo is generated from our own synthetic inputs by
`gen_vectors.py`. Hash outputs are facts; the algorithms are the book's; the words here are ours.

## Appendix D — deployment notes (observed in live cross-implementation runs)

- **fastmcp peers return HTTP 421 behind tunnels unless the tunnel rewrites the Host header**
  (issue #4). The MCP streamable-HTTP server's DNS-rebinding protection rejects requests whose
  `Host` is not the bind address — which is every request arriving through a tunnel. Fix at the
  tunnel, no code changes: Cloudflare named tunnel → `originRequest.httpHostHeader:
  127.0.0.1:<port>`; ngrok → `--host-header=rewrite`. Verified by full mini-games against the
  unmodified reference peer over public URLs in both role pairings (mutual audits Verified OK).
  Pre-match checklist probe: "does your public URL answer a tool call?" catches it in seconds.
