# The sparring peer

A practice opponent you run **locally**. The full rulebook, no mail, simple brains.

Play a complete six-sub-game series against it before you ever contact another team — and find
out about your serialization, your receiver contract and your artifacts on your own schedule
instead of during someone else's window.

```bash
# a full six-sub-game series against itself — no dependencies, a few seconds
python -m sparring.cli selfplay

# play a series against YOUR implementation: both sides dial each other
# (MCP pushes one way per session, so serving alone answers tools but plays nothing)
python -m sparring.cli serve --port 8931 --peer http://localhost:<your-port>/mcp --role thief
# and point your peer at http://localhost:8931/mcp
```

## Status: what is verified

Everything below is re-verified by CI on every push.

- **The whole game layer with no dependencies installed** — a full six-sub-game series, role
  alternation, clean mutual audits, fourteen artifacts under one `game_uid`, over an in-process
  transport.
- **That same seeded series again over a transport that duplicates, reorders and
  drops-then-retries**, producing a *byte-identical outcome ledger*.
- **A live series over HTTP between two separate processes** — the real thing. Two peers, two
  FastMCP servers, handshake per sub-game, sealed turns, mutual audit, artifacts. Both sides
  settle every sub-game identically and derive **one shared `game_uid`**, and CI runs a
  single-sub-game version of exactly this on every push.
- The four MCP tools under the reference's names, with `submit_audit` taking `payload` and the
  others `message`, and no handler blocking.
- The artifacts it writes pass `tools/check_artifacts.py`; its logs pass `cli replay`.

A representative full run (two processes, `--policy random`): six sub-games settled
`survival, survival, capture, capture, survival, capture`, every mutual audit *Verified OK* both
ways, 14 artifacts per side, and **one `game_uid` across all 28 files**.

> **The bug that only a live run could find.** In self-play both sides shared one outcome
> variable, which hid the fact that the thief computed its honest answer to a capture claim and
> never sent it. Over a real transport the cop cannot see the board, so an answer that does not
> travel means the cop waits out its budget and settles a game it *won* as a timeout — two peers
> describing the same game differently, which is the shape App. E rule 35 zeroes for both teams.
> Fixed by making the peer deliver what it owes before it stops talking, and there is now a
> two-server CI test that would catch it again.

---

## What you get

A conformant opponent that will refuse you for the same reasons a real team would, and say which:

- the four MCP tools under the reference's names, **including the asymmetry** — `submit_audit`
  takes `payload`, the other three take `message`;
- a signed-terms handshake that distinguishes **terms absent** (a wire-shape fault on the sender's
  side) from **terms differing** (a constitution disagreement) — and prints the canonical strings,
  because a float that differs only in `repr` is invisible in a value diff and fatal to a signature;
- locked-model declarations in all three families a real pairing exchanges — `scent_model`,
  `wire_shape`, and `info_mode` as a **doc hash** (`020947da…`, byte-identical to the kit's
  PROMOTED `belief` registration) — plus pairing declarations and the at-least-once receiver
  contract;
- the **derived `game_uid` declared at negotiate** (SPEC §7.3) whenever the opponent is known,
  and refused by name on mismatch — derive yours from the wrong input on purpose and this peer
  is the only opponent that will tell you *at the handshake* instead of in a report diff the
  next morning;
- commit-reveal with a real end-of-game **mutual audit** that will call you tampered if your bytes
  differ from the kit's — which is exactly what a real opponent's audit would do;
- all four artifacts under one `game_uid`, named by the book's App. F grammar.

**It speaks Hebrew and emoji on purpose.** With `--hint-lang mixed` (the default) some sub-games
carry Hebrew hints and one carries an astral-plane character. SPEC §2 calls `ensure_ascii=False`
the single most important fact in the kit, because a serializer that escapes non-ASCII produces
hints your opponent cannot re-hash — and the failure surfaces as a false `tamper_forfeit` that
zeroes *both* teams. A peer that only ever said ASCII would let you finish a whole rehearsal
without discovering it. Use `--hint-lang en` if you want that off.

## What you do *not* get, by construction

| | |
|---|---|
| **No mail. At all.** | Not "disabled" — absent. `python -m sparring.guards.no_mail` scans the source and refuses to let the peer start if a mail surface exists, and the manifest hash of that scan is written into the declaration artifact. Seven rules, including outbound-network confinement, because a package could import no mail library and still open a socket to port 587. |
| **No report.** | Sparring is an uncounted warm-up (App. E rule 52), so nothing is owed by either side. The result artifact carries **no signature key at all**, only `"settlement": "not_owed"` — a label can be edited, but a missing preimage cannot be emailed. Its league fields ride in the **friendly posture** (present but disarmed: counts unbumped, diversity all-false — SPEC §6.2), and the counted shape with a real `mutual_agreement` is demonstrated by [`examples/pairing-artifacts/`](../examples/pairing-artifacts/README.md) instead. |
| **No tuned anything.** | Random and greedy, public-knowledge and shallow. `guards/purity.py` holds `policies/` to an import surface with no file reads and no weights formats, so a brain here physically cannot load a trained model. |
| **No counted mode.** | `RunMode.SPARRING` is the only value that exists. A mode whose preflight demanded a deliverable would make this host refuse itself at startup, so the modes that would demand one are not in the code. |

**Point your own mail at yourselves or at nothing while practising — never at the lecturer.**
See [`../docs/WARNINGS.md`](../docs/WARNINGS.md) §3.

## Commands

```
python -m sparring.cli selfplay                    # zero dependencies
python -m sparring.cli serve  --peer <url>         # a real peer over MCP — --peer is what makes
                                                   #   it PLAY; without it, tools answer and
                                                   #   nothing else happens (the banner says so)
python -m sparring.cli doctor --peer <url>         # classify their edge before you agree a T
python -m sparring.cli replay <dir>                # Verified OK / TAMPERED
```

Exit codes are distinct so a script can tell failures apart: `0` clean · `2` usage · `3` preflight
refused · `4` handshake refused · `5` port already held · `6` a sub-game ended in a technical loss
or tamper forfeit · `7` no opponent arrived.

Useful flags: `--policy {greedy,random}` · `--scent-model {subtractive_chebyshev_v1,multiplicative_book_v1}`
· `--seed` · `--lie-rate` · `--hint-lang {en,he,mixed}` · `--reorder-window` · `--turn-timeout`.

## Two honest notes

**Greedy vs greedy always draws.** Both agents move one cell per turn, so a pursuer cannot close
distance on an evader that keeps moving away; the cop only wins by cornering, and the greedy thief
weights its moves to keep exits open. That is a real property of the game rather than a bug, and it
is worth knowing before you tune anything. Use `--policy random` if you want to see captures, or
just play your own brain against it — which is the point.

**This is a third independent implementation of the game layer, not of the crypto.** The rules,
engine, state machine, wire, receiver contract and artifacts are written from `SPEC.md` and the
book. The byte-level constructions are imported from the kit's own `verify_vectors.py` — the same
functions the fixtures are generated from — so the peer cannot drift from the published vectors,
and equally **cannot catch a bug inside them**. Playing a real team remains the true test.

## How it is checked

Everything except the HTTP surface runs with **nothing installed**:

```
python -m sparring.guards.no_mail        # the mail surface is absent
python -m sparring.guards.purity         # one hash seam, one clock, no tuned weights
python -m unittest discover -s sparring/tests -t .
```

The suite includes a seeded six-sub-game series over an in-process transport, and **the same
series again over a transport that duplicates, reorders and drops-then-retries messages** — with
the outcome ledger required to come out byte-identical. That is the §7.1 receiver contract proven
at the level that matters: not "we handled a duplicate" but "the duplicates changed nothing about
who won".
