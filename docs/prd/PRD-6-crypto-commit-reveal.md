# PRD-6 — Security and Cryptography (אבטחה וקריפטוגרפיה)

**Stage 6 of 7** · Rulebook Ch. 5 · Repo: **THIEF**
Prev: [PRD-5](PRD-5-tunneling.md) · Next: [PRD-7 — Reporting & Visualization](PRD-7-reporting-and-gui.md)

## 1. Objective

Wrap the already-working remote communication in **Commit-Reveal over SHA-256**,
write the nonce generator, and add the **Step-0** hardware declarations. Order
matters: encryption sits on top of transport that has already proven itself
operationally, so a failure can never be ambiguous between "network problem" and
"crypto problem".

## 2. Scope

**In:** commitment construction, canonical serialisation, nonce generation,
acknowledge/reveal/audit phases, tamper handling, truthful capture obligation,
Step-0 declaration and signing, commit-hash reporting, log integrity.
**Out:** the replay *viewer* UI (PRD-7) — the verification *engine* is here.

## 3. Why this exists

In a P2P network with no objective game master, three frauds threaten the race:
**time travel** (altering a move already made), **changing a move after seeing the
opponent's**, and **denying a previous position or statement**. As long as each
side is both player and record-keeper of its own protocol, nothing prevents
rewriting history in its own favour. The answer is not legal but mathematical:
commit to a decision while it is still sealed, and reveal only after the opponent
has locked in theirs.

## 4. Functional requirements

### 4.1 Phase 1 — Commit
- FR-6.1 The agent picks its physical move and the hint it will send (including
  the `Intent` flag: is the hint true or false), and draws a fresh **Nonce**.
- FR-6.2 The commitment is

  ```
  H_commit = SHA256( State ‖ Move ‖ Intent ‖ Nonce )
  ```
  where `‖` is byte concatenation — **not** numeric addition.
- FR-6.3 Concatenation is implemented as **canonical JSON**: `sort_keys=True`,
  `separators=(",", ":")`, UTF-8 encoded, so both peers hash byte-identical input.
- FR-6.4 The sealed record is **richer than the four core fields** — it also
  includes the verbal hint, the intent classification, the step number, the role,
  and the sub-game id.
- FR-6.5 Field semantics:
  - `State` — the board snapshot the move is based on; prevents reusing an old
    commitment in a new context.
  - `Move` — the physical action; the core we are locking against change.
  - `Intent` — `truth` / `lie`, forcing an advance declaration of sincerity.
  - `Nonce` — cryptographic randomness; guarantees hash uniqueness and defeats a
    **dictionary attack**. Without it, the tiny move space would let an opponent
    pre-hash every plausible option and crack any commitment in a fraction of a
    second.
- FR-6.6 Nonces are generated with `secrets.token_hex(16)` — **never** the
  `random` module.
- FR-6.7 Only `H_commit` crosses the wire at this phase. **Never the content.**

### 4.2 Phases 2–4
- FR-6.8 **Acknowledge** — the opponent confirms receipt and that it is locked on
  our commitment. This prevents the sender from retreating, while ensuring the
  reveal happens only after both sides have fixed their moves.
- FR-6.9 **Reveal** — send `Move` and the verbal sentence. **The nonce stays
  hidden** at this phase, to prevent premature reverse-engineering of signatures.
- FR-6.10 **Final Reveal / Audit** — only at the end of the whole match are all
  nonce values disclosed, for full mutual audit.

### 4.3 Verification and sanction
- FR-6.11 Each side recomputes the opponent's hashes from the revealed
  `State`/`Move`/`Intent`/`Nonce` and compares against the declared commitment.
  Use `secrets.compare_digest` for the comparison.
- FR-6.12 **Any mismatch is unambiguous proof of tampering.** There is no room for
  interpretation or statistical doubt: SHA-256 is sensitive to every single bit.
  The cheating team takes a **heavy technical loss — total loss of the match**,
  independent of the board result. Cryptography, not human judgement, decides.
- FR-6.13 The move log is written append-only with each step's commit, reveal and
  (at the end) nonce, in the format of `log_<game_id>_g<NN>.json`, so the Replay
  App (PRD-7) can verify it step by step.

### 4.4 Truthful capture obligation (thief-critical)
- FR-6.14 When the cop issues a **Capture Claim**, the thief is under a
  **cryptographic obligation to answer truthfully**. A capture claim is not a
  matter of trust between rivals but a claim verifiable after the fact.
- FR-6.15 Every answer is signed and logged. **Any attempt to deny a real state is
  necessarily exposed at the log-audit stage and triggers total systemic
  disqualification** (Appendix E rules 21–22). This is the single highest-risk
  code path in the thief agent: it must be correct, and it must be honest by
  construction — the honest answer is computed directly from `BoardState`, with no
  branch that can produce a different one.

### 4.5 Step-0 and computational fairness
- FR-6.16 Before the first move, each side collects and publishes its machine
  specification: **OS, CPU cores and frequency, RAM, GPU/VRAM, and the name of the
  language model in use**.
- FR-6.17 The declaration also records the **code version**, the **team name**, the
  **sub-game number**, and — mandatory — the **GitHub commit hash** the code is
  running at for this match.
- FR-6.18 Code may be changed, updated and improved between matches, **but every
  match must record the exact commit hash played**, so the grader can reproduce the
  precise version that competed. The same hash appears in the final email JSON as
  `github_commit`.
- FR-6.19 The whole specification is packed into a JSON string and **signed
  cryptographically with a pre-supplied key** so it cannot be forged retroactively.
- FR-6.20 All LLM **token consumption** is metered and cryptographically locked as
  well, to prevent denial of the compute resources actually used. Totals are
  reported in the final JSON (per sub-game and per series).
- FR-6.21 The lecturer applies a **normalisation formula** granting bonuses to
  algorithmically efficient solutions — good results at minimal resource cost.
  A lean, fast agent on a modest machine beating a heavy rival is a win of
  engineering over brute force. This is a direct incentive to keep the
  `template` / `ollama` bluff providers and a tight move policy.

### 4.6 Zero-knowledge framing
- FR-6.22 Commit-Reveal embodies the spirit of a **zero-knowledge proof**: each
  agent proves it has chosen and fixed a legal move without revealing what it is.
  At commit time the opponent has total certainty that a locked decision exists —
  and zero knowledge of its content. Only at reveal is the content exposed, and
  even then it is verifiable against the original commitment. Commitment is thus
  separated from disclosure.

## 5. Reference sketch

```python
import hashlib, json, secrets

def commit(state: str, move: str, intent: str) -> tuple[str, str]:
    nonce = secrets.token_hex(16)                     # defeats dictionary attacks
    payload = json.dumps(
        {"state": state, "move": move, "intent": intent, "nonce": nonce},
        sort_keys=True, separators=(",", ":"))        # CANONICAL JSON
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), nonce

def verify(state, move, intent, nonce, h_commit) -> bool:
    payload = json.dumps(
        {"state": state, "move": move, "intent": intent, "nonce": nonce},
        sort_keys=True, separators=(",", ":"))
    recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return secrets.compare_digest(recomputed, h_commit)
```

> The sketch shows the core; the record actually sealed in this project covers the
> full step — state, move, intent, nonce, hint, verdict, step index, role and
> sub-game.

## 6. Acceptance criteria (milestone gate)

- [ ] A move is committed, then revealed, with a valid nonce; the opponent's
      verification passes.
- [ ] A deliberately corrupted reveal is detected and produces `TECHNICAL_LOSS`.
- [ ] Nonces are never transmitted before the final audit (protocol test).
- [ ] Both peers hash byte-identical payloads (cross-implementation fixture test).
- [ ] `Step-0` verifies hardware, code version and commit hash on both sides.
- [ ] A truthful capture answer is produced from board state with no path that can
      return a false one (unit + property test).
- [ ] Full end-of-match audit completes with no tampering detected.
- [ ] Token totals are metered and locked.

## 7. Out of scope / deferred

Replay viewer UI and `Verified OK` / `TAMPERED` banners (PRD-7) · Gmail delivery
of the signed report (PRD-7).
