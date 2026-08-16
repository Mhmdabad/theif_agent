# Cop–Thief League Interop Kit

**Everything two teams need to go from "never met" to a clean, counted game — verified on your
own machine, before you ever talk to an opponent. Any team that passes these checks can play any
other team that passes them.**

For the official final-project assignment: *Distributed Cops-and-Robbers over a Peer-to-Peer
Network*, Dr. Yoram Reuven Segal, book v3.0.0 (Orchestration of AI Agents, University of Haifa).

## In plain words

- **The danger.** In this game your opponent checks your bytes: every move you make is hashed,
  and at the end of each game they re-hash your log with *their* code. Two honest agents whose
  JSON differs by one escaped character will each conclude the other cheated — and the rules
  score that **zero for both teams**. Most of what can go wrong in the league is this, in some
  disguise.
- **What this kit is.** A set of checks you run locally, tonight, that prove your bytes will
  match — before any opponent is involved. Pass them, and you and every other team that passes
  them can schedule a game knowing the audits will come out clean.
- **What else is in the box.** A practice opponent that plays full series against you locally
  (and refuses bad handshakes the way a real team would, telling you exactly why); a playbook
  covering the whole road from "first hello" between two teams to the one counted game —
  including the **friendly games** the book itself recommends playing first; and the mistakes
  that already cost two real teams burned evenings, written up so they don't cost you yours.
- **Why it pays.** Your league grade is driven by how many *distinct* opponents you finish
  clean games with. Every team using this kit is an opponent you can play with confidence —
  and that cuts both ways, which is exactly why we published it.
- **Proof, not promises.** Two independent teams walked exactly this path — friendlies first,
  then a counted series that ran six sub-games in 78 seconds with every audit clean and both
  reports byte-agreeing. The details, including the score, are below.

### → [**Start here**](docs/START-HERE.md) — four commands, four pass criteria, no account and no conversation with anyone.

```bash
git clone https://github.com/Imreec/copthief-league-protocol && cd copthief-league-protocol
python verify_vectors.py          # do your bytes match everyone else's?
python -m sparring.cli selfplay   # a full six-sub-game series against a real opponent
```

Both run on a clean Python 3.12 with **no dependencies installed**.

## What the game is, in three sentences

Two agents — a cop and a thief — play on a small grid over MCP, with **no referee and no shared
board**: neither can see the other's position, and each enforces the rules on its own side. Every
move is sealed with a SHA-256 commitment and revealed only at an end-of-game audit, where **your
opponent re-hashes your log with their serializer**. A series is six sub-games with roles
alternating, and both teams then report the result independently.

That audit is why this repo exists. Two *honest* implementations whose JSON differs by one escaped
character will each fail to reproduce the other's commitments, each conclude the other cheated, and
**both score zero**.

**This is not the game spec — [the book](https://github.com/rmisegal/Game-P2P-Cop-Chase) is.** The
book fixes the transport (MCP/FastMCP), the game (hidden positions, the pheromone scent, capture,
scoring), the commit-reveal, the `config/game.json` constitution, and the Gmail-API reporting. This
repo adds the one thing the book does not ship: **machine-checkable vectors** for the byte-level
constructions two independent implementations must agree on — plus a practice opponent, the
operational knowledge two teams paid for in burned evenings, and a few opt-in enhancements.

## Why this exists

The book says "hash the canonical JSON." But two clean-room codebases that serialize even slightly
differently will silently fail each other's post-game audit and both take a **technical loss** —
zero points. The classic trap: the reference hashes with `ensure_ascii=False` (native UTF-8), so a
Hebrew hint like `אני ליד הכיכר` is hashed raw; an implementation that `\uXXXX`-escapes it computes
a different hash, the opponent's audit re-hash of your revealed log misses, and the match voids for
both sides. There is no vector in the book to catch this before match day. There is one here.

It gets sharper: the release itself publishes **three inconsistent commit constructions** (the
book's ch.5 listing, its audit-chapter snippet, and the reference implementation each hash
differently — and the book's own clarification page makes printed listings non-binding, so the
choice formally falls to the teams). Implement from the wrong page in good faith and you fail
every audit against a team that implemented from another. This kit pins the reference's form —
which is also the only one of the three that binds the full record (the audit-snippet form hashes
just `nonce|move`, leaving `state` and `intent` unbound) — documents the contradiction per the
book's academic-freedom clause, and ships a `divergent_forms` vector hashing the same sealed
record under all three, so a failing team can see in seconds which construction it accidentally
built.

Your competitive grade is a **league rank → 75–100**, and it's driven by how many *distinct*
opponents you can finish a clean game with (first meeting only; up to 10). Every team that can't
hash-agree with you is a game you can't score. This kit is how a team certifies — alone, on its own
schedule — that it will interoperate.

## What's here

**New here? [`docs/START-HERE.md`](docs/START-HERE.md) is the ordered path** — four gates, a
glossary of the vocabulary the rest of these documents assume, and what to read before contacting
anyone. The table below is the map, not the route.

| File | What it is |
|---|---|
| [`docs/START-HERE.md`](docs/START-HERE.md) | **The onboarding path.** Four runnable gates with pass criteria, plus the glossary |
| [`SPEC.md`](SPEC.md) | The interop surface: canonical JSON, commit-reveal, agreement signature + `game_uid`, pheromone math, report bytes, locked-model declarations — mapped to the book's chapters, plus opt-in enhancements |
| [`vectors/`](vectors/) | Machine-generated fixtures, one file per construction — each declares its own tier; roster at [`vectors/INDEX.md`](vectors/INDEX.md) |
| [`verify_vectors.py`](verify_vectors.py) | Stdlib-only reference checker — `python verify_vectors.py`; prints the roster and the totals it ran |
| [`gen_vectors.py`](gen_vectors.py) | Regenerates every fixture from the reference constructions; CI fails on drift |
| [`examples/`](examples/) | A worked exchange (agreement → sealed steps → audit → settlement), every hash real and regenerable — plus [`pairing-artifacts/`](examples/pairing-artifacts/), a full six-sub-game artifact bundle in the played counted format, generated and verifiable with `check_artifacts.py` |
| [`sparring/`](sparring/) | A practice opponent you run locally — full rulebook, no mail, simple brains. `python -m sparring.cli selfplay`, or stand one up for your peer to dial |
| [`docs/WARNINGS.md`](docs/WARNINGS.md) | The mistakes that cost points — including the opponent's. Read before configuring any recipient |
| [`docs/LEAGUE-OPS.md`](docs/LEAGUE-OPS.md) | How a scheduled window actually runs: the T-protocol, netcheck discipline, topologies, budget math |
| [`docs/PAIRING-PLAYBOOK.md`](docs/PAIRING-PLAYBOOK.md) | The whole lifecycle of one pairing: the first-contact message, role allocation, the friendly campaign and its report-compare ritual, arming and running the one counted series, the retry agreement. Written from a completed campaign |
| [`tools/`](tools/) | `check_artifacts.py` (your four artifacts, before anyone sees them) and `netcheck.py` (your network, before you name a start time) |
| [`docs/EVIDENCE.md`](docs/EVIDENCE.md) | Real frames off the wire — handshake, sealed step, audit, all four artifacts. Generated, so it cannot drift |
| [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) | What `CORE` / `PROMOTED` / `PROPOSED` / `ENH` claim, and what it takes to promote one |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to report a conformance failure, file a reproduction, or propose a construction |

The constructions were confirmed byte-for-byte against the official reference implementation. Every
vector is generated from our own synthetic inputs — no reference content is copied.

## The interop surface (what must match cross-team)

1. **Canonical JSON** — `sort_keys=True, ensure_ascii=False, separators=(",", ":")`, UTF-8.
2. **Commit-reveal** — `SHA256(canonical_json(payload)|nonce)`; the opponent re-hashes your
   revealed log at audit.
3. **Agreement signature** — `SHA256(canonical_json(terms)|nonce)`; the pre-game gate.
4. **`game_uid` and `game_id`** — `UUID(SHA256(canonical(terms)|sorted-group-ids)[:16])` and
   `"-vs-".join(sorted(group_ids))`. Both sort the pair, so neither peer has to be told which order
   to use; a peer that names itself first gives one match two different `game_id`s.
5. **Pheromone field** — radial emission + per-step decay (self-test, but breaks your belief map if wrong).
6. **Report bytes + consensus signature** — the emailed body is the exact canonical bytes that
   were hashed, and the consensus signature inside the report uses a **second (spaced)
   serialization** with sign-then-insert ordering (SPEC §6 — found by Alon's team).
7. **Locked-model declarations** — one doc schema (`family`/`name`/`params`/`example`) serving
   scent models, wire shapes, information modes and scent bindings, hashed and declared at
   negotiate time. Refusal fires only when **both** peers declare and disagree; silence never
   refuses (SPEC §7).

Four more are **behaviour** rather than bytes, pinned as truth tables because answering them
differently costs a game just as surely as a bad hash — and unlike a hash, you cannot catch these
by comparing a digest with a partner: the locked-model refusal rule (§7), the at-least-once
receiver contract (§7.1), the pairing declaration `sub_game_number` + `role` (§7.2), and the
`game_uid` declaration (§7.3, `PROPOSED`).

Everything else — strategy, GUI, prompts, infra — is private and needs no agreement.

## This has been played, not just written

None of the above is theoretical. On **2026-07-25** two independently built implementations played
a **full six-sub-game series** against each other over public tunnels, on these constructions:

- one wire `game_uid`, derived at the handshake and shared across all twelve halves;
- **every mutual audit clean, in both directions** — each side re-hashed the other's revealed log
  with its own serializer and reproduced every commitment;
- both teams' final reports agreeing on every game value — winner, totals, per-sub-game outcomes;
- roles alternating across the six sub-games, one report fired automatically per side.

It also surfaced one substantive defect, which is why [`docs/WARNINGS.md`](docs/WARNINGS.md) §2
leads with it: one side derived its `game_uid` from its **whole config** rather than from the flat
negotiated terms. That is the sneaky failure — the uid was perfectly deterministic and identical
across all four of that team's artifacts, so they joined each other correctly and looked healthy;
only the *cross-team* join failed, while every game *value* in the two reports matched exactly.
Nothing on either side had reason to look. Two counted reports naming one match by two uids is what
App. E rule 35 scores zero, for *both* teams. `tools/check_artifacts.py` exists because of that.

The series took **seven scheduled windows** to complete. Every one of the six that burned was a
launch-time default rather than a protocol fault, every abort was clean and before any report went
out, and the ones worth learning from are written up — anonymised — in
[`docs/LEAGUE-OPS.md`](docs/LEAGUE-OPS.md). What that run produced is most of
[`docs/WARNINGS.md`](docs/WARNINGS.md), the two tools in [`tools/`](tools/), and the promotions in
[`docs/GOVERNANCE.md`](docs/GOVERNANCE.md).

A real inbound frame from that run — redacted, with the redaction marked — is in
[`docs/EVIDENCE.md`](docs/EVIDENCE.md) §6. It shows a second implementation declaring locked-model
hashes **byte-identical** to this kit's registered documents, which is the whole point of pinning
the document schema rather than just the hash.

**And on 2026-08-04 the same pairing played its one counted series** — the end state this whole
kit exists to reach. The campaign before it (2026-08-01 → 04): five clean friendly series in a
single day, two mutual repo audits with written dispositions, then six counted sub-games in about
78 seconds — six clean mutual audits, one `game_uid` (`e351176a…`), zero refusals of any kind,
one result-only report per team, and the two reports' `mutual_agreement.sha256` **byte-identical**.
The result on the record: **30–90, winner anrbj666**, all six sub-games — with the App. F
diversity reward correctly attaching to them and not to us, and both teams' league fields agreeing
field-for-field. We publish the score with the protocol facts because the two are one artifact:
a kit that only cited runs it won would be advertising, not evidence. The whole lifecycle of that
pairing — first contact to counted report — is written up as
[`docs/PAIRING-PLAYBOOK.md`](docs/PAIRING-PLAYBOOK.md), contributed by the team that won.

Separately, the [sparring peer](sparring/) plays a full series over MCP between two separate
processes, and CI re-runs a networked sub-game on every push.

## Credit

This kit is better than we could have made it alone. **anrbj666 — Alon Engel and Renat
Karimov** — have been its most demanding readers and are the reason several parts of it exist:

- **two full review passes** on the early drafts (issue #1), including the transcript-interlock DAG
  now in Appendix A — they found that per-sender hash chains with no cross-links can be re-forged
  wholesale offline, which is not an obvious hole;
- **the consensus signature's second canonical form** (SPEC §6) — that settlement signatures use
  the *spaced* serialization with sign-then-insert ordering. Two teams that disagree on that detail
  fail at the exact moment they must agree on a result;
- **the clean-room reproduction** that promoted `multiplicative_book_v1` (issue #6), byte-exact
  from an implementation built from the book alone, predating our fixtures — which is what the
  promotion bar in [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) actually requires;
- **the T-protocol** (`docs/LEAGUE-OPS.md` §1), which fixed days of half-started windows on the
  first attempt;
- **the at-least-once receiver contract** (SPEC §7.1), worked out jointly after a live
  duplicate-delivery drill over a public tunnel;
- **the root cause of the `game_uid` divergence** (SPEC §6, §7.3) — including correcting our own
  first published diagnosis of it. We wrote that the uid had been "freshly minted"; it had not, and
  the real mechanism is both subtler and more useful to teach.

Where we disagreed, the disagreement improved the result: on the scent kernel they read the printed
figure as an exact Gaussian and were right about its shape, we read it as matching no clean formula
and were right about its reproducibility — so the kit pins the printed values *and* documents the
closed form, which follows from both readings (SPEC §5.1).

Reviewers are credited by name throughout, beside the thing they contributed. That is provenance,
not courtesy: a reader deciding how far to trust a construction should be able to see who else has
looked at it.

## How to adopt

1. Read [`SPEC.md`](SPEC.md) — it's short and maps each construction to a book chapter.
2. Run `python verify_vectors.py` to see the reference constructions reproduce every fixture.
3. Port the checks into your own suite and point them at `vectors/*.json`. When your implementation
   reproduces every **CORE** vector, your bytes match every other conformant team's.
4. Check your own artifacts before anyone else does — `python tools/check_artifacts.py <dir>`.
   It catches the defect that zeroes **both** teams: a report whose `game_uid` is not the one the
   handshake derived.
5. Before you name a start time, prove your network: `python tools/netcheck.py <peer-url>` to
   classify their edge, and `--loopback <port> <your hostnames>` to prove your own receiving path.
   A bare `502` check cannot tell a healthy idle tunnel from one with no ingress.
6. Read [`docs/WARNINGS.md`](docs/WARNINGS.md) before configuring any recipient, and
   [`docs/LEAGUE-OPS.md`](docs/LEAGUE-OPS.md) before agreeing a window.
7. Rehearse a whole series against the [sparring peer](sparring/) — a real opponent over MCP,
   full rulebook, no mail. It puts Hebrew and an emoji on the wire on purpose, so a serializer
   that escapes non-ASCII fails *there* rather than at a real opponent's audit.
8. Ready for a real team? Open with the first-contact message in
   [`docs/PAIRING-PLAYBOOK.md`](docs/PAIRING-PLAYBOOK.md) (an issue on this repo reaches us),
   then play **friendlies** — full-discipline warm-ups, reports to yourselves only — until the
   report diff passes field-by-field in *both* directions. Only then arm the one counted game.
9. The real acceptance test: feed a partner's revealed log to your verifier and yours to theirs —
   both audits must pass with zero `tamper_forfeit`.

## Enhancements (opt-in)

The book invites teams to agree on extras and exploit undefined gaps, as long as it's signed into
`config/game.json` and weakens no mandatory minimum. This repo offers, as opt-ins: a transcript
interlock DAG (`prev`/`prev_recv`) that hardens the book's per-step commits against wholesale
re-forgery; a joint-seed coin flip for randomized-but-fair starts; synchronized fixture scheduling;
and demo staging. See SPEC Appendix A.

## Relationship to the book (and IP)

The book (© Dr. Segal) and its reference implementation (Educational-Use-only) are the authority;
this kit is complementary, not a competing standard. We cite the book by chapter, link the reference
repo, and copy neither its text nor its code. Hash outputs are facts, the algorithms are the book's,
the words here are ours.

— Team ImreEyal
