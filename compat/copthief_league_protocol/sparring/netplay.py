"""Playing a real opponent over MCP — our side only.

``series.py`` drives both sides for self-play. Against a real peer we drive exactly one, which
changes the shape in ways worth naming, because each one cost a real team a window:

* **We wait, bounded by our own budget.** A silent opponent is classified by rule (App. E) and
  never by self-termination — so the deadline that ends a sub-game is ours, and the transport's
  give-up must outlast it (``deadlines.Budgets``).
* **The handshake runs per sub-game**, and a greeting that fails the pairing check is refused *on
  the record* rather than accepted. On a role-split wire the opponent's other window can push at
  our port carrying identical signed terms; it belongs to a different game.
* **A settled peer stops accepting.** Between settlement and the next sub-game the opponent's next
  peer greets us; swallowing that greeting into a queue nobody drains makes them burn their whole
  connect budget on a message we acknowledged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sparring import KIT_REPO_URL, kitref
from sparring.artifacts import ArtifactSet, assert_uncounted_group
from sparring.config import SparConfig
from sparring.deadlines import MonotonicClock, poll_until
from sparring.identity import locks
from sparring.negotiate import Refused, our_greeting, verify_peer
from sparring.policies import REGISTRY
from sparring.preflight import assert_sparring_ready
from sparring.rules.outcome import (TIE_SCORE, Outcome, Role, is_tie_row, role_for, score_for,
                                    settled_outcome)
from sparring.state import PeerState
from sparring.turnloop import (Equivocation, IllegalMove, IllegalTransition, ProtocolViolation,
                               SubGamePeer)


class NetworkTransport:
    """Sends through an MCP client; receives from the server's inboxes."""

    def __init__(self, client, inboxes) -> None:
        self.client = client
        self.inboxes = inboxes

    def send_turn(self, message: dict) -> dict:
        return self.client.receive_turn(message)

    def send_agreement(self, message: dict) -> dict:
        return self.client.negotiate(message)

    def send_audit(self, payload: dict) -> dict:
        return self.client.submit_audit(payload)

    def send_control(self, message: dict) -> dict:
        return self.client.receive_control(message)

    def poll_turn(self):
        return self.inboxes.turns.popleft() if self.inboxes.turns else None

    def poll_agreement(self):
        return self.inboxes.agreements.popleft() if self.inboxes.agreements else None

    def poll_audit(self):
        return self.inboxes.audits.popleft() if self.inboxes.audits else None


@dataclass
class NetResult:
    game_id: str = ""
    game_uid: str = ""
    # Per-sub-game OUTCOME list — not the rule-52 ledger (WARNINGS section 5a).
    ledger: list[dict] = field(default_factory=list)
    settled: bool = True
    artifacts: list[Path] = field(default_factory=list)
    note: str = ""


def handshake(cfg: SparConfig, transport, role: Role, n: int, lock_hashes,
              budget: float, poll: float, clock, opponent_group: str | None = None):
    """Exchange greetings for one sub-game. Refuses a bystander on the record and keeps waiting."""
    mine = our_greeting(cfg, role.value, n, f"{n:032x}", lock_hashes, opponent_group)
    transport.send_agreement(mine.to_wire())

    deadline = clock.now() + budget
    last: Refused | None = None
    while clock.now() < deadline:
        raw = transport.poll_agreement()
        if raw is None:
            clock.sleep(poll)
            continue
        try:
            return verify_peer(cfg, mine, raw)
        except Refused as exc:
            # A bystander's agreement carries identical signed terms and fails only the pairing
            # check — it belongs to a different game. Say so and keep waiting for our counterpart,
            # bounded by the same budget. Terms drift and bad signatures still raise at once.
            last = exc
            print(f"  refused a greeting: {exc}")
            if exc.code not in ("SPAR-N06", "SPAR-N07"):
                raise
    raise Refused("SPAR-N09",
                  "handshake budget exhausted; our counterpart never arrived"
                  + (f" (last refusal {last.code})" if last else ""))


def play_series(cfg: SparConfig, client, inboxes, artifacts_dir: Path,
                sub_games: int = 6) -> NetResult:
    """Play our side of a whole series against a real opponent."""
    assert_uncounted_group(cfg.group_id)
    report = assert_sparring_ready(cfg)
    transport = NetworkTransport(client, inboxes)
    budgets = cfg.budgets
    clock = MonotonicClock()
    natural = Role(cfg.natural_role)
    lock_hashes = locks(cfg.scent_model)
    result = NetResult()
    artifacts: ArtifactSet | None = None

    known_opponent: str | None = None
    for n in range(1, sub_games + 1):
        role = role_for(natural, n)
        print(f"\n  sub-game {n}: we are {role.value}")
        try:
            # From sub-game 2 onward the opponent is known, so the greeting declares the derived
            # game_uid (SPEC section 7.3). Sub-game 1 declares none — omission never refuses.
            agreed = handshake(cfg, transport, role, n, lock_hashes,
                               budgets.turn_timeout, budgets.poll_interval, clock,
                               opponent_group=known_opponent)
        except Refused as exc:
            print(f"  {exc}")
            result.settled = False
            result.note = str(exc)
            break

        if known_opponent is not None and agreed.opponent_group != known_opponent:
            # One series, one opponent. Identical signed terms make a third team's greeting
            # PASS the pairing and uid checks (both derive from terms + group ids they supply),
            # so without this pin its sub-games would be aggregated into the first opponent's
            # artifact set (anrbj666's E12).
            result.settled = False
            result.note = (f"sub-game {n}: a DIFFERENT group ({agreed.opponent_group!r}) "
                           f"answered a series opened with {known_opponent!r} — refusing to "
                           f"mix two opponents into one artifact set")
            print(f"  {result.note}")
            break
        known_opponent = agreed.opponent_group
        if artifacts is None:
            result.game_id, result.game_uid = agreed.game_id, agreed.game_uid
            artifacts = ArtifactSet(artifacts_dir, agreed.game_id, agreed.game_uid,
                                    report.mail_scan_sha256)
            result.artifacts.append(artifacts.declaration(
                [{"group_id": cfg.group_id, "group_name": cfg.group_name,
                  "llm_model": "template", "members": [],
                  "repos": {"cop": KIT_REPO_URL, "thief": KIT_REPO_URL}, "mcp_servers": {}},
                 {"group_id": agreed.opponent_group, "group_name": "", "llm_model": "",
                  "members": [], "repos": {}, "mcp_servers": {}}], sub_games))

        peer = SubGamePeer(cfg=cfg, role=role, sub_game_number=n,
                           policy=REGISTRY[cfg.policy][role.value](), transport=transport,
                           clock=clock, budgets=budgets, seed=cfg.seed)
        peer.seal_step_zero(cfg.group_name)
        outcome = _play_one(peer, role, cfg, budgets, clock)

        peer.send_audit(outcome.value)
        audit = poll_until(peer.verify_audit_if_ready, budgets.turn_timeout,
                           budgets.poll_interval, clock)
        audit_present = bool(audit and not audit.skipped)
        audit_passed = bool(audit_present and audit.passed)
        # ONE settlement rule, shared with self-play (rules/outcome.settled_outcome): a failed
        # audit settles as tamper_forfeit rather than refusing the series, a classified zeroed
        # sub-game settles without an audit, and only an unverifiable PLAYED game unsettles.
        outcome, row_settled = settled_outcome(outcome, audit_present, audit_passed)
        result.settled = result.settled and row_settled
        print(f"  settled: {outcome.value} after {peer.step} steps; "
              f"opponent audit {'Verified OK' if audit_passed else 'NOT verified'}")

        result.artifacts.append(artifacts.config(n, cfg.terms()))
        result.artifacts.append(artifacts.log(n, {
            "sub_game_number": n, "group_id": cfg.group_id, "role": role.value,
            "result": outcome.value, "steps": peer.step,
            "audit": audit.to_wire() if audit else {},
        }, peer.records, {"opponent_group_id": agreed.opponent_group,
                          "sha256": kitref.canonical_hash({"sub_game": n,
                                                           "result": outcome.value}),
                          "confirmed": audit_passed}))
        result.ledger.append({"sub_game_number": n, "role": role.value,
                              "outcome": outcome.value, "steps": peer.step,
                              "score": score_for(outcome, role), "audit_ok": audit_passed,
                              "tampered": bool(audit_present and not audit_passed)})

        # Drain anything the opponent's NEXT peer pushed while we were settling: it belongs to
        # the next sub-game's handshake, not this one.
        inboxes.turns.clear()

    # The result artifact is written only when every sub-game settled. That is the settlement
    # guard from docs/WARNINGS.md §1: a report that quietly drops a game is precisely what App. E
    # rule 35 punishes — on BOTH teams. Nothing is owed for a sparring run, which is exactly why
    # it costs nothing to keep the habit here.
    if artifacts is not None and result.settled and len(result.ledger) == sub_games:
        ours, theirs = cfg.group_id, result.ledger and agreed.opponent_group
        # Both columns are DERIVED from each settled outcome (score_for is role-symmetric), so
        # even this one-sided view carries a full scoring table — an earlier revision emitted
        # our column only, with `series_tie` hardcoded false, which meant the tie path of the
        # result shape was never exercised anywhere in the kit (dogfood finding 5).
        rows = []
        totals = {ours: 0, theirs: 0}
        won = {ours: 0, theirs: 0}
        ties = 0
        for row in result.ledger:
            outcome, role = Outcome(row["outcome"]), Role(row["role"])
            score_ours, score_theirs = row["score"], score_for(outcome, role.other)
            totals[ours] += score_ours
            totals[theirs] += score_theirs
            row_tie = is_tie_row(outcome, score_ours, score_theirs)
            if score_ours > score_theirs:
                won[ours] += 1
            elif score_theirs > score_ours:
                won[theirs] += 1
            elif row_tie:
                ties += 1
            rows.append({
                "sub_game_number": row["sub_game_number"],
                "roles": {ours: row["role"], theirs: role.other.value},
                "result": row["outcome"],
                "winner_group": (ours if score_ours > score_theirs
                                 else (theirs if score_theirs > score_ours else None)),
                "tie": row_tie,
                "score": {ours: score_ours, theirs: score_theirs},
                "tokens": {ours: 0, theirs: 0},
                # tampered means an audit that RAN and failed — a zeroed row that settled
                # without an audit is log_verified false, tampered false (the pair-agreed
                # technical-loss shape, PAIRING-PLAYBOOK stage 7).
                "audit": {"log_verified": row["audit_ok"],
                          "tampered": row.get("tampered", False)},
            })
        series_tie = totals[ours] == totals[theirs]
        # Tie award INTO the totals — the reference's aggregate behaviour (see series.py; N1).
        awarded = ({g: v + TIE_SCORE for g, v in totals.items()} if series_tie else totals)
        result.artifacts.append(artifacts.result(
            [{"group_id": ours, "group_name": cfg.group_name,
              "repos": {"cop": KIT_REPO_URL, "thief": KIT_REPO_URL}},
             {"group_id": theirs, "group_name": ""}],
            rows,
            {"total_score": awarded,
             "sub_games_won": won,
             "ties": ties,
             "winner_group": None if series_tie else max(totals, key=lambda k: totals[k]),
             "series_tie": series_tie,
             "tie_score_each": TIE_SCORE if series_tie else None,
             "tokens_total_series": {ours: 0, theirs: 0},
             "_remark": "one side's view, both columns derived from the settled outcomes. A "
                        "counted series settles the result WITH the opponent before either "
                        "reports; this is a practice run and reports nothing."},
            unclaimed_counts=frozenset({theirs})))
    elif artifacts is not None:
        print("\n  no result artifact: a sub-game did not settle. A report that quietly drops a "
              "game\n  is what rule 35 punishes, on both teams — so the guard refuses the whole "
              "series.")

    return result


def _play_one(peer: SubGamePeer, role: Role, cfg: SparConfig, budgets, clock) -> Outcome:
    """One sub-game against a live opponent. THE THIEF MOVES FIRST.

    That order is the reference implementation's, observed live against it (its runtime takes
    the thief's turn before entering the receive loop) — and this peer declares
    ``wire_shape: reference-v3``, so it plays what it names. This line shipped police-first
    until the 2026-08-04 dogfood run, where a reference-conformant opponent and this peer each
    waited for the other after a *fully successful* handshake: terms equal, signature verified,
    all three locks matched — then both timed out and each blamed the other, which is the
    contradictory-reports shape App. E rule 35 zeroes. The wire_shape lock does not cover turn
    order (`bookletter-v3` negotiates it explicitly; `reference-v3` inherits the reference's
    behaviour), so a matching lock actively *confirmed* agreement while hiding the one
    disagreement that mattered — hence the diagnosis below rather than a silent timeout.
    """
    our_move_first = role is Role.THIEF
    saw_their_turn = False
    try:
        for _ in range(cfg.max_steps * 2):
            if our_move_first:
                own = _take_own_turn(peer, role)
                if own is not None:
                    return own

            # ONE deadline per EXPECTED message (LEAGUE-OPS §5) — an absorbed duplicate or a
            # buffered-ahead arrival proves the opponent is alive but does not discharge what
            # it owes, so it renews nothing and, critically, never lets us move again on stale
            # state. The first revision was discharged by ANY raw message: a redelivery could
            # make this peer take two consecutive own turns (anrbj666's B2 — the exact failure
            # `series._await_step` was built to prevent, absent from the driver that meets
            # strangers).
            applied = _await_applied(peer, budgets, clock)
            if applied is None:
                if not saw_their_turn:
                    print("  no turn was EVER exchanged after a successful handshake. That "
                          "pattern is almost never a dead peer —\n  it is a TURN-ORDER "
                          "disagreement: reference-v3 plays thief-first (the reference's own "
                          "behaviour),\n  and a peer that plays police-first will wait here "
                          "forever while we do the same. The wire_shape lock\n  does not cover "
                          "turn order — state it with your opponent (PAIRING-PLAYBOOK stage 1).")
                return Outcome.TIMEOUT
            saw_their_turn = True
            verdict = None
            for msg in applied:
                answer = peer.answer(msg)
                verdict = verdict or peer.adjudicate(msg, answer)
            if verdict is not None:
                # Deliver what we owe before we stop talking. The opponent cannot see the board;
                # if we walk away holding the answer, it waits out its budget and settles a game
                # it won as a timeout.
                final = peer.terminal_message()
                if final is not None:
                    peer.transport.send_turn(final.to_wire())
                return verdict

            if not our_move_first:
                own = _take_own_turn(peer, role)
                if own is not None:
                    return own
    except (Equivocation, ProtocolViolation, IllegalMove, IllegalTransition) as exc:
        # An inbound message that breaks the rules is CLASSIFIED, exactly as self-play
        # classifies it — the first revision let it unwind the whole series, so against a live
        # opponent an equivocation was a crash instead of a refusal (anrbj666's B1).
        print(f"  technical loss — {type(exc).__name__}: {exc}")
        return peer.fail(str(exc))
    return Outcome.SURVIVAL


def _await_applied(peer: SubGamePeer, budgets, clock):
    """Wait for the message we are OWED — not merely for traffic. None means our deadline ran
    out; tolerated traffic (duplicates, buffered-ahead arrivals) never renews it."""
    peer.deadline.expect(f"turn {peer.inbox.next_step}", budgets.turn_timeout)
    while True:
        raw = peer.transport.poll_turn()
        if raw is not None:
            applied = peer.receive(raw)
            if applied:
                peer.deadline.clear()
                return applied
        if peer.deadline.expired():
            return None
        clock.sleep(budgets.poll_interval)


def _take_own_turn(peer: SubGamePeer, role: Role) -> Outcome | None:
    """Take and send our half-turn; return an outcome if OUR OWN move ended the game.

    The self-checks are the THIEF's, and they must follow the thief's move wherever it sits in
    the turn: self-capture (walking into a barrier fold) concedes with a terminal message, and
    reaching the survival threshold returns with the claim that already rode out on the message
    just sent. The first thief-first cut of `_play_one` left these checks in the second-mover
    branch — where the thief no longer was — so a surviving thief never returned, kept polling
    for a turn that would never come, and timed out a sub-game it had won; its opponent's audit
    poll then starved too. CI's two-container series caught it within the hour.
    """
    if peer.step >= peer.cfg.max_steps:
        # The ceiling binds BOTH roles. The thief's ceiling produces a survival claim before
        # this line can be reached; the cop's did not exist at all — a cop facing a thief that
        # never claimed sealed steps 36..70 past the signed max_steps and then settled the
        # sub-game as SURVIVAL unconditionally (anrbj666's B3). Past the ceiling we stop
        # sealing and only wait: for the claim, or for our own deadline to classify a silent
        # opponent by rule.
        return None
    message = peer.take_turn()
    peer.transport.send_turn(message.to_wire())
    peer.machine.to(PeerState.VERIFYING)
    peer.machine.to(PeerState.WAITING_FOR_OPPONENT)
    if role is Role.THIEF:
        own = peer.engine.self_captured()
        if own is not None:
            final = peer.terminal_message()
            if final is not None:
                peer.transport.send_turn(final.to_wire())
            return own
        if peer.engine.survived():
            # The survival claim already rode out on the message just sent.
            return Outcome.SURVIVAL
    return None
