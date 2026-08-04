# Latency, and why `response_timeout_sec` is 30 seconds

**Stage 5** · Rulebook Ch. 8.4 and Appendix F · Spec: [PRD-5](prd/PRD-5-tunneling.md) FR-5.8

The rulebook asks for two things: measure the real round-trip latency over the
tunnel, and defend the timeout against it in writing. This is the writing.

## What the timeout is actually covering

The obvious budget is wrong, and it is worth showing why before showing the
right one:

```
network round trip  +  opponent's thinking  ≤  response_timeout_sec
        ?                    30 s           ≤        30 s
```

`step_deadline_seconds` is 30 on its own, so this says the shipped
configuration cannot work. It says that because the premise is wrong.

**Inbound calls are fire-and-forget.** A tool call into `PeerInboxes` validates
the message, drops it in a queue and returns `{"ok": True}`. The opponent's
decision-making happens *after* our response has already gone, on their clock,
and their reply arrives as a separate push into our server. So the real budget
is:

```
network round trip  +  validate and enqueue  ≤  response_timeout_sec
     tens of ms              microseconds     ≤        30 s
```

The opponent's thinking is bounded by a different number entirely —
`turn_timeout_seconds` (180 s) in the private config, with
`step_deadline_seconds` (30 s) capping the language model inside it.

This is why the decoupling in `infra/inboxes.py` is load-bearing rather than
tidy. If a tool call blocked while the far side chose its move, every team's
`response_timeout_sec` would have to exceed every other team's worst thinking
time — and a peer that thought slowly would time out a peer that was working
perfectly.

## Measuring

`infra/latency.py` wraps the transport:

```python
from thief_agent.infra.latency import TimedTransport, justify

transport = TimedTransport(real_transport)
client = OpponentClient(transport, settings)
# ... play a warm-up match ...
print(justify(transport.log))
```

The wrapper sits **inside** the retry loop, not outside it. Timing the loop
would fold four failed attempts and two five-second backoffs into a single
"round trip" and make a healthy tunnel look unusable. Failed calls are not
recorded at all: a connection refused returns in microseconds and would drag
the median toward zero, making a dying tunnel look like a fast one.

Percentiles are nearest-rank, so a reported p95 is a duration that actually
occurred rather than one interpolated between two that did.

## Recorded measurements

> **Not yet measured.** These rows are filled from a warm-up match over a real
> tunnel against a real opponent, which has not happened yet. `justify()`
> reports `UNJUSTIFIED` — not "generous" — until there is evidence behind the
> number, which is the distinction the rulebook is asking for.

| Opponent | Date | Calls | Median | p95 | Slowest | Margin over p95 |
| -------- | ---- | ----- | ------ | --- | ------- | --------------- |
| _(warm-up)_ | | | | | | |
| _(counted #1)_ | | | | | | |
| _(counted #2)_ | | | | | | |

Fill these in before agreeing terms for a counted match, and paste the
`justify()` line into the match's config commit.

## The verdict we expect, and the one that would worry us

An HTTP round trip through ngrok or Localtonet between two machines in the same
country is normally tens of milliseconds. Against a 30-second timeout that is a
margin of several hundred times over, and `justify()` will say `ample`.

`COMFORTABLE_HEADROOM` is set at **10×**, not 2×. The failure being guarded
against is not the average call being slow — it is one call in a match hitting a
stall an order of magnitude past normal. A technical loss scores **zero for both
sides**, so the price of a thin margin is a whole sub-game, not a retry.

If a tunnel ever measures `THIN`, that is a fact worth having before the match
rather than inferring it from a technical loss afterwards.

## Changing the number

`response_timeout_sec` is a **minimum** in Appendix F. It may be raised by
mutual agreement and **never lowered**, silently or otherwise — a lowered
threshold is a deviation from a signed condition, and the negotiated value is
hashed into `config_sha256`. If a measurement ever justifies raising it, raise
it in the shared `game.json`, re-exchange the digest, and record why here.
