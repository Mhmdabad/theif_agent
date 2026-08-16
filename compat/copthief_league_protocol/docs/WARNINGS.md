# Warnings — the mistakes that cost points, including someone else's

Most of what can go wrong in this game costs you a game. A few things cost **both teams** a game,
including the one that did nothing wrong. Those are first.

Read this before you configure a recipient, and before you name a start time.

---

## 1. A failed series must send **nothing**

> **App. E rule 35** — each team sends its own final report; a missing report from one side, **or
> contradictory reports**, disqualifies the game and scores **0 for both teams**.

Read that sanction twice. It is not "you lose the points you would have won". It is *the opponent
loses theirs too*. So the dangerous instinct after a series that half-worked is the helpful one:
send what you have, note the gap, sort it out afterwards. That is precisely the contradictory
report the rule punishes, and the other team pays for it.

**Build the refusal into the settlement path**, not into your memory:

- **One sub-game that never settled refuses the whole series.** A report that quietly drops a game
  describes a different series from your opponent's report of the same match.
- **An aborted game has no honest summary.** No revealed records means no result; refuse loudly
  rather than writing a hollow entry.
- **Derive, never declare.** Totals come from the per-sub-game results by the fixed scoring table
  (book ch.9), so agreement on the sub-games *is* agreement on the totals. A separately declared
  total is a second source of truth and will eventually disagree with the first.
- **Decide before you start.** A run that owes a report should refuse to *begin* if it could not
  deliver one — an empty recipient or a stale token is cheap to discover before six sub-games and
  expensive after the sixth settles.

**Make the failure legible to whatever runs you.** Distinguish, by exit code, "I refused to report
a series that never settled" from "the report exists but did not reach anyone". They need different
next actions: the first is over, the second still owes an artifact to your opponent.

Finish every sub-game even after one fails, though. A series is six games; quitting early leaves
the other team playing a match you have abandoned.

---

## 2. Derive the `game_uid` from the **flat negotiated terms** — not from your config

The `game_uid` is a pure function of two things: the **flat negotiated terms** and the two sorted
group ids (SPEC §4). It is the only key that joins your report to your own sealed logs *and* to
your opponent's report.

So there are two ways to get it wrong, and **the second is much harder to catch than the first**:

| | What it looks like |
|---|---|
| **A fresh id** | Obvious once anyone looks: the uid appears nowhere in your logs. |
| **A deterministic id from the wrong input** | **Everything looks healthy.** The uid is stable, reproducible, and identical across all four of your artifacts — they join to each other perfectly. Only the *cross-team* join fails. |

The correct input is the flat 14-key set that was signed and exchanged — the reference computes
`derive_game_ids(terms_from_config(...), ...)`, where `terms_from_config` **extracts** those keys.
Feeding the whole `game.json`, or any wider configuration object, produces a uid that is wrong in a
way nothing on your side can see.

**This is the one that actually happened.** In the 2026-07-25 cross-team series, one side's uid was
derived from its whole config rather than from the flat negotiated terms. Its four artifacts were
internally self-consistent on that uid and looked entirely correct; every game *value* in the two
teams' reports agreed exactly — same winner, same totals, same per-sub-game outcomes. Nothing in
either implementation noticed, because nothing on either side had reason to look.

*(Our first published account of this said the uid had been "freshly minted". That was wrong, and
the correction is anrbj666's — the true mechanism is more instructive than the one we guessed,
because a minted id announces itself and a wrongly-derived one does not.)*

**Why it stayed silent for six sub-games:** the uid never crosses the wire. Each side derives it
independently and neither has anything to compare against, so a divergence surfaces only when two
reports are diffed — which happens *after* the games are over. See §2a.

Keep a fresh id for internal attempt bookkeeping if you want one. The **emitted** uid is derived,
from the terms.

```
python tools/check_artifacts.py <your artifact dir> --terms terms.json
```

catches both classes in one second. Note the `--terms`: without it the tool can only check that
your uid is *consistent*, which the wrong-input case already is. Pass the flat signed terms and it
**re-derives** the uid and compares — which is the only check that catches the sneaky one.

And before either side reports, run it over **both** artifact sets:

```
python tools/check_artifacts.py <your dir> <their dir>
```

It checks each set and then the **join between them** — the check neither team can perform alone,
because each bundle is internally perfect. That is precisely the check the 2026-07-25 pairing
needed and did not have.

---

## 2a. Declare your derived `game_uid` at the handshake (PROPOSED)

The reason §2 stayed invisible for a whole series is structural: **the uid never crosses the wire.**
Both peers derive it independently, so neither has anything to compare, and the first moment a
disagreement can surface is a post-game report diff.

The proposed closure — SPEC §7.3, and deliberately the same shape as the pairing declaration in
§7.2 — is for each peer to declare its derived uid top-level in the negotiate extras:

- both declare and the values **differ** → refuse, before a single move is played;
- either side omits it → **play**. Omission never refuses, in either direction; the unmodified
  reference peer declares nothing at all, and a guard that fail-fasts on silence forfeits that game
  to itself.

Status is **PROPOSED**: both implementations have declared it live since 2026-08-01 (every
handshake through the 2026-08-04 counted series, values matching), but the **refuse** row of the
table has never fired cross-team and only one implementation's tests pin it, so under
[`GOVERNANCE.md`](GOVERNANCE.md) the behaviour table is not yet reproduced. Do not assume an
opponent refuses on mismatch — but declare it anyway: a wrong-input uid then becomes a refusal at
the handshake instead of a contradiction in two reports the next morning.

*Finding credited to both teams: imreeyal observed that the divergence was silent for the entire
series; anrbj666's root-cause analysis made the mechanism precise.*

---

## 2b. Answering a push is not replying to it

Two conformant peers can wait on each other forever, and **every probe you own will say both are
healthy.**

`negotiate` can be built two ways, and the kit's vectors pin the bytes rather than the direction:

- as a **push** — call the opponent's `negotiate`, discard the return value, and wait for *their*
  call to arrive at yours;
- as **request/response** — call the opponent's `negotiate` and read the agreement out of the reply.

A push peer and a request/response peer are each internally correct and mutually mute. The
request/response side answers every call perfectly — and its answers land in a variable the push
side never reads. The push side, meanwhile, may have no outbound call at all, because its design
expects to be spoken to first. Both logs show healthy traffic. Neither shows an error. **The
missing thing is missing from both**, so there is nothing to see until the deadline expires.

What makes this worse than a normal interop bug is that the usual pre-flight passes. `tools/list`
matches. Argument names match. Terms match, signatures verify, the call returns 200. A pre-flight
that diffs tool names *and* argument names — a good pre-flight, better than most teams have —
passes clean, because the shape that is wrong is in neither list.

**Two defences, and you want both:**

1. **Read the response body as well as your queue.** A peer that answers your call correctly should
   never be mute to you. Accepting an agreement from either place costs nothing and makes your side
   compatible with both dialects.
2. **Push first, without waiting to be spoken to.** Whoever speaks first unblocks the other, so
   speaking is never the wrong move.

*Found by **best2934** and **imreeyal** on kit issue #45, from two live stalls in one night. The
diagnosis needed both halves: best2934's log showed thirteen well-formed answers going out;
imreeyal's showed a handshake that had never read a reply.*

---

## 2c. An unknown tool is not a dead peer

When a `tools/list` comes back with none of the names you expect, the tempting reading is that
nobody is home. It is the wrong one, and it costs a window.

A peer publishing ten tool names you have never seen is **running, reachable, and conformant to
its own design** — you have found a dialect, not a corpse. The correct next action is to name the
mismatch to your opponent, not to retry the endpoint or wait for it to come up. It is already up.

So **log the names you actually received**, in both directions and tallied — not merely "handshake
failed". A team that logs only its own view has no way to log an *absence*: a client that called
nothing produces no record anywhere, and the one fact that matters is then structurally invisible
to the side that needs it. Names only, never bodies — a turn carries a commitment and an audit
carries the nonces, and neither belongs in a file that gets pasted into an issue thread.

SPEC §7.5 pins the four tools and their payloads precisely so this conversation can be short.

*Both league pairings hit this. Credited to **best2934**, whose tool-name tally turned the second
stall from a guess into a diagnosis in one message.*

---

## 2d. Read the other side's edge before you blame the other side's code

`502`, `530`, `404` and `406` are four different facts and only one of them is about your opponent's
agent. Guessing between them wastes a window at best and produces a false accusation at worst.

| what the probe returns | what it actually means |
|---|---|
| **406** (or any non-5xx) | a peer is **bound** and answering — an MCP endpoint refusing a bare `GET` is a *healthy* endpoint |
| **502** | the tunnel is up and reaching its origin, but **no peer is bound** — the correct standby state between sub-games |
| **530** | the tunnel is up and the **origin is unreachable** — your own process, not the network |
| **404 + `ERR_NGROK_3200`** | **no agent is connected to the reserved domain at all** — the tunnel client itself is gone |

That last row is the one that gets misread. The domain still resolves, TLS still completes, and you
get a clean HTTP response — so it looks like a routing or path mistake and invites a round of "are
you sure that is the right URL?". It is not a URL problem. `ERR_NGROK_3200` means the agent process
on the other side has stopped, and no amount of correctness on your side will produce a game until
it restarts.

**So put the probe in your launcher and gate on it.** Refusing to start against a dead endpoint
costs nothing and leaves no artifacts to clean up; discovering it after the handshake budget
expires costs a window and writes a technical loss into a log you then have to explain. And check
the *specific* error code, not merely "did I get a non-5xx" — a bare `502` check cannot tell a
healthy idle tunnel from one with no ingress at all ([LEAGUE-OPS](LEAGUE-OPS.md)).

---

## 3. Make the lecturer's address unreachable, not merely unconfigured

An address you have configured is one flag away from being used. An address the run *cannot*
reach is not.

- **Authorization is the configuration, and the recipient is the switch.** A generic "sending is
  allowed" boolean says only that sending may happen; a recipient says who receives it — and
  nobody types the lecturer's address by accident.
- **Authorize before the match, never inside it.** By the time a series is running there is no
  human step left (book §9.3), so every decision about where mail goes has already been made.
- **A non-counted run should refuse the lecturer structurally** — matched case- and
  whitespace-insensitively, including when hidden inside a list of recipients.
- **Practising? Point your mail at yourselves, or at nothing.** Never at the lecturer. A warm-up is
  not a counted game (App. E rule 52 permits uncounted warm-ups explicitly), so nothing is owed and
  nothing should be sent onward.
- **Rate-limit the sender.** The book's own answer to a runaway loop is not human review; it is the
  gatekeeper of rule 28 — quota, then token bucket, then a breaker on repeated failure.

**Only one counted game per opponent** (App. E rule 52). An accidental early send can burn the one
meeting that scores, so the cost of being casual here is not symmetric.

---

## 4. Two teams, one match, two names for it

**`game_id` is the sorted pair**: `"-vs-".join(sorted([g_a, g_b]))` — see SPEC §4. A peer that
names *itself* first produces a different `game_id` on each side, so one match yields two sets of
artifact filenames and two reports that cannot be joined by `game_id` at all.

Both sides of the 2026-07-25 series did exactly this — **and the `game_uid` diverged in the same
run** (§2). Two reports that agreed on every game value could be joined by neither key. If you are
tempted to treat `game_id` as cosmetic because the uid will save you: in the one run where this has
actually been observed, it did not.

*(Both implementations now sort the pair — anrbj666's did so already, and imreeyal adopted it on
2026-07-27.)*

If you and your opponent cannot agree, agree to join on `game_uid` alone — and then be certain
yours is derived from the flat negotiated terms (§2).

---

## 5. Stale state does not announce itself

**Attempts share a deterministic `game_uid`.** That is the point of deriving it — but it means a
burned attempt and the real series produce the *same* artifact names and the same uid. If your
logger appends, a dead attempt leaves records at the top of the very files your settlement reads.

**Archive between attempts; never delete.** Move the previous attempt's logs aside before you start
a new one. The evidence may matter later, and the aggregation must not see it now.

**An orphaned peer will play a game for you.** A peer left alive from an earlier attempt still holds
the port. It will catch a sub-game, play it to a clean mutual audit, and settle it — while your
*real* peer for that sub-game starts a second later, starves behind it, and honestly reports a
timeout it did not cause. One game, two indices, and nothing anywhere notices that two of your peers
were alive at once. **Killing a shell does not kill what it spawned.**

```
python tools/netcheck.py --loopback <series port> <your public hostnames>
```

refuses to run if anything already holds the port, and tells you why.

**A settled peer should stop accepting.** Between settlement and process exit, your opponent's
*next* sub-game peer will greet you. Accepting there swallows the greeting into a queue nobody will
drain: they burn their whole connect budget on a message you acknowledged, and run ahead of you for
the rest of the series. Refusing makes it an ordinary transport failure, which their retry resolves
by delivering to your next peer.

---

## 5a. The first-meeting ledger must advance — and must be committed

The result's league fields (`games_played_including_this`, `first_meeting_between_groups`,
`diversity_reward_applied` — SPEC §6.2) are fed by a ledger of counted games that only your own
repo keeps. Two ways it silently rots, **both observed** — each of the first two league teams
found one of them in the other's tree during the pre-counted mutual audit:

- **The ledger lives in a git-ignored file.** Then a fresh clone — a grader's clone — cannot
  prove the pairing already played, and rule 52's one-counted-game-per-opponent is guarded by
  nothing but memory. Committed evidence or it is not evidence.
- **Nothing advances it.** A run that reports a counted series but never writes the ledger makes
  the *next* counted series declare `first_meeting_between_groups: true` against a repeat
  opponent — a false declaration under **rules 37–38**, which are project-disqualification
  rules, produced automatically by an honest team.

So: the ledger write is part of the counted run's settlement path (arming the run is what bumps
it — never a calendar or a human), and the post-series commit that archives the artifacts
commits the advanced ledger with them. A counted series is not over until the ledger that proves
it happened is pushed.

One disambiguation, because a grep will mislead you (anrbj666's P5-8): **the kit's sparring peer
deliberately has no rule-52 ledger** — it cannot play a counted game, so the mechanism this
section describes belongs in *your* implementation, not here. The `ledger` you will find in the
sparring source is its per-sub-game outcome list, an unrelated object that happens to share the
word.

---

## 5b. A verdict your schema advertises must be producible by your code

If your audit can fail, something must be able to say so out loud. The hazard: an outcome that
is *defined* in your schema, *scored* in your tables, and *reachable by no code path* — so the
one time it matters, your settlement writes a healthy-shaped row instead.

This is not hypothetical, and this repo is the example: until 2026-08-04 the sparring peer
defined `tamper_forfeit`, scored it 0–0, and **assigned it nowhere** — a failed audit produced a
`log_verified: false` buried in a row whose `result` still said `capture`. (Found as a corollary
of anrbj666's audit; their framing of why it matters is the right one — *an outcome reachable by
no code path is worse than an unimplemented check, because the artifact schema advertises a
verdict the peer cannot render.*)

The check is mechanical: for every value your `result` field can carry, find the line that
assigns it. An outcome with zero assignment sites means the failure it names will be reported as
something else — and under rule 35, two teams describing one failure differently is the
contradiction that zeroes both.

---

## 5c. An ending only you can see must be SAID, or you fork the game

Two of the three ways a capture happens are facts about the **thief's own hidden position** — a
barrier dropped on its cell (rule 46) and no legal move left (rule 47). The cop cannot infer
either. If your thief settles those endings silently, it stops playing while the cop, having
learned nothing, waits out its whole budget and settles a **timeout**. Both peers are honest,
both are correct by their own knowledge, and they have just described one sub-game two ways —
the contradictory-report shape rule 35 zeroes for **both** teams.

It is worse than a normal bug in two ways. It only appears in a **live** run: self-play shares a
process, so the outcome never has to travel, and a one-sub-game CI test is protected by
random-walk odds. And it cascades — from the fork on, the two peers are auditing different
games, so the next sub-games settle as `tamper_forfeit` and the sub-game index drifts until one
side gives up.

This repo is the example. Two copies of the sparring peer were played against each other over
real HTTP; sub-game 3 settled **capture on one side and timeout on the other**, three runs out
of three, no fault injected (anrbj666, issue #37). The settlement guard then correctly refused
both result artifacts — the guard held, but the game it was guarding had already split in two.

**The fix costs nothing**, because the vocabulary already exists: the thief's game-ending final
carries `claim_response: {"claim": [own final cell], "caught": true}`, the same shape every
implementation already emits on a co-location capture, and a conforming cop already settles
CAPTURE on it. See SPEC §3.1 for the construction, the answer-vs-concession distinction, and why
the cop must **corroborate** a `caught: true` rather than believe it.

The check is mechanical, and it is the same shape as §5b above: find the line where your thief
detects a rule-46/47 ending, and follow it to the message that leaves your process. If there
isn't one, your opponent will never know you lost.

---

## 5d. Audit against the commitment that **arrived**, not the one in the record

A commit-reveal audit has two inputs and it is easy to ship with only one.

At the end of a sub-game your opponent discloses a list of records — position, nonce, and the
commitment each one hashes to. The obvious check is that every record is self-consistent: recompute
`SHA256(canonical(payload)|nonce)` and compare it to the commitment **printed in that same record**.
That check passes on every honest game, so it looks finished.

It is worth nothing on its own. A record whose position, nonce *and* commitment were all rewritten
after the fact is perfectly self-consistent — you are verifying a document against itself. The
commitments that actually constrain anything are the ones that **crossed the wire during play**,
one per turn, before the position they hide was knowable. Those are the promise; the disclosed
records are merely the claim to have kept it.

**So keep your own archive of the live commitments and bind the disclosure to it**: for every step,
the commitment in the disclosed record must equal the commitment you received at that step, and
every step you received must appear. Then recompute the hash. A disclosure that changes any sealed
position now fails, because the live commitment is a value the opponent can no longer choose.

Two properties worth stating, because they decide whether this is real:

- **Verify it is live, not merely present.** The check is easy to write and easy to leave
  unreachable (§5b is the same hazard). Run a real game and confirm the auditor is holding a
  non-empty set of received commitments — a check fed an empty archive passes everything.
- **It costs the honest peer nothing.** Both implementations that have shipped it report no
  behaviour change on clean games, which is exactly what a tamper-evidence check should look like.

*Raised by **gal-roy1** on kit issue #48, and already built by **best2934** at the time it was
raised. imreeyal's audit had the self-consistency half only.*

---

## 6. Report format traps

- **Rule 34 says JSON attachment; the book's own listing sends a text body.** The rule requires the
  final report as an attached JSON file and refuses free text, but the book's Appendix A listing and
  the reference implementation send a plain body with no attachment. Sending **both** satisfies the
  rule literally and whatever the grader's tooling actually reads. Over-satisfying a contradiction
  is cheaper than picking the wrong side of it — and per the book's academic-freedom clause, say so
  in your documentation rather than choosing silently.
- **And "both" means the result, twice — not the whole artifact set.** One email per team per
  series: the result JSON as the body and the same file as the single named attachment. The other
  three artifact types are published in the repos and reached via the result's `links.github`
  (rule 49), never mailed. Both league teams flip-flopped on this in a single day (a 14-attachment
  reading of the §9.3.3 template list looked equally defensible) before settling it with evidence —
  SPEC §6.1 has the convention, the evidence, and the documented tension with §9.3.3's prose, so
  read it there instead of re-fighting it with your opponent by email.
- **The emailed bytes must be the exact canonical bytes that were hashed** — never a pretty-printed
  re-serialization. Two teams once matched on every hash while one team's *email* was a
  re-serialization, and it nearly scored zero (SPEC §6).
- **Check your OAuth token before a counted series.** A Google Cloud project left in Testing mode
  expires refresh tokens after **seven days**, so a token that worked last week fails silently at
  the one moment you cannot retry.
- **Send-only scope** (rule 30). Note that a send-only scope cannot create drafts — if your safety
  gate depends on drafting, it depends on a broader permission than the rules allow.

---

## 6a. The tie rule is undeclared, and you will find out on the one series that ties

Three behaviours are live in this league and all three are defensible, because the book and the
reference disagree about where the App. F tie score (2) lands:

| behaviour | who | totals for a 25–25 series |
|---|---|---|
| `series_add` | this kit, imreeyal, anrbj666, best2934 | 27 / 27 |
| `series_replace` | the book's other reading | 2 / 2 |
| `per_subgame` | the reference implementation | 25 / 25, with tied ROWS paying 2 each |

The book puts the award at the **series** level, on the accumulated score (ch.9 *כלל התיקו*, and
App. F **table 17** row 5, which is binding for the value). The reference awards it **per
sub-game** and plainly sums — see its own `4-final-result.txt`. The course staff have ruled this a
genuine contradiction under the academic-freedom clause: implement either, **document and justify
the choice**. SPEC §6 has the full disposition and this kit's documented choice.

**Why it is a trap rather than a disagreement.** It cannot surface in a friendly, because a level
series is rare. It cannot surface in testing, because each side is self-consistent. It surfaces
exactly once — in a counted series that happens to tie — and then two honest reports carry
different `total_score` values for one match, which is the contradiction rule 35 zeroes for
**both** teams.

**So declare it before the first window, beside the scent model**, as a `tie_rule` value:
`series_add | series_replace | per_subgame`. One line in the pairing constitution costs nothing;
the alternative is a coin flip you do not know you are making. *(Raised by **best2934** on kit
issue #45, along with the observation that the kit had attributed its own rule to the one source
that contradicts it.)*

---

## 7. If you are practising

Warm-ups are explicitly permitted and encouraged (App. E rule 52) — *"warm-up games that are not
counted are permitted and even recommended, for testing and calibration before the counted game."*
That permission comes with a shape:

- **Nothing is owed.** A practice game is not a game under rules 32/35, so no report is due from
  either side. Do not expect one from a practice peer, and do not send one.
- **Point your own mail at yourselves or disable it.** See §3.
- **Mark practice artifacts so they can never be mistaken for a league pairing** — a distinct group
  id is enough, since `game_id` is built from the group ids.
- **A practice partner cannot certify you.** Passing against one implementation proves you agree
  with *that* implementation. `python verify_vectors.py` is what proves you agree with the pinned
  bytes; the behaviour tables (SPEC §7, §7.1, §7.2) are what prove you agree on the decisions.

---

## The short version

| Do not | Because |
|---|---|
| send a report for a series that did not fully settle | rule 35 zeroes **both** teams |
| derive the `game_uid` from anything but the flat negotiated terms | your four artifacts still join each other perfectly; only the cross-team join fails, and nothing on your side can see it |
| configure the lecturer's address in a non-counted run | it is then one flag from being used |
| name the pair self-first in `game_id` | one match, two names, two sets of files |
| reuse a log directory between attempts | attempts share a deterministic uid; appended dead records reach settlement |
| keep the counted-games ledger uncommitted, or forget to advance it | the next counted series declares a false first meeting on its own (rules 37–38, 52) |
| assume the shell you killed took its children | an orphan will play a sub-game and settle it |
| trust a bare `502` check | it cannot tell a healthy idle tunnel from one with no ingress ([LEAGUE-OPS](LEAGUE-OPS.md)) |
| read `404 ERR_NGROK_3200` as a wrong URL | the URL is fine; the agent behind it is gone, and nothing you change will help |
| assume a peer that answers your `negotiate` has replied to it | a push and a request/response peer are each conformant and mutually mute, and every probe passes |
| read an unfamiliar `tools/list` as a dead peer | you have found a dialect, not a corpse — say so instead of retrying |
| verify a disclosed record only against the commitment printed inside it | that is a document checked against itself; bind it to the commitment that arrived live |
