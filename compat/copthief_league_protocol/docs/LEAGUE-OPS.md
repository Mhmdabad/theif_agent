# League ops — how a scheduled window actually runs

Two conformant implementations that both pass every vector still have to *meet*. This page is
about that half: agreeing a start time, proving the network before it, and the failure modes that
burn a window and look like something else. For the layer above single windows — the lifecycle of
a whole pairing, from first contact through the counted series — see
[`PAIRING-PLAYBOOK.md`](PAIRING-PLAYBOOK.md).

It is written from a real series that took **seven scheduled windows** to complete — six burned,
one played. Every failure was a launch-time default. Every abort was clean and before any report
went out, which is the only reason it cost nothing but evenings. The ledger is at the bottom.

Sides are unattributed. Which team hit which default is not the lesson; the defaults are.

---

## 1. The T-protocol

Coordinating two teams over chat, in real time, does not converge. Naming a minute does.

1. **Name a T** — a wall-clock minute, with the timezone written out.
2. **Both sides launch at T**, without waiting for confirmation from the other.
3. **At T+30s, both sides probe every hostname in play.**
4. **If an edge is not ready, kill everything and name a new T.** Do not debug into the window; a
   half-started window produces stale state that costs the *next* one too.

That is the whole protocol, and it fixed days of half-windows on the first attempt.
*(Direction proposed by **anrbj666** — Alon Engel, Renat Karimov.)*

**Automate the trigger, not the decision.** A sentry that polls the opponent's edge and fires your
launcher when it turns ready removes the human from the loop without removing the agreement.

**What to check before you name a T** — each of these burned a window on its own:

- The **wire shape** each side will actually launch with. A committed default that differs from
  what you agreed will greet your opponent in the wrong shape, and it will be refused.
- The **run config** each side will load — specifically, which scent model it declares. Two peers
  that agree in chat and disagree in `config` refuse each other at the handshake.
- **Recipients and mail mode on both sides**, if the run is meant to produce reports at all. See
  [WARNINGS §3](WARNINGS.md#3-make-the-lecturers-address-unreachable-not-merely-unconfigured).
- **A fresh artifact from each side** to diff schemas against, if you have never settled together.

---

## 2. Netcheck discipline

### The status codes mean different things

| Code | State | What to do |
|---|---|---|
| `406` | An MCP streamable-HTTP peer **is listening** and correctly refused a browser-shaped GET | This is the ready state. Poll for **this**, not for `200`. |
| `502` | The edge is up; **nothing is behind it** | Either the peer has not started, or the tunnel has no ingress — indistinguishable from outside. |
| `421` | The server's DNS-rebinding guard rejected the `Host` header | Fix at the tunnel: Cloudflare → `originRequest.httpHostHeader: 127.0.0.1:<port>`; ngrok → `--host-header=rewrite`. No code change. (SPEC App. D.) |
| `530` | The edge does not know this hostname | DNS record or tunnel route missing. |
| refused | Nothing accepted a connection | The tunnel process is not running, or the URL is wrong. |

**Poll for the ready state; do not sleep and hope.** "I waited two minutes, it should be up" is how
a window becomes a mystery.

```
python tools/netcheck.py https://peer.example/mcp --expect 406
python tools/netcheck.py https://peer.example/mcp --tool-call
```

`--tool-call` is the probe worth running before a first-ever meeting: *does your public URL answer
a tool call?* It catches the `421` trap in seconds, which a status probe alone leaves you guessing
about.

### A bare `502` check cannot prove your own path

This is the single most expensive thing on this page.

A tunnel connector launched with **mangled arguments and no ingress rules at all** answers `502`
forever — which is exactly what a healthy tunnel with a not-yet-started peer looks like. So
watching your own edge for `502` cannot distinguish *"my peer hasn't started"* from *"my tunnel is
broken and no peer will ever be reachable through it"*. One of those resolves itself in thirty
seconds; the other burns the window.

**The only proof is a loopback through your own edge:**

```
python tools/netcheck.py --loopback 8931 https://cop.example.com https://thief.example.com
```

Bind a throwaway listener on the series port, fetch your **own** public hostname, and demand your
listener's own answer back. That exercises tunnel, ingress rules and host-header rewrite in one
shot. The tool sends a nonce and requires it back, so another process answering on that port cannot
be mistaken for success — and it refuses to start at all if something already holds the port.

*(A config path containing spaces must travel as one quoted argument. An unquoted one is how a
connector ends up running with no ingress in the first place.)*

---

## 3. All your gates must finish **before** T

Every local check you run — including the loopback listener above — answers HTTP on the series
path. A lax opponent transport can read **any** HTTP response as a delivery acknowledgement and
negotiate off a phantom. Between your last gate and your real peer binding, nothing of yours may
answer on that path.

So: run the gates early, free the port, then wait for T. If you are scripting it, make the gates a
phase that completes before the sleep-until-T, not one that races it.

---

## 4. Two series topologies exist, and both are legitimate

- **One process, one address, all six sub-games.** What the reference does.
- **Role-split services**, each owning the sub-games of its own role — so the address you must dial
  *changes with their role each game*.

A driver that dials one URL for the whole series is **wrong half the time** against a role-split
opponent, and a peer that dials the wrong service burns its entire connect budget before failing.

**Refuse loudly rather than guess.** Accept either one opponent address for the series or a
role-split pair — never both, and never a default when the pair is ambiguous. Guessing which was
meant loses a series; refusing costs a message in chat.

**This changes the T-protocol.** Under per-window binding, only the **first** counterpart can be
required to be ready at T — their other role's service legitimately binds only when its own window
opens. So: hard-require the first counterpart, treat the rest as informational, and let each
window's own handshake budget judge its own edge. A rule demanding all edges ready at T cannot hold
against a conformant role-split opponent, and will burn windows that were fine.

---

## 5. Patience math — the budgets must be reconciled, not merely set

A real kill-drill lost a game to two timeouts that had never been related to each other anywhere:
a signed `watchdog_timeout_sec` and a private per-turn budget. At runtime the wrong one won and the
peer self-terminated while perfectly healthy.

State the relationships once, and **check them at config load** so a tree that would kill you
refuses to start rather than losing a counted game:

1. **An armed watchdog needs a budget.** `watchdog > 0`, or it is not armed.
2. **The poll interval must be shorter than the watchdog.** An idle loop beats once per poll, so a
   poll that can outlast the watchdog self-terminates a healthy waiting peer.
3. **An outbound give-up must not outlast your own turn budget.** Otherwise the transport abandons
   a peer your deadline still considers in-budget.
4. **The stall timeout must exceed the turn deadline.** Whatever a stalled transport does, *your own*
   turn deadline must expire first — so a silent opponent is classified by rule (a technical loss,
   App. E) and never by suicide.
5. **The reorder window must be at least 1.** A receiver with no window turns an ordinary
   at-least-once retry into a protocol violation — see SPEC §7.1. Zero tolerance is not a
   tightening; it is a self-inflicted technical loss that takes the opponent's points with it.

Report **every** violation at once when you refuse. A config is fixed in one pass or not at all.

**One clock per expected message.** A redelivered or early push proves the opponent is alive but
does not discharge what it owes you, so it renews nothing — and the deadline must be evaluated on
laps where a message *did* arrive, or a flood keeps you in the loop past your own budget. Pinned as
a decision table in `vectors/delivery_contract.json`.

---

## 6. Handshake hazards

**Bystander greetings.** On a role-split wire, the opponent's *other* window can push at your port
carrying identical signed terms — it fails only the pairing check, because it belongs to a
different game. Refuse it **on the record** and keep waiting for your real counterpart, bounded by
the turn budget. Terms drift and bad signatures should still raise on the first offence; a
bystander should not. See SPEC §7.2.

**Absence is a different diagnosis from disagreement.** Say which:

- *terms **absent*** — a greeting carrying no `terms` at all is a differently-shaped wire arriving
  under a reference wire. That is a wire-shape fault on the **sender's** side.
- *terms **differing*** — both sides speak the same wire and their constitutions disagree.

They have completely different fixes, and naming them apart saves the hours it costs to work out
the difference the first time.

**The cost of a failed handshake compounds.** A failed handshake ends in about 60 seconds while a
real sub-game takes minutes, so the side that failed runs **ahead** and never resynchronises.
Observed: one side on sub-game 4 while the other was still on sub-game 2 — two teams describing
different series, which is the shape App. E rule 35 zeroes for both.

---

## 7. Between attempts

See [WARNINGS §5](WARNINGS.md#5-stale-state-does-not-announce-itself). In short: archive the
previous attempt's logs (never delete), check for orphaned peers holding the port, and remember that
a burned attempt and the real series share a **deterministic** `game_uid` — so they name the same
files.

---

## The seven-window ledger

One evening, one pairing, one six-sub-game series. Sides unattributed.

| # | Verdict | Root cause |
|---|---|---|
| 1 | burned | One side's thief-role service never bound — a sequential orchestrator binds one role at a time. |
| 2 | burned | A tunnel launched with an unquoted spaced config path → connector with no ingress → `502` forever, indistinguishable from healthy-idle. |
| 3 | burned | A parallel-runner switch dropped the wire-shape flag; the committed default greeted the opponent in the wrong shape and was refused. |
| 4 | burned | A run config still declared the previous scent model; the pair lock was the other one → refused at the handshake, before any game. |
| 5 | burned (+ cascade) | One side's window resumed a dead window's stored context off transport acks and went silent; the handshake-patience math cascaded. **Two sub-games did settle** — the first real cross-team automated games. |
| 6 | burned | Protocol conflict: a new per-window binding topology met a "all four edges must be `406` at T" rule that could not hold. Rule retired (§4). |
| 7 | **played** | Six sub-games, one wire `game_uid`, mutual audits clean both ways, one report per side. |

**What came out of it**, all verified live in window 7:

1. Quoted tunnel launch **plus** an end-to-end loopback gate — a bare `502` check cannot
   distinguish a healthy-idle tunnel from a connector with no ingress (§2).
2. All local gates complete **before** T, so nothing but a real peer ever answers on the series
   path — a lax opponent transport had read a gate listener's HTTP responses as delivery acks (§3).
3. Stale same-`game_id` logs archived at launch — the logger appends, and a burned attempt must
   never pollute a later aggregation (§7).
4. Refusal wording that distinguishes terms-absent from terms-differing, so a window-3-class fault
   diagnoses itself from the refusal line alone (§6).

Nothing here is clever. All four are the kind of thing you only write down after it has cost you
an evening — which is why they are written down.
