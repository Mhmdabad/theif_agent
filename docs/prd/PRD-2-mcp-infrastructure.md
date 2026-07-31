# PRD-2 — Basic FastMCP Infrastructure (תשתית FastMCP בסיסית)

**Stage 2 of 7** · Rulebook Ch. 2 · Repo: **THIEF**
Prev: [PRD-1](PRD-1-base-logic.md) · Next: [PRD-3 — Blind Strategy](PRD-3-blind-strategy.md)

## 1. Objective

Split the two agents into **separate processes** and prove the pipe works: a
message leaving agent A arrives, intact and correctly parsed, at agent B. Agents
still speak in pure numeric coordinates — no language, no scent, no crypto. The
only goal of this stage is *transport confidence* before we load the pipe with
complex content.

## 2. Scope

**In:** FastMCP server per agent, MCP tools, client engine, turn scheduling,
Orchestrator skeleton, game-phase state machine, Deadline Tracker, Watchdog,
process/config separation.
**Out:** public URLs (PRD-5), natural language and scent (PRD-4), Commit-Reveal
(PRD-6), GUI/email (PRD-7).

## 3. Functional requirements

### 3.1 Symmetric peer
- FR-2.1 Each agent is **simultaneously an MCP server** (exposing `@mcp.tool`
  endpoints) **and an MCP client** (calling the opponent's tools). There is no
  strong side and no weak side.
- FR-2.2 Server binds `host="0.0.0.0"` on `my_port` with HTTP transport so a
  tunnel can later expose it unchanged.
- FR-2.3 The only thing we know about the opponent is `opponent_url`.

### 3.2 Mandatory separation (Appendix E rules 1–2)
- FR-2.4 Cop code and thief code run in **two completely separate processes**,
  under **separate config directories** (`config/thief/` here vs `config/police/`
  in the cop repo).
- FR-2.5 **Absolutely forbidden:** shared memory, importing a common module that
  holds live state, or reading shared variables across the two sides. Such sharing
  hands one side its opponent's local truth, breaks the Zero-Trust model, and
  **disqualifies the solution even if the game works technically.**
- FR-2.6 This separation is also why submission is two repositories.

### 3.3 Tools exposed by this peer
Minimum viable surface for stage 2 (extended in later stages):

| Tool | Purpose |
|---|---|
| `handshake(peer_info)` | Exchange identity, roles, protocol/config version |
| `negotiate_config(config_json, config_sha256)` | Agree the shared constitution; refuse on hash mismatch |
| `receive_move(payload, signature)` | Accept an opponent action (stage 2: plain coordinates) |
| `get_state_digest()` | Return our view digest for cross-checking |
| `ping()` | Liveness / latency probe for the Deadline Tracker |

- FR-2.7 Every tool validates its input and **never trusts an unverified move**.
  A malformed or illegal payload is rejected with a structured error, never by
  crashing.

### 3.4 Orchestrator (Appendix E rule 3)
- FR-2.8 A single `Orchestrator` acts as the **only gateway** to all subsystems:
  MCP Connector, Decision Module, Log Manager, Deadline Tracker, Watchdog.
- FR-2.9 Peripheral modules **never reference each other** — only the
  Orchestrator. Replacing the decision engine must touch exactly one module.
- FR-2.10 The Orchestrator coordinates; it contains **no** decision logic and no
  low-level transport code.

### 3.5 State machine (Appendix E rules 4–5)
- FR-2.11 Legal transitions only:

  ```python
  TRANSITIONS = {
      "WAITING_FOR_OPPONENT": {"COMPUTING_MOVE"},
      "COMPUTING_MOVE":       {"COMMITTING", "TECHNICAL_LOSS"},
      "COMMITTING":           {"AWAITING_REVEAL"},
      "AWAITING_REVEAL":      {"VERIFYING", "TECHNICAL_LOSS"},
      "VERIFYING":            {"WAITING_FOR_OPPONENT"},
      "TECHNICAL_LOSS":       set(),   # terminal
  }
  ```
- FR-2.12 An illegal transition raises **immediately** rather than leaving the
  system undefined — turning a logic bug into a visible development-time error
  instead of a silent in-match deadlock.

### 3.6 Reliability patterns (Appendix E rules 6–7)
- FR-2.13 **Deadline Tracker** — every outgoing MCP request carries a timestamp
  and an expiry (`response_timeout_sec`, default 30 s). A missed deadline is a
  **failure**, not a reason to keep waiting: perform a controlled retry
  (`max_retries` = 3, `retry_backoff_sec` = 5) or declare technical loss and close
  the turn cleanly.
- FR-2.14 **Watchdog** — an independent background process monitors the main loop
  heartbeat. If no heartbeat for `watchdog_timeout_sec` (default 60 s), persist
  state and perform a controlled shutdown so the match can be recovered instead of
  lost entirely.

### 3.7 Turn scheduling
- FR-2.15 Strict alternation; acting out of turn is impossible by construction
  (the state machine plus the turn banner lock in PRD-7).
- FR-2.16 A full turn = cop move + thief move. Scent decay (PRD-4) fires at the
  end of a full turn.

## 4. Reference sketch

```python
from fastmcp import FastMCP

mcp = FastMCP("police_thief_peer")          # each agent runs its own instance

@mcp.tool
def receive_move(signed_move: str, signature: str) -> dict:
    """Expose an action to the opponent over the network."""
    is_valid = verify_signature(signed_move, signature)
    return {"accepted": is_valid, "move": signed_move if is_valid else None}

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8802)
```

## 5. Recommended (not required) complements

MCP is the **required** protocol for tool/data connectivity and may not be
replaced. Alongside it, the book strongly recommends knowing:
- **A2A** (Agent-to-Agent, Google) — structured task lifecycle states
  (submitted / working / completed) for inter-agent task hand-off.
- **ACP** (Agent Communication Protocol) — zero-trust federated communication, for
  advanced teams.

## 6. Acceptance criteria (milestone gate)

- [ ] A geometric message leaving agent A over localhost is **received and parsed
      correctly** by agent B.
- [ ] Cop and thief run as two separate OS processes with separate config dirs;
      no shared state whatsoever.
- [ ] Every inter-module call goes through the Orchestrator.
- [ ] An illegal state transition raises and is covered by a test.
- [ ] Killing the opponent process mid-turn produces a controlled
      `TECHNICAL_LOSS` — not an infinite wait.
- [ ] Watchdog fires on a simulated freeze and persists state.

## 7. Out of scope / deferred

Public exposure and NAT traversal (PRD-5) · natural language and scent (PRD-4) ·
signature semantics beyond a stub (PRD-6) · GUI, replay, email (PRD-7).
