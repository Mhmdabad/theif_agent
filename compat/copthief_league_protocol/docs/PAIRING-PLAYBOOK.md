# Pairing playbook — from first contact to a reported counted series

[`START-HERE.md`](START-HERE.md) certifies your bytes. [`LEAGUE-OPS.md`](LEAGUE-OPS.md) runs one
scheduled window. This page is the layer above both: **the whole lifecycle of one pairing** — the
messages two teams exchange, in what order, with what in them, and the checks between them — so
that the single counted series at the end is a 90-second formality instead of a first date.

It is written from a completed campaign: the anrbj666 ↔ imreeyal pairing, 2026-07-24 → 2026-08-04.
Seven scheduled windows to the first clean friendly (2026-07-25 — that run is the ledger in
LEAGUE-OPS), then five clean friendly series in one day (2026-08-03), two mutual repo audits with
written dispositions, and a counted series (2026-08-04) that played six sub-games in 78 seconds
with every audit clean, one report per team, and byte-identical `mutual_agreement` hashes.
*(An earlier revision compressed all of this into "2026-08-01 → 04", leaving the seven-window
ledger attributed to two different runs — caught in anrbj666's own audit of their own text.)* Every stage below exists because skipping it cost one of us an evening —
or would have cost both of us the counted game.

Everything here fits the reference-v3 wire and the four-artifact format
([START-HERE vocabulary](START-HERE.md#the-vocabulary-this-repo-assumes)); where a construction is
pinned by a vector, the vector is cited. Where the book admits two readings, both are named — a
playbook that silently picks one becomes a new source of cross-team divergence.

---

## Stage 0 — before you contact anyone

All four [START-HERE](START-HERE.md) gates pass, **including the loopback netcheck**
(LEAGUE-OPS §2). Additionally:

- **Your lecturer-address guard is structural, not disciplinary**
  ([WARNINGS §3](WARNINGS.md#3-make-the-lecturers-address-unreachable-not-merely-unconfigured)).
  The pattern that survived our whole campaign without one stray mail: the league address may be
  addressed only when a counted run is **doubly armed** — a config flag (`counted = true`) AND a
  CLI flag (`--counted`) on the very invocation. Every friendly below runs with reports going to
  the two teams' own inboxes only. Additionally in the counted direction: an ARMED counted run
  should **refuse to play at all** if it could not deliver the league report (mode not `send`, no
  league recipient, token dead) — a counted series owes the league a report, and discovering a
  dead mail rail after the sixth settle is the worst possible time.
- **Your artifacts top level starts clean.** A friendly and the counted series against the same
  opponent share a deterministic `game_uid` and therefore the exact same artifact filenames
  ([WARNINGS §5](WARNINGS.md#5-stale-state-does-not-announce-itself)). The layout that makes this
  a non-event: snapshot every settled series into its own committed archive folder
  (`results/friendlies/<pairing>-<stamp>/`, laid out as a mini repo root — `results/` +
  `config/games/` inside — so each archived log's config artifact resolves beside it and the full
  audit replays against the snapshot unchanged), and keep the live top level **empty** before a
  counted T so the counted artifacts arrive as pure adds, never overwrites.

---

## Stage 1 — first contact: the planning message

One message opens a pairing. Ours converged on this shape; every field below earned its place by
its absence burning a window somewhere:

```
Hi — <group_id> here (<member names>), proposing a pairing.

IDENTITY
  group_id:        <8-char code, no spaces>
  members:         <names>
  repos:           cop <URL> / thief <URL>
  MCP endpoints:   cop <https://.../mcp> / thief <https://.../mcp>
  topology:        role-split services (address changes with role) | single service
  wire shape:      reference-v3 (flat 14-key terms + nonce + signature),
                   wire_shape_sha256 <hash of the registered doc — SPEC §7>
  turn order:      thief moves first each sub-game (the reference's behaviour —
                   NOT covered by the wire_shape lock; two peers that disagree
                   here deadlock silently after a perfect handshake)

CONSTITUTION (proposed shared game.json, attached)
  - flat terms exactly as in the attachment; note max_moves == survival_threshold
    (the flat form carries ONE step field — a config where they diverge cannot be
    represented and must be refused, not approximated)
  - schema_version: <e.g. "1.1"> — byte-identical in every artifact both sides emit
  - agreed_between: ["<first-group>", "<second-group>"]  (sorted; see Stage 2)
  - scent model: <model id>, sha256 <hash> — our implementation file + golden
    vectors attached; run the file or prove your implementation reproduces the
    vectors (book ch. 4.5: sharing is "permitted and even recommended")
  - info_mode: <belief | exact>, info_mode_sha256 <hash> — the posture lock
    (SPEC §7; both-declare-and-differ refuses, so compare hashes in chat first)

MAIL & FAILURE POSTURE
  friendly reports: <our inbox(es)> + <yours> ONLY — never any lecturer address
  counted reports:  <the league alias> (confirmed before the counted T, Stage 6)
  retry policy:     discard-and-rerun by mutual written agreement (Stage 7)
                    unless you propose otherwise — pick one BEFORE any T

DERIVED (verify independently, do not take our word)
  game_id:   <sorted pair joined -vs->
  game_uid:  <uuid from SHA256(canonical(flat terms) | sorted group ids)>

ROLES (Stage 3 convention unless you object)
  <first-sorted group> plays COP on odd sub-games (1,3,5),
  <second-sorted group> plays COP on even (2,4,6)

PROPOSED FIRST FRIENDLY: T = <day, HH:MM, timezone written out>. Uncounted:
reports to our two inboxes only, nothing to the lecturer, no league fields
armed. We follow the T-protocol (LEAGUE-OPS §1).
```

Three rules about this message:

1. **Attach the constitution as a file, not prose.** Two peers that agree in chat and disagree in
   `config` refuse each other at the handshake (LEAGUE-OPS window 4). The file is the agreement;
   the chat is commentary.
2. **Both sides derive `game_uid` independently and compare in chat** before any window. It is a
   pure function of the flat terms + sorted group ids (`vectors/game_uid.json`), so a mismatch
   here is a five-minute chat fix instead of a silently divergent series
   ([WARNINGS §2](WARNINGS.md#2-derive-the-game_uid-from-the-flat-negotiated-terms--not-from-your-config)).
3. **Name the topology explicitly.** A driver that assumes one-address-for-the-series is wrong
   half the time against a role-split opponent (LEAGUE-OPS §4).

**Where to send it:** an issue on this repo reaches the maintainer teams — the
[proposal or operational-report templates](../CONTRIBUTING.md) both work. First contact on the
record beats first contact in a DM: almost every line of the message above is a checkable claim,
and an issue thread is where the checking naturally happens.

---

## Stage 2 — the constitution, and what is actually load-bearing in it

- **Identity is the canonical hash, not the bytes.** Two conformant sides on different formatters
  hold the same agreement; compare `SHA256(canonical(shared config))`, never file bytes
  (SPEC §2).
- **`agreed_between` carries the real team ids, sorted** — the same sort that builds `game_id`.
  Two findings from our campaign, verified in both implementations and then live:
  - `agreed_between` is **not one of the 14 flat terms**, so it does not feed `game_uid` and it
    never crosses the reference wire. Swapping a placeholder for the real names **cannot break a
    handshake** — verified by smoke (uid byte-identical before/after) and then by a full series.
  - Therefore adopt the real names **early**, in the rehearsal config too. The standing rule that
    kept us honest: *a friendly differs from a counted game only in not being counted and not
    mailing the lecturer.* Every placeholder that exists only in rehearsal is a divergence that
    counted day must remember to fix — and counted day is the wrong day for remembering.
- **The scent model is locked before the first window, with code or vectors attached.** A run
  config still declaring last week's model refuses at the handshake (LEAGUE-OPS window 4;
  SPEC §7 locked-model declarations).
- **Everything numeric comes from the book's appendix.** If the book and any example disagree, the
  book wins, and the disagreement gets written down (see Stage 5 — both teams keeping a written
  interpretation record is what made our disputes short).

---

## Stage 3 — roles, sub-game ownership, and who does what

The book alternates roles across the six sub-games but does not name who starts. Any convention
works **if it is stated**; unstated, each side "obviously" starts as its own favourite role and
the pairing checks refuse for a whole window. Ours, offered as a default:

> **The alphabetically-first group (the same sort that builds `game_id`) plays COP in the odd
> sub-games (1, 3, 5); the second group plays COP in the even ones (2, 4, 6).**

Derived duties, so nothing is owned by "whoever notices":

| Duty | Owner | Why |
|---|---|---|
| Windows 1,3,5 | first-sorted group's cop + second's thief | the convention above |
| Windows 2,4,6 | second-sorted group's cop + first's thief | — |
| Sequencing | window N launches only after N−1's log exists | a window that starts its handshake budget before the rival's driver reaches it burns the budget against nobody (LEAGUE-OPS §6, the runaway-series hazard) |
| Series close + report | **each team closes and reports for itself** once all six logs settle; within a team, the driver that owns sub-game 6 closes | the closer must be able to see all six logs; the other driver defers with a named refusal, not a guess |
| Aggregation guard | every sub-game 1..6 needs a settled, audit-clean log or the series emits **nothing** | [WARNINGS §1](WARNINGS.md#1-a-failed-series-must-send-nothing) |

Declare `sub_game_number` and `role` alongside the greeting (SPEC §7.2) — it is what turns a
leftover instance from a previous window into a named refusal instead of a wrong game.

### The window map — who dials whom, spelled out

The single most "obvious to us, opaque to a stranger" fact in the whole lifecycle. Each agent
runs its **own** MCP server and dials the **opponent role's** endpoint — so under role-split
topology the URL you must dial changes every window. For the example pairing (`team-aleph`
first-sorted, so cop on odds; endpoints as in
[`examples/pairing-artifacts/`](../examples/pairing-artifacts/README.md)):

| Window | team-aleph runs → dials | team-bet runs → dials |
|---|---|---|
| g01 | its **cop** → `https://thief.team-bet.example/mcp` | its **thief** → `https://cop.team-aleph.example/mcp` |
| g02 | its **thief** → `https://cop.team-bet.example/mcp` | its **cop** → `https://thief.team-aleph.example/mcp` |
| g03 | its **cop** → `https://thief.team-bet.example/mcp` | its **thief** → `https://cop.team-aleph.example/mcp` |
| g04 | its **thief** → `https://cop.team-bet.example/mcp` | its **cop** → `https://thief.team-aleph.example/mcp` |
| g05 | its **cop** → `https://thief.team-bet.example/mcp` | its **thief** → `https://cop.team-aleph.example/mcp` |
| g06 | its **thief** → `https://cop.team-bet.example/mcp` | its **cop** → `https://thief.team-aleph.example/mcp` |

Rules of the map:

- **Both sides dial.** There is no client team and no server team — each peer pushes its own
  messages at the other's endpoint. A team that only listens plays nobody.
- Under **single-address topology** (LEAGUE-OPS §4) a team's two columns collapse to its one URL;
  the role alternation is unchanged.
- Put this table — with the real URLs — **in the Stage-1 exchange**, filled in by both sides.
  Every burned-window cause in the LEAGUE-OPS ledger that involved "dialed the wrong thing" dies
  on this table.
- The wire enforces what the table promises: `role` must be complementary and `sub_game_number`
  equal (SPEC §7.2), so a wrong-row dial is refused in seconds, by name.

### What a healthy series looks like on the clock

From the campaign's counted run (T = 01:00:00), so a third team knows what "normal" is and when
to worry — the whole series is **under two minutes**:

```
01:00:00  both sides' runners fire (nobody waits for the other's confirmation)
01:00:01  g01 handshakes and starts        01:00:20  g01 settles (~19s)
01:00:18  g02 starts (tempo gate: g01's LOG exists — see below)
01:00:33  g02 settles · g03 starts         01:00:40  g03 settles (~8s)
01:00:39  g04 starts                       01:00:53  g04 settles
01:00:52  g05 starts                       01:01:00  g05 settles
01:00:59  g06 starts                       01:01:14  g06 settles
01:01:17  the sub-game-6 owner aggregates, emails ONE report, writes the ledger
```

**Why windows appear to overlap by a second or two:** the tempo gate is the previous
sub-game's **log file existing**, not the previous runner *process exiting*. A window writes
its log, then spends a second or two on its own closing bookkeeping before it prints
"settled" — so the next window legitimately starts before the previous one's settle line.
Reading the gate as "wait for the process to exit" serializes the series and adds a dead
second per window for nothing.

Sub-games run 8–20 seconds each; a window that shows **no handshake ~60 seconds after its turn**
is not slow, it is stuck — check the map row you are on, then the refusal taxonomy (connection
contract below). A *failed* handshake ends in ~60s while a real sub-game takes minutes only when
LLM hints are armed; with template hints the whole series should finish inside two minutes.

---

## Stage 4 — the friendly campaign (not "a friendly")

This stage is not a courtesy the pair extends to itself — it is the book's own recommendation.
Ch. 9.2.1: warm-up games that are not counted are *"מותרים ואף מומלצים, לצורך בדיקה וכיול לפני
המשחק הנספר"* — permitted and even recommended, for testing and calibration before the counted
game (the same permission App. E rule 52 grants; WARNINGS §7 carries the operating shape). A
"friendly" is that warm-up, played under full counted discipline — the two words name one thing.

One friendly is a smoke test. A campaign is what actually de-risks the counted series. Ours took
five series in one day and each one caught something the previous had not. Set expectations
honestly before you start: our pairing needed **seven scheduled windows** to complete its first
clean friendly (six burned on launch-time defaults — the LEAGUE-OPS ledger has the row-by-row),
and about five more settled series before both sides called the counted T. That is what "ready"
cost two teams that both passed every vector; budget for it.

**4a. Posture.** Every friendly runs uncounted: reports to the two teams' own inboxes **only**,
league fields disarmed (see 4d), `--counted` absent, config `counted = false`. If your guard is
structural (Stage 0) this is not a discipline problem.

**4b. The T-protocol** exactly as LEAGUE-OPS §1, per window. Probe your own edge with the
loopback **before** T, not during.

**4b′. The minimum ladder — what each friendly is FOR.** A campaign is not the same friendly
repeated; each rung has its own pass criterion, and you climb only on a pass:

| Rung | Goal | Pass criterion |
|---|---|---|
| F1 — smoke | one window handshakes and settles | one sub-game, both audits clean |
| F2 — full series | all six windows + both closes | 6/6 settled, one report each (to the teams only), compare ritual (4c) diffs clean |
| F3 — verification | re-prove the stack after ANY change (code, config, layout) | same as F2, on the exact bytes the counted series will run |
| F(n) — drills, optional | whatever you want observed live: a deliberate uid-mismatch refusal, a kill-and-resume, a chaos flap | the drill's own observable, on the record |

The counted T is named only from the top of the ladder: **the last friendly before counted runs
the identical committed stack, and nothing changes after it** except the arming (Stage 6). Our
counted series was byte-for-byte the previous night's F3 plus `--counted` — which is why it was
boring, and boring is the goal.

**4c. The report-compare ritual.** After every settled friendly, both teams put their result
files and the email bodies side by side and diff. This ritual — tedious the first time, ninety
seconds by the third — is where almost all of our real findings came from. What must agree, and
what may legitimately differ:

| Must be identical | May differ, and that is fine |
|---|---|
| `game_uid`, `game_id`, `groups`, `num_sub_games` | JSON key order (one side sorts keys) |
| per-sub-game: roles, result, `winner_group`, `tie`, scores, log filenames | `_schema` / `_remark` envelope prose |
| both audits `log_verified: true, tampered: false` | per-sub-game timestamps (different clocks, different start/end definitions — **provably outside the consensus scope**, since the hashes match anyway) |
| all four `github_commit` values, byte-for-byte | email subject wording |
| aggregate: `total_score`, `sub_games_won`, `ties`, `winner_group`, `series_tie` | which side's driver reported first |
| league fields `first_meeting_between_groups` and `diversity_reward_applied` — both pair-observable, both derived from the same outcome (SPEC §6.2) | `games_played_including_this` **where one side declares `null`** — a count is each team's own unverifiable claim, so an emitter that cannot know yours declares nothing rather than inventing it. Non-null claims must be compatible per group; `null` is *unclaimed*, never `0` (SPEC §6.2, which is the authority the checker's join implements) |
| **`mutual_agreement.sha256`** — the machine-checkable consensus (SPEC §6, `vectors/report_consensus.json`) | — |

If the mutual hash differs, do not negotiate prose — diff the **canonical consensus strings**
(the scope is `{game_id, aggregate, trimmed sub-game rows}` — `sort_keys`, `ensure_ascii=False`)
and the differing key names itself. Ours converged in one exchange this way; arguing about the
envelope would have taken a week.

**The exit criterion** — the convention our pairing used (two-team convention, offered as the
default; the book fixes no bar here): the friendly campaign is over when, **in both directions**,
each team's report arrives at the other and a field-by-field diff agrees on every must-match row
above — `mutual_agreement.sha256`, all scores, all league fields, `game_uid`, `links.github`,
and both `github_commit` columns — with nothing but per-peer timestamps differing. Until that
diff passes both ways, no counted game: the counted series is the pairing's one scoring shot
(App. E rule 52), and a diff you have not yet seen pass in a friendly is a diff you are gambling
it on.

**4d. League fields stay truthful in friendlies.** `games_played_including_this` unbumped,
`diversity_reward_applied` all-false, `first_meeting_between_groups` declared truthfully
(the disarmed posture — SPEC §6.2's counted derivation does not apply to a game that does
not count). A friendly
that fabricates a counted record is not a rehearsal, it is a false declaration with a rehearsal's
excuse (App. E rules 37–38 — this is the bug class both our teams found in each other's repos on
the same day, from opposite directions).

**4e. A verification friendly after *any* change.** Code change, config change, artifact-layout
change — the next friendly exists to watch that change behave under live fire. Two of ours were
purpose-built: one to validate an audit-rule fix, one to validate that declared commit hashes came
out as bare resolvable hashes (see Stage 6). ~90 seconds of wall clock per series makes this
cheap; the alternative is discovering the change's failure mode during the counted run.

**4f. Findings from our compare rituals that are now protocol, so you do not re-derive them:**

- **Step-0 has two conformant spellings.** The book-attached example set seals a slim log record
  (`type: "step_zero"` — `declaration_ref`, `group_id`, `role`, `sub_game_number`,
  `github_commit`) with the hardware spec living in the declaration artifact; the reference
  inlines the full spec in the log (`type: "system_spec"`). **Readers must accept both**; both
  satisfy book §5.5. The declaration artifact is, either way, the single home that carries **both
  teams'** hardware (yours signed by you; theirs captured from their greeting identity).
- **A landing capture your opponent never claimed is evidence, not tampering.** A cop can land on
  the thief's true cell without either side knowing (hidden information); the honest game plays
  on. A strict post-game reconstruction that treats the co-location as a mandatory capture will
  read the next honest move as tampering and zero an honest game. The reading that survived both
  teams' review: LAW captures (barrier-on-thief, fully-blocked thief) stay strict — the thief can
  self-detect those — while an unclaimed landing co-location downgrades to a recorded
  `disputed_capture` finding and the replay follows the outcome the peers actually lived.
- **Timestamps are not worth aligning.** Sub-second skew, different start/end definitions —
  outside the consensus scope by construction. Leave them.

---

## Stage 5 — the mutual repo audit (optional, and the single highest-value day we spent)

Before scheduling the counted T, each team audits the **other's** public repos against the book —
and sends a written findings list. Ours ran both directions in one day; the combined yield was
five real defects fixed before they could touch a counted game (among them the landing-capture
rule above and a rule-52 ledger that existed only in a gitignored path — committed evidence or it
is not evidence). Rules that made it work instead of igniting:

1. **Findings are numbered claims with file/line receipts**, not vibes.
2. **The audited team answers every finding**: *confirmed + fixed (with the commit)*, or
   *challenged (with receipts)*. A challenge with a file:line citation ends the thread — two of
   ours died exactly that way, one in each direction, both correctly.
3. **Anything that needs joint shape agreement** (e.g. how a technical-loss row looks in the
   result — see Stage 7) gets **agreed in chat first, implemented after**, so neither team codes
   a guess.
4. Both teams keep a written interpretation record (ADR-style) for every place the book admits
   two readings. When the readings differ, the *difference* gets documented as tolerated, which
   is cheaper than one team "winning".

---

## Stage 6 — arming the counted series

The counted series is the friendly you already ran five times, plus arming. The pre-T exchange
message:

```
COUNTED CONFIRMATION — <pairing>, T = <day HH:MM, timezone>

- constitution: unchanged from the friendlies (uid <first 8 chars>… — a no-op
  adoption; if EITHER side's file changed, say so now: config_sha256 moves)
- declared commits: cop <hash>, thief <hash>  (pushed; bare hashes)
- posture: --counted armed both halves, report to <league alias> only,
  each team sends its own report (book §9.3.3)
- retry protocol: <the Stage 7 agreement, restated in one line>
- counted_games_played we will declare: <n>  (truthful, App. E rules 37–38)
```

The checklist behind it, every line of which is a real event from our campaign:

- **Play a pushed commit, and exchange the hashes before T.** The wire cross-checks the declared
  commit against the sealed step-0 automatically (two channels that must agree), but a mismatch
  surfaced in chat costs a message; at the handshake it costs the window. Rule 53 wants the exact
  commit **in the step-zero declaration, updated every game** — it rides the sealed record, the
  declaration artifact, and the report's per-sub-game `github_commit`. *(It does NOT require a
  separate email to the lecturer — we checked the appendix text after almost inventing that duty.
  The lecturer's plain address exists for repo access; the report goes to the league alias.)*
- **Declared hashes are bare `git rev-parse HEAD` output.** No `-dirty` or other qualifiers: a
  series rewrites its own tracked artifact files mid-run, so any working-tree marker is
  structurally always-on — noise stamped onto a field whose spec is a resolvable commit id, and
  `<hash>-dirty` fails every grader's `rev-parse`. Both our teams converged here after a report
  diff; the honesty burden moves to the launch ritual: archive → commit → **push** → launch.
- **Commit change between friendlies and counted is legal — but say so.** Rule 53 explicitly
  permits changing code between games. One of our sides played the counted series on a cop commit
  that had never played a friendly (three dispositioned non-wire fixes). Fine — declared, and the
  other side got a one-line heads-up and asked one clarifying question, instead of discovering it
  from the report.
- **Email preflight before window 1** (Stage 0): a counted posture that cannot deliver refuses
  the whole run with zero games played.
- **League fields arm with the run**, not the calendar: counted arming is what bumps
  `games_played_including_this`, sets diversity, writes the one-counted-game-per-rival ledger.
  The ledger is **committed** in both role repos after the report sends — a fresh clone must be
  able to prove the pairing already played, or rule 52 is guarded by memory.
- **The lecturer can actually see your repos.** Private repos need the collaborator invite
  *accepted* — invitations expire (~7 days on GitHub). Check the collaborator list, not your
  sent-mail folder.
- **Snapshot the last friendly and empty the artifact top level** (Stage 0 layout), so the
  counted evidence lands as pure adds and the post-series commit is exactly "the counted series"
  and nothing else.

---

## Stage 7 — the counted run, and the one thing you must pre-agree

The run itself is LEAGUE-OPS §1–§4 with `--counted` on every window and the close. What is new is
the failure agreement, and it must exist **in writing before T**:

**If any window dies for technical reasons mid-series: both sides discard the whole attempt and
re-run all six from s1.** Grounds, from our own negotiation of exactly this clause:

- A full clean series takes ~90 seconds; a surgical single-window re-stitch is a hand-assembled
  recovery neither team has ever drilled, attempted for the first time on the one series that
  counts, with rule 35 zeroing both teams if the stitch shows.
- A discarded attempt **sent no report and wrote no ledger entry**, so the re-run is still the
  pairing's one counted game (rule 52). The record is the *reported* series.
- Two guardrails, both non-negotiable:
  1. **Discard only by mutual agreement, in writing** (chat suffices). A unilateral crash must
     never void a series — otherwise "my process died" is an erase button for whoever is losing.
  2. **The dead attempt's artifacts are archived on both sides, never deleted.** Logs are the
     only accepted dispute evidence.

**Technical-loss rows** (the case where one sub-game settles as a technical loss rather than the
series dying): agree the row shape before either team codes it. The shape our pairing agreed —
offered as a default: `result: "technical_loss"`, `winner_group: null`, `tie: false`, score 0/0
per the book's technical-loss line, `audit: {log_verified: false, tampered: false}`. And the
settlement guard must accept a *settled* technical-loss log as settled — a series containing one
is reportable; a series missing a log is not (WARNINGS §1 is about the second case, not the
first).

---

## Stage 8 — after the series

1. **Both sides verify before either celebrates:** every audit `Verified OK`, mutual hashes
   byte-equal, all four `github_commit` values resolve, league fields truthful
   (`games_played` bumped by exactly one, diversity DERIVED — winner of a first-meeting
   counted series → true, SPEC §6.2 — ledger written).
2. **One report per team** went to the league alias — result JSON as body + the result file as
   the attachment. §9.3.3 names the results file as the emailed report's full example; the other
   three artifact types reach the lecturer via the repos, so **commit and push everything**:
   declaration, logs, result, configs, ledger. An uncommitted artifact is invisible evidence.
3. **Run the two-directory artifact check** (`tools/check_artifacts.py <yours> <theirs>`) one
   last time on the counted bundles — the join check is the one neither team can run alone.
4. **De-arm.** Recipients back to the two teams, `counted = false`, mode back to the committed
   default. The next pairing starts at Stage 1 with a different `game_id` and cannot collide with
   this one's files — but the armed posture must not outlive the game it armed.
5. Exchange one final compare (Stage 4c). If the counted reports diff clean, the pairing is done
   and the evidence tells one story from two repos.

---

## The E2E contract — rules of engagement, in one list

Everything above, compressed to the enforceable statements. A team that holds all of these is
safe to play against; a violation of any is a finding (Stage 5 format). Book/kit anchors in
parentheses.

**Identity & derivation**
1. `game_id` = sorted pair; `game_uid` = UUID over SHA-256 of canonical flat 14-key terms +
   sorted group ids — derived by BOTH sides independently, compared in chat before window 1, and
   declared at the handshake (SPEC §4, §7.3; `vectors/game_uid.json`).
2. All hashes over canonical JSON: `sort_keys`, `ensure_ascii=False`, compact separators — except
   the settlement consensus signature, which uses the spaced form (SPEC §2, §6).
3. Every artifact filename derives from `game_id`; one `game_uid` spans all of them
   (`tools/check_artifacts.py` is the gate).

**Play**
4. Moves are always pure code; the LLM writes hint text only, ≤ 15 words, free natural language —
   never a coordinates protocol (book ch. 6; the hint may be any language and any emoji, and your
   opponent's serializer must survive that).
5. Commit-reveal on every step; nonces stay secret until the end-of-game audit; each side
   re-hashes the other's revealed records with its own serializer (SPEC §3).
6. Sub-game N launches only after N−1's log exists; the driver owning sub-game 6 closes.
7. Token counts are truthful, including zero — zero-token play is book-sanctioned (§6.1).

**Reporting**
8. A series that did not fully settle sends **nothing** (WARNINGS §1). A settled technical-loss
   sub-game is settled (Stage 7 row shape) — a missing one is not.
9. Each team sends exactly ONE report per counted series, to the league alias, result file
   attached — and nothing, ever, to any lecturer address outside a doubly-armed counted run
   (WARNINGS §3; book §9.3.3).
10. League fields arm with the counted run only; friendlies never bump counts or claim rewards
    (App. E rules 37–38).
11. The commit id that played is in the sealed step-0, the declaration, and the report — bare,
    pushed, resolvable (App. E rule 53). No side-channel duty exists.
12. One counted series per pairing, guarded by committed evidence, not memory (App. E rule 52).

**Failure**
13. Discard-and-rerun by mutual written agreement only; dead attempts archived, never deleted
    (Stage 7).

---

## The connection contract — how a peer actually reaches us (or you)

The transport surface, compressed from LEAGUE-OPS §2/§4 and SPEC App. D — this is the "how do I
dial them" page for a team meeting this pairing (or any conformant one):

| Item | Contract |
|---|---|
| Endpoint | `https://<host>/mcp` — MCP streamable HTTP. The path is part of the address; a bare hostname is not an endpoint |
| Ready state | `406` to a browser-shaped GET. **Poll for 406, not 200** |
| Not ready | `502` = edge up, no peer behind it (normal before T; permanent if the tunnel has no ingress — from outside you cannot tell, which is why the loopback gate exists) |
| Broken | `421` = host-header guard; fix at the tunnel (`httpHostHeader` / `--host-header=rewrite`), no code change. `530`/refused = DNS or no tunnel process |
| Topology | Declared in the Stage 1 message: one address for the series, or role-split (the address you dial changes with their role each window). Never guess — refuse ambiguity loudly |
| Per-window readiness | Under role-split, only the FIRST counterpart must be ready at T; later windows' edges are judged by their own handshake budget (LEAGUE-OPS §4) |
| Pre-T proof | Loopback through your OWN edge (`tools/netcheck.py --loopback`), finished BEFORE T so nothing but a real peer answers on the series path |
| Handshake | Greeting carries the flat signed terms + nonce + signature, identity block, locked-model hashes, `sub_game_number`/`role` (+ optionally the derived `game_uid`) — see `docs/cross-team-frame.json` for a real inbound one |
| Turn order | **Thief moves first each sub-game** (reference behaviour). The wire_shape lock does not cover this, so a disagreement survives a perfect handshake and then deadlocks both sides into mutual timeouts — state it in the Stage 1 message, never assume it |
| Refusals | Terms-absent ≠ terms-differing ≠ bystander-window — three different faults, three different fixes; name which (LEAGUE-OPS §6) |

**A worked, checkable example of the four ARTIFACT kinds** — a full six-sub-game series in the
counted shape this playbook's campaign played, generated, replayable, and verifiable with both
of the kit's gates — lives at
[`examples/pairing-artifacts/`](../examples/pairing-artifacts/README.md). Its README names what
it does *not* cover (no technical-loss row, no series tie, no second team's copy, so nothing to
join); for those, and for the wire frames rather than the artifacts, run the sparring peer and
read [`EVIDENCE.md`](EVIDENCE.md):

```bash
python examples/gen_pairing_artifacts.py
python tools/check_artifacts.py examples/pairing-artifacts
```

---

## Appendix — what may legitimately differ between two conformant teams

Collected so the first diff against a new opponent does not read as a fault list:

| Surface | Tolerated divergence |
|---|---|
| step-0 record | `step_zero` (slim + declaration_ref) vs `system_spec` (inline hardware) |
| hardware home | declaration artifact (both teams' specs) vs additionally inline in own log |
| result envelope | `_schema`/`_remark` prose, key ordering |
| timestamps | clock skew, start/end definitions, precision |
| email | subject wording; which driver inside a team sends |
| series driver | one process for all six vs role-split per-window binding (LEAGUE-OPS §4) |
| aggregation copies | each team emits its own result file; content must agree, envelope may not |

Everything **outside** this table that differs between two reports is a finding. Raise it the
Stage 5 way: numbered, with receipts.

---

*Contributed from the anrbj666 side of the anrbj666 ↔ imreeyal pairing (Alon Engel, Renat
Karimov), 2026-08-04 — the morning after the counted series it describes. Nothing in this page
can send mail; the posture it prescribes is the reason.*
