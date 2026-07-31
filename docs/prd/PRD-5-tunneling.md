# PRD-5 — Cloud Exposure and Tunneling (חשיפה לענן ומנהור)

**Stage 5 of 7** · Rulebook Ch. 2 · Repo: **THIEF**
Prev: [PRD-4](PRD-4-language-and-scent.md) · Next: [PRD-6 — Cryptography](PRD-6-crypto-commit-reveal.md)

## 1. Objective

Move from `localhost` to **public addresses** and connect agents running on
remote machines. From this point the system stops being a simulation on one box
and becomes a genuinely distributed system — with all the latency and
disconnection problems that entails.

## 2. Scope

**In:** tunnel setup (ngrok / Localtonet), NAT traversal, public-URL exchange,
remote-play hardening, tunnel-failure handling.
**Out:** cryptography (PRD-6), reporting/GUI (PRD-7).

## 3. Functional requirements

### 3.1 Public exposure is mandatory
- FR-5.1 Running the FastMCP server on `localhost` is permitted **only during
  early coding**. For league play each team **must** expose its server to the
  public internet through a tunneling tool such as **ngrok** or **Localtonet**
  (Appendix E rule 10).
- FR-5.2 Most machines sit behind a firewall and NAT and are therefore not
  directly reachable. The tunnel creates a public URL that performs **NAT
  traversal**, so the opponent — anywhere in the world — can reach our server.
- FR-5.3 The server must already bind `0.0.0.0` (PRD-2 FR-2.2); no code change
  should be required to go public.

### 3.2 Address exchange
- FR-5.4 The public URL is exchanged during the pre-match handshake and recorded
  in the pre-game declaration file (`declaration_<game_id>.json`) together with
  both teams' MCP server addresses.
- FR-5.5 `opponent_url` in `config/thief/game.toml` switches from
  `http://127.0.0.1:<port>/mcp` to the opponent's public tunnel URL. **This is the
  only thing we know about the opponent.**
- FR-5.6 Tunnel URLs are ephemeral on free tiers; the runtime must tolerate a URL
  change between sub-games (re-handshake) without a restart of the whole series.

### 3.3 Resilience over a real network
- FR-5.7 **Tunnel robustness is part of game robustness.** If one tunnel drops,
  the opposite side loses the ability to verify moves and would deadlock on turn
  scheduling. The Deadline Tracker (PRD-2 FR-2.13) must convert that into a
  controlled retry and, ultimately, a clean `TECHNICAL_LOSS` — never an infinite
  wait.
- FR-5.8 Latency budget: `response_timeout_sec` (default 30 s, negotiable) must
  accommodate real internet round-trips plus the opponent's LLM think time. Raise
  it by mutual agreement rather than lowering it silently.
- FR-5.9 Retry policy: `max_retries` = 3 with `retry_backoff_sec` = 5, applied to
  transport failures only — **never** to re-send a different move after a commit.
- FR-5.10 Concurrency is bounded (`concurrent_requests` = 2) so a burst of retries
  cannot stampede the opponent's server.
- FR-5.11 Log every transport-level event (connect, timeout, retry, reconnect)
  with timestamps; these logs are the evidence when a match ends in a technical
  result.

### 3.4 Separation still holds
- FR-5.12 Going public does not relax PRD-2 FR-2.4/2.5. During league play the two
  teams are on different machines and separation is inherent; the discipline
  matters most during **local development**, when one team builds both the cop and
  the thief on a single machine and accidental overlap (shared memory or
  variables) is a real risk that would produce behaviour never reproducible in the
  league.

## 4. Acceptance criteria (milestone gate)

- [ ] An agent on a **remote machine** connects via ngrok/Localtonet and plays a
      **full round** against the local agent.
- [ ] Public URL appears in the declaration file and in the handshake log.
- [ ] Killing the tunnel mid-match produces a controlled technical result within
      the deadline budget — no hang, no silent crash.
- [ ] Tunnel restart with a new URL is recovered by re-handshake between sub-games.
- [ ] Round-trip latency measured and recorded; timeout values justified against it.

## 5. Out of scope / deferred

Commit-Reveal and Step-0 hardware declarations (PRD-6) · Gmail reporting, GUI and
Replay App (PRD-7).
