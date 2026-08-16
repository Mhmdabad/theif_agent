# Start here — from "found this repo" to "ready to play", without asking us anything

Four gates. Each one is a command, each has a pass criterion you can check yourself, and each
fails in a way that names what is wrong. Work through them in order; if all four pass, the
remaining ways to lose a game against us are operational rather than protocol, and
[`LEAGUE-OPS.md`](LEAGUE-OPS.md) covers those.

Nothing here needs an account, an install, or a conversation with us.

```
git clone https://github.com/Imreec/copthief-league-protocol
cd copthief-league-protocol
```

Python 3.12+. **No dependencies** for gates 1, 3 and 4. Gate 2 needs one package, and only if you
want to play the peer over a network rather than watch it play itself.

---

## Gate 1 — your bytes

```bash
python verify_vectors.py
```

**Pass:** the last line reads `ALL VECTORS PASS`, and the exit code is `0`.

This proves *our* reference constructions reproduce the published fixtures on *your* Python. It is
the floor, not the finish line — the point is the next sentence.

**Now port the checks into your own suite and point them at `vectors/*.json`.** That is what
actually certifies you: when your implementation reproduces every `[CORE]` fixture, your hashes are
byte-compatible with every other conformant team, your agreement signature will verify, both sides
will derive the same `game_uid`, and the post-game audit of your revealed log will pass instead of
raising a false `tamper_forfeit`.

**If it fails**, the failing line names the fixture and the case, and prints what your code
produced. Compare the *canonical strings*, not the hashes — see
[`CONTRIBUTING.md`](../CONTRIBUTING.md). The two things that catch almost everyone are
`ensure_ascii=False` and float `repr`.

---

## Gate 2 — your rules, against a real opponent

```bash
python -m sparring.cli selfplay
```

**Pass:** six sub-games settle, every mutual audit reports clean, and 14 artifacts are written
under `runs/`. Exit code `0`.

That command runs a full series with **no dependencies at all** — it is the sparring peer playing
itself, so you can read exactly what a conformant series looks like before you build one.

To play it with *your* implementation — note that **both sides dial each other** (MCP pushes one
way per session, so a served peer with no `--peer` answers tools and plays nothing):

```bash
pip install -r sparring/requirements.txt
python -m sparring.cli serve --port 8931 --peer http://localhost:<your-port>/mcp --role thief
# and point your peer at http://localhost:8931/mcp
```

It will refuse you for the same reasons a real team would, and say which — a greeting with no
`terms` is diagnosed differently from terms that disagree, because those are faults on different
sides. See [`sparring/README.md`](../sparring/README.md).

**It speaks Hebrew and an emoji on the wire on purpose.** A serializer that escapes non-ASCII
produces hints your opponent cannot re-hash, the audit reads that as tampering, and **both** teams
score zero. A rehearsal that never leaves ASCII would let you find that out at a real opponent's
audit instead. [`EVIDENCE.md`](EVIDENCE.md) shows both hazards with their hashes, so you can check
your serializer against them directly.

---

## Gate 3 — your artifacts

```bash
python tools/check_artifacts.py <directory holding your four artifacts>
```

**Pass:** `ALL ARTIFACT CHECKS PASS`, exit `0`.

It checks the filename grammar, that **one `game_uid`** spans all four files, that `game_id` is the
sorted pair, that required keys are present, and that declared totals equal the sum of the
sub-game scores.

**This is the gate that protects your opponent, not just you.** Under App. E rule 35, two counted
reports naming one match by two different `game_uid`s score **0 for both teams**.

Pass `--terms <your flat signed terms>.json` and it also **re-derives** the uid rather than just
checking it is consistent. That matters more than it sounds: in a real cross-team series one side
derived its uid from its whole config instead of the flat negotiated terms, so the uid was
perfectly deterministic, identical across all four of its artifacts, and joined them correctly —
only the cross-team join failed, while every game *value* in the two reports agreed. Consistency
checks cannot see that; re-derivation can. Read [`WARNINGS.md`](WARNINGS.md) §2 before you settle
anything.

Try it on the sparring peer's own output first, so you can see it pass:

```bash
python tools/check_artifacts.py runs/sparring_*
```

**Give it two directories — yours and your opponent's — and it also checks the join between
them:**

```bash
python tools/check_artifacts.py <your dir> <their dir>
```

That is the check neither team can run alone, because each side's bundle is internally perfect.
Run it before either of you reports.

---

## Gate 4 — your network

```bash
python tools/netcheck.py https://your-peer.example/mcp --expect 406
python tools/netcheck.py --loopback 8931 https://your-public-hostname
```

**Pass:** the first prints `PEER LISTENING`; the second prints that your own nonce came back
through the edge. Both exit `0`.

The second command is the one teams skip and regret. A tunnel connector launched with mangled
arguments and **no ingress at all** answers `502` forever — which is exactly what a healthy tunnel
with a not-yet-started peer looks like from outside. So watching for `502` cannot tell *"wait
thirty seconds"* from *"this window is already lost"*. The loopback binds a throwaway listener,
fetches your own public hostname, and demands your listener's own answer back.

Run it before you agree a start time, not during one.

---

## Then, before you contact anyone

1. **Read [`WARNINGS.md`](WARNINGS.md).** It leads with the failures that cost the *opponent's*
   points too — a series that did not fully settle must send **nothing**; the report's `game_uid`
   must be the one the handshake derived; the lecturer's address should be structurally unreachable
   outside a counted run rather than merely unconfigured.
2. **Read [`LEAGUE-OPS.md`](LEAGUE-OPS.md).** The T-protocol, what `406` / `502` / `421` each mean,
   why every local gate must *finish* before the start time, the two legitimate series topologies,
   and the five timing-budget rules that should refuse to load rather than kill you mid-game.
3. **Know what is actually agreed.** [`GOVERNANCE.md`](GOVERNANCE.md) says which constructions two
   independent implementations have reproduced and which have only one behind them. Do not assume
   an opponent implements a `PROPOSED` one.
4. **When you are ready to actually approach a team**, follow
   [`PAIRING-PLAYBOOK.md`](PAIRING-PLAYBOOK.md) — the message that opens a pairing, the role
   convention, the friendly campaign that de-risks the counted series, and the retry agreement you
   want in writing before anything counts.

---

## The vocabulary this repo assumes

| Term | What it means here |
|---|---|
| **the book** | *Distributed Cops-and-Robbers over a Peer-to-Peer Network*, Dr. Yoram Reuven Segal, v3.0.0. The sole source of truth. This kit is not the spec — the book is. |
| **the reference** | The book's own implementation, [`rmisegal/Game-P2P-Cop-Chase`](https://github.com/rmisegal/Game-P2P-Cop-Chase). Where the kit pins a form, it is usually this one. |
| **sub-game / series** | A series against one opponent is six sub-games, with roles alternating. |
| **commit-reveal** | You send a hash of your sealed move; the nonce stays secret until the end-of-game audit. |
| **the audit** | At the end of a sub-game each side reveals every record and nonce, and the **opponent** re-hashes them with its own serializer. |
| **`tamper_forfeit`** | What a failed audit produces. It is not a penalty on the guilty side; a serialization mismatch between two *honest* peers ends the game for both. |
| **technical loss** | A crash, a timeout, an illegal move. Scores **0 for both sides**, deliberately. |
| **counted vs warm-up** | Only the first meeting with an opponent counts (App. E rule 52). Uncounted warm-ups are explicitly permitted — the book even recommends them (ch. 9.2.1) — and are what the sparring peer is for. |
| **friendly** | The league's word for a warm-up against a real team, played as if it counted: same six sub-games, same locked stack, same auto-fired report — only the counting and the lecturer's inbox differ. [`PAIRING-PLAYBOOK.md`](PAIRING-PLAYBOOK.md) Stage 4. |
| **the four artifacts** | `declaration_<game_id>.json`, `config_<game_id>_g<NN>.json`, `log_<game_id>_g<NN>.json`, `result_<game_id>.json` — all sharing one `game_uid`. |

---

## If something here is wrong

Open an issue — [`CONTRIBUTING.md`](../CONTRIBUTING.md) has the four kinds and what to include.
The most valuable one you can file is a conformance failure with **your canonical string in it**:
either your serializer diverges and you have found it before match day, or *our fixture is wrong*
and you have found something that would have cost two teams a match.
