# Governance — what the tiers mean, and what it takes to move between them

Every fixture in [`vectors/`](../vectors/) carries a **tier**. The tier is a claim about *how much
you should trust it*, and this page is the only authoritative definition of those claims. If some
other document in this repo paraphrases the rule and disagrees with this page, this page wins and
the paraphrase is a bug.

Read this before opening an issue that proposes a new construction, and before believing a
`PROMOTED` label.

---

## The four tiers

| Tier | What it claims | What you should do about it |
|---|---|---|
| **`CORE`** | Two independent implementations **must** produce these bytes, or the game cannot start, cannot audit, or cannot settle. Confirmed byte-for-byte against the official reference implementation. | Reproduce every one of them before you play anyone. This is the interop floor. |
| **`PROMOTED`** | Not required by the book, but **a second independent implementation has reproduced it**. The claim has survived contact with someone else's code. | Safe to build against. Still declare it — see the locked-model rule in [`../SPEC.md`](../SPEC.md) §7. |
| **`PROPOSED`** | Published so that a second implementation *can* reproduce it. **At most one implementation** — an entry published for two first implementations to build to says zero, explicitly. It may be wrong in ways nobody has noticed yet. | Read it, reproduce it, and tell us — reproducing it is what promotes it. Do not assume an opponent has it. |
| **`ENH`** | An opt-in enhancement (SPEC Appendix A). Binding on a pair **only** if both teams signed it into their `config/game.json`. | Ignore it unless you and your opponent both agreed to it. |

Tiers are about *evidence*, not about importance. `CORE` outranks `PROMOTED` because the book and
the reference force it, not because it was checked harder.

---

## The promotion bar

> **A fixture is promoted from `PROPOSED` to `PROMOTED` when a second, independent implementation
> reproduces it — and the evidence for that is cited in this repository.**

All three clauses bind.

**"Second."** Ours does not count. The kit's own `verify_vectors.py` reproducing a fixture proves
only that the generator and the checker agree, which they do by construction — `gen_vectors.py`
imports the checker. Self-consistency is not evidence.

**"Independent."** The other implementation must not have been derived from these vectors. The
strongest form is a clean-room build from the book that *predates* the fixture; the next strongest
is a build from the SPEC prose without reading the fixture values. An implementation that was fixed
*by* looking at our numbers has confirmed our numbers to itself and nothing more.

**"Reproduces."** Byte-exact on every case in the fixture, with zero tolerance, or — where the
fixture pins behaviour rather than bytes (a refusal truth table, a receiver contract) — the same
decision on every row. Partial reproduction is a partial result: promote the cases that were
reproduced, or don't promote.

### What counts as evidence

Two forms, both acceptable:

1. **A clean-room reproduction** — another team runs their implementation against the fixture and
   reports the result. Cite the issue number and the team.
2. **A live cross-implementation run** — the construction was exercised by two implementations
   playing each other, and the artifacts show it. Cite the run: date, what was played, and which
   observable in the archived records demonstrates it.

The citation goes **in the tree** — in `SPEC.md` beside the claim and in the fixture's own
`description`, so a reader can check the basis of a `PROMOTED` label without leaving the repo and
without asking us. A promotion whose evidence is only in someone's memory is not a promotion.

Where the evidence lives in a private repository, cite the **run**, never the path: the reader
needs to know what happened and when, not to be pointed at something they cannot open.

### What a promotion does *not* do

- **It does not make anything mandatory.** Only the book makes things mandatory. A `PROMOTED`
  fixture is still opt-in unless it is also `CORE`.
- **It does not widen what may be chosen.** The book's Appendix F binding table is unaffected by
  anything on this page. A construction that lowers a binding minimum is refused by the table
  regardless of how many implementations reproduced it.
- **It does not travel.** Promoting `X` says nothing about `Y`, even if the same team reproduced
  both and even if they ship together.

### Demotion, and what happens when the book revises

A `PROMOTED` fixture returns to `PROPOSED` if the evidence turns out not to support it — a
reproduction that was not independent, a case that was never actually run. Say so in the commit;
a quiet demotion is the same failure as a stale promotion.

**If the book revises**, every `CORE` construction is re-verified against the new reference code
*before* the vectors are updated. `CORE` means "the reference does this"; a new reference means the
claim has to be re-earned, not carried forward.

---

## How a tier is recorded (and why it cannot go stale)

The tier is declared **once**, in the `TIERS` registry at the top of
[`../gen_vectors.py`](../gen_vectors.py):

```python
"scent_book_v3.json": ("PROMOTED", "§5.1", "`multiplicative_book_v1` — the book's own scent model"),
```

From there:

- `_write()` stamps it into the fixture as `"status"`, and **refuses to write a fixture whose tier
  is not registered**;
- `verify_vectors.py` reads `status` back for its runtime banner, and **refuses a fixture that
  declares no tier** — it never carries a tier literal of its own;
- `gen_vectors.py` regenerates [`../vectors/INDEX.md`](../vectors/INDEX.md) from the same registry;
- CI regenerates everything and fails on any drift.

So the tier is written in one place and read in three, and prose elsewhere links the index rather
than restating it. For the current counts, run the checker — its last-but-one line reports what it
actually ran, in the form:

```
<N> checks across <M> fixtures — <n> CORE, <n> PROMOTED, <n> PROPOSED, <n> ENH
```

(No number is written here on purpose. A count in prose is a claim that a later commit can
falsify, which is the failure this whole section exists to prevent.)

**Why this is mechanised rather than remembered.** It was not, and it drifted.
`multiplicative_book_v1` was promoted on 2026-07-20; the commit updated `SPEC.md`, the generator's
description and the fixture, and missed the checker's banner and the README's counts. For six days
the repo shipped a fixture that said `PROMOTED` while its own verifier printed `[PROPOSED]` beside
it — a kit whose single promise is that its claims are checkable, making an unchecked claim about
itself. The registry exists so that cannot recur.

---

## Current promotions

| Fixture / section | Promoted | Evidence |
|---|---|---|
| `multiplicative_book_v1` — [`vectors/scent_book_v3.json`](../vectors/scent_book_v3.json), SPEC §5.1 | 2026-07-20 | Clean-room reproduction by **anrbj666** (Alon Engel, Renat Karimov), issue #6: byte-exact on the kernel, both emit cases, all three walk turns, both scalar traces and every ordering-probe case with zero tolerance — from an implementation built from the book alone, predating these vectors. Reconfirmed on the wire: their peer declared this exact doc hash throughout the run below. |
| At-least-once receiver contract — [`vectors/delivery_contract.json`](../vectors/delivery_contract.json), SPEC §7.1 | 2026-07-26 | Implemented independently by two teams (2026-07-22, from a live duplicate-delivery drill and a reading of the reference source), then exercised by both across the run below with mutual audits clean in both directions. |
| Pairing declaration — [`vectors/pairing_declaration.json`](../vectors/pairing_declaration.json), SPEC §7.2 | 2026-07-26 | Both `sub_game_number` and `role` were declared **and asserted** by two independent implementations across the run below; the opponent's inbound greetings carry both fields top-level, alternating correctly with the role swap. |
| `wire_shape: reference-v3` — [`vectors/locked_model.json`](../vectors/locked_model.json), SPEC §7 | 2026-07-26 | Two independent implementations played the whole run below on this shape, and the opponent declared a `wire_shape_sha256` **byte-identical to the registered doc**. The checker asserts that equality, so this row is verified rather than asserted. |
| `game_id` = the sorted pair — [`vectors/game_uid.json`](../vectors/game_uid.json), SPEC §4 | 2026-07-27 | Reference-derived, and **independently matched by two implementations**: anrbj666's `build_game_id` sorts the pair in their own code, written before this kit pinned it, and the imreeyal implementation adopted the sorted derivation on 2026-07-27. Neither agreed it with the other. |
| `info_mode: belief` — [`vectors/locked_model.json`](../vectors/locked_model.json), SPEC §7 | 2026-08-04 | Both implementations declared `info_mode_sha256` **byte-identical to the registered doc** in every handshake of run 2 — the five-friendly campaign and the counted series, both role directions. Same evidence class as the `wire_shape` row, and verified the same way: the fixture carries the observed hash and the checker asserts it still equals the registered doc. (In run 1 the mode travelled as a bare string; that limit is discharged, and is why this row post-dates the others.) |

**The runs** these rows cite. **Run 1, 2026-07-25**: the first fully autonomous cross-team series —
six sub-games under one wire `game_uid`, roles alternating, mutual audits clean both ways,
imreeyal vs anrbj666. **Run 2, 2026-08-01 → 04**, same pairing: a five-friendly campaign and then
the pairing's **counted series** (2026-08-04) — six clean mutual audits, zero refusals, one
result-only report per team, and the two reports' `mutual_agreement.sha256` byte-identical.
Per the rule above, the runs are cited and not the paths: their logs live in private
implementation repositories.

**Currently `PROPOSED`**: the **`game_uid` declaration** at negotiate (SPEC §7.3,
[`vectors/uid_declaration.json`](../vectors/uid_declaration.json)). Run 2 strengthened it without
promoting it: **both** implementations declared the derived uid in every handshake, values
matching — but the fixture is a behaviour table, and its **refuse** row has never fired
cross-team; only one implementation's tests pin it. A behaviour table promotes on decisions, not
on the happy path, so it stays `PROPOSED` until a cross-team drill (or a live mismatch, which
nobody should wish for) exercises the refusal. Recorded here so the difference between "declared
by both" and "reproduced" stays visible.

**Currently `PROPOSED` with *zero* implementations** — the weakest thing this repo publishes, and
labelled so rather than dressed up: the **`smell_binding` family** (SPEC §7.4,
[`vectors/smell_binding.json`](../vectors/smell_binding.json)). Both league teams agreed on
2026-07-29 that it is worth doing; neither has built it. It is published so that a *first* and a
*second* implementation can each build to the same bytes instead of to each other. Its promotion
bar is the ordinary one **plus a live warm-up drill**, because it changes a commit preimage: both
peers must change what they seal on the same turn, and a mid-series divergence there is the
contradiction App. E rule 35 zeroes both teams for. It never debuts in a counted game.

Still not promoted, and why: **`info_mode: exact`** — run 2 promoted only `belief`, the mode both
teams actually declared; promoting the counterpart nobody has put on the wire would be exactly
the promotion-by-association the bar forbids. **`hardware_spec_sha256`** was observed on the wire
as a fourth family and is deliberately not registered; the doc underneath it is unknown to us,
and registering a family whose field set we have not seen would reintroduce the ad-hoc-dict
problem §7 exists to remove. **`bookletter-v3`** keeps four unpinned preimages and stays
`PROPOSED`.

---

## Credit

Contributions are credited by name, in the SPEC beside the thing contributed and in the fixture's
`description`. This is not courtesy — it is provenance: a reader deciding how much to trust a
construction should be able to see who else has looked at it.

The reviewer who opens an issue **closes it**, after verifying the fix. We do not close other
people's issues on their behalf.

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to file a reproduction, a conformance
failure, or a proposal.
