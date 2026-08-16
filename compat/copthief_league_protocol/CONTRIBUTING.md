# Contributing

This kit exists so that two teams who have never spoken can still finish a clean game. That only
works if it is easy to tell us we are wrong. Most of what follows is about making a disagreement
*checkable* rather than about etiquette.

You do not need permission to open an issue, and you do not need to be in the league.

---

## Before you file: get your bytes on the table

Almost every interop dispute is a serialization difference, and almost none of them are visible in
a hash. So whenever you report a mismatch, **include the canonical string, not just the digest.**

```
python verify_vectors.py
```

If that passes on your machine but your implementation disagrees with a fixture, the fixture and
your code are computing over different bytes, and the bytes are the evidence. A report that says
"I get `4f1c…`, you get `9a02…`" cannot be diagnosed by anyone. A report that shows both preimages
usually diagnoses itself — a `א` where a native `א` should be, a `0.10000000000000001` where
`0.1` should be, a space after a separator.

---

## The four kinds of issue

### 1. Conformance failure — "my implementation disagrees with a fixture"

The most valuable kind. Include:

- the fixture and the case (`vectors/commit_reveal.json`, `commit #2`);
- **your canonical string** for that case, verbatim, and ours;
- your language and its JSON serializer, if it isn't Python.

Two outcomes, both fine: your serializer diverges and now you know before match day, or **the
fixture is wrong** and you have found something that would have cost two teams a match.

### 2. Reproduction — "I built this independently and my numbers match"

This is what promotes a `PROPOSED` fixture to `PROMOTED`, so it is worth filing carefully. See
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) for the bar. State:

- which fixture, and **which cases** you reproduced (partial is fine, and is recorded as partial);
- how your implementation was built — from the book, from the SPEC prose, or from these vectors.
  **This is the load-bearing detail.** An implementation corrected by reading our numbers confirms
  our numbers to itself and nothing more, and we will record it that way;
- whether your implementation predates the fixture.

### 3. Proposal — "the kit should also pin X"

Say what breaks without it. The bar is specifically *interop*: a construction earns a place here
if two independent implementations can silently disagree on it and lose a game as a result.
Strategy, performance, architecture and ergonomics are out of scope by design — they are private,
and the SPEC says so.

New constructions land as `PROPOSED`. That is not a hedge; it is an accurate statement that one
implementation has it.

### 4. Operational report — "this failed against a real peer"

Tunnel behaviour, host headers, delivery semantics, handshake races. These are how SPEC Appendix D
and §7.1 got written. Include what you observed and what you concluded, and keep them separate —
the observation stays useful even if the conclusion turns out to be wrong.

---

## How we respond

**Candidly, per item.** Every item in a review gets an explicit accept or decline with a reason.
Declining is normal and expected; a review where everything is accepted is a review nobody read
properly.

**You close your own issue.** When we push a fix, we say so and leave the issue open. The person
who reported it verifies and closes — we do not close other people's issues on their behalf,
because "fixed" is not our call to make.

**You get named.** Substantive contributions are credited by name in `SPEC.md` beside the thing
contributed and in the fixture's own `description`. That is provenance, not politeness: a reader
deciding how far to trust a construction should be able to see who else has looked at it.

---

## Changing the repo

**Fixtures are generated, never hand-edited.** `vectors/*.json`, `vectors/INDEX.md` and
`examples/sample_exchange.md` are build artifacts. To change one, change the reference construction
in `verify_vectors.py`, then:

```
python gen_vectors.py
python examples/gen_sample_exchange.py
python verify_vectors.py
```

CI runs exactly that and then `git diff --exit-code`, so a hand-edited fixture fails the build. A
fixture that disagrees with the code that generates it is worse than no fixture.

**A new fixture needs a tier.** Register it in the `TIERS` map at the top of `gen_vectors.py`;
`_write` refuses to write a fixture whose tier is not declared, and the checker refuses a fixture
that does not declare one. Tier meanings: [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md).

**Stdlib only.** The kit runs with no dependencies and no packaging, on Python 3.12+, so that
verifying it is never blocked on an install. Keep it that way for anything under the repo root.

**Nothing in the tree may be untrue of the tree.** No counts that a later commit can falsify, no
"two implementations reproduced this" without the citation, no documented behaviour that the code
does not have. Where a number would go stale, generate it or print it at runtime instead.

---

## What this kit is not

It is not the game spec — **the book is**: *Distributed Cops-and-Robbers over a Peer-to-Peer
Network*, Dr. Yoram Reuven Segal, v3.0.0, with the
[reference implementation](https://github.com/rmisegal/Game-P2P-Cop-Chase). Where the book and this
kit disagree, the book wins and the disagreement is a bug worth filing. Where the book disagrees
with *itself*, the kit names the contradiction and the choice it made rather than picking silently
(see SPEC §3).
