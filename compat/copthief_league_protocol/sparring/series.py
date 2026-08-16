"""A whole series: six sub-games, roles alternating, one game_uid, four artifacts.

Self-play drives both sides in one process. That is what makes the flagship CI test possible with
no dependencies, and it is also the honest shape of a practice tool: a team pointing its own peer
at this one gets exactly the same code path with a real transport underneath.

Three structural rules, all of which cost a real team a window at some point:

* **Fresh runtime per sub-game.** New engine, new trail, new inbox, new nonce stream, new
  handshake. The transport survives; nothing else does.
* **Every sub-game is played out even after one fails.** A series is six games; quitting early
  leaves the opponent playing a match we had abandoned.
* **A series that did not fully settle produces no result artifact.** That is the settlement
  guard from ``docs/WARNINGS.md`` §1, and it is the one rule here that exists to protect the
  *other* team: under App. E rule 35 a report that quietly drops a game zeroes them too. A
  sparring run owes no report at all, so the guard costs nothing to obey and rehearses the shape
  a counted run needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from sparring import KIT_REPO_URL, kitref
from sparring.artifacts import ArtifactSet, assert_uncounted_group
from sparring.config import SparConfig
from sparring.deadlines import Clock, FakeClock, MonotonicClock
from sparring.identity import locks
from sparring.inbox import Equivocation, ProtocolViolation
from sparring.negotiate import Refused, our_greeting, verify_peer
from sparring.policies import REGISTRY
from sparring.preflight import assert_sparring_ready
from sparring.rules.engine import IllegalMove
from sparring.rules.outcome import (SUB_GAMES_PER_SERIES, TIE_SCORE, Outcome, Role, is_tie_row,
                                    role_for, score_for, settled_outcome)
from sparring.state import IllegalTransition, PeerState
from sparring.transport.loopback import pair
from sparring.turnloop import SubGamePeer, SubGameResult


@dataclass
class SeriesResult:
    game_id: str
    game_uid: str
    sub_games: list[dict] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    won: dict[str, int] = field(default_factory=dict)
    ties: int = 0
    winner: str | None = None
    series_tie: bool = False
    artifacts: list[Path] = field(default_factory=list)
    settled: bool = True
    # Per-sub-game OUTCOME list — not the rule-52 counted-series ledger, which a
    # practice peer deliberately does not have (WARNINGS section 5a; anrbj666's P5-8).
    ledger: list[dict] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.settled and all(
            sg["audit"]["log_verified"] for sg in self.sub_games)


def _await_step(other, mover, cfg: SparConfig, clock: Clock) -> Outcome | None:
    """Poll until the opponent's expected step has been applied, or our own deadline expires.

    One clock per expected message: the deadline is armed once, here, and nothing that arrives
    can renew it. Tolerated traffic — a redelivery, a message from a future step buffered inside
    the reorder window — proves the opponent is alive but does not discharge what it owes us, so
    the loop keeps waiting on the *original* budget. And the deadline is checked on every lap,
    including laps where something did arrive, so a flood cannot hold us past our own budget.
    """
    other.deadline.expect(f"turn {other.inbox.next_step}", cfg.budgets.turn_timeout)
    verdict: Outcome | None = None

    while True:
        raw = other.transport.poll_turn()
        if raw is not None:
            applied = other.receive(raw)
            if applied:
                # The WHOLE drained batch is answered and adjudicated. The first revision
                # returned from inside this loop after one message, so when the inbox drained
                # a buffered pair, the second message's capture claim or win claim was never
                # answered (anrbj666's B5).
                for msg in applied:
                    answer = other.answer(msg)
                    if answer is not None:
                        msg.claim_response = answer
                    verdict = verdict or other.adjudicate(msg, answer)
                other.deadline.clear()
                return verdict
            # Nothing became ready: absorbed as a duplicate, or buffered ahead of a gap. Either
            # way the opponent still owes us the step we are waiting for.
        if other.deadline.expired():
            return Outcome.TIMEOUT
        # Nothing to apply. A real sender retries on its own budget when it sees no progress;
        # `flush` is how the fault injector models that. Then let the clock move.
        flush = getattr(mover.transport, "flush", None)
        if flush is not None:
            flush()
        elif raw is None:
            return Outcome.TIMEOUT       # a plain transport with an empty inbox will never fill
        if isinstance(clock, FakeClock):
            clock.advance(cfg.budgets.poll_interval)


def _play_sub_game(cfg: SparConfig, n: int, a_role: Role, transports, clock: Clock,
                   seed: int) -> tuple[SubGameResult, SubGameResult]:
    """One sub-game, both sides, until someone can adjudicate."""
    t_a, t_b = transports
    brains = REGISTRY[cfg.policy]
    b_role = a_role.other

    a = SubGamePeer(cfg=cfg, role=a_role, sub_game_number=n,
                    policy=brains[a_role.value](), transport=t_a, clock=clock,
                    budgets=cfg.budgets, seed=seed)
    b = SubGamePeer(cfg=cfg, role=b_role, sub_game_number=n,
                    policy=brains[b_role.value](), transport=t_b, clock=clock,
                    budgets=cfg.budgets, seed=seed + 10_000)

    a.seal_step_zero(cfg.group_name)
    b.seal_step_zero(f"{cfg.group_name} (opponent)")

    # THE THIEF MOVES FIRST — the reference implementation's own order, observed live against
    # it, and what `wire_shape: reference-v3` therefore implies. Shipped police-first until the
    # 2026-08-04 dogfood run deadlocked against a reference-conformant peer (netplay._play_one
    # has the full story). Self-play must sequence the same way netplay plays, or a rehearsal
    # certifies an order no real opponent uses.
    first, second = (a, b) if a_role is Role.THIEF else (b, a)
    outcome_first = outcome_second = None
    note = ""

    try:
        for _ in range(cfg.max_steps):
            for mover, other in ((first, second), (second, first)):
                message = mover.take_turn()
                mover.transport.send_turn(message.to_wire())

                # WAIT for the expected step rather than assuming it arrived. This is the whole
                # difference between a loop that works on a calm transport and one that works.
                # A delayed message must not be skipped past: deciding on a stale observation
                # produces a different move, a different sealed record, and a different commit —
                # so two honest peers would diverge because of the *network*, which is exactly
                # what SPEC section 7.1 exists to prevent. The wait is bounded by our own turn
                # deadline, so a genuinely silent opponent is still classified by rule.
                verdict = _await_step(other, mover, cfg, clock)
                if verdict is not None:
                    outcome_first = outcome_first or verdict

                mover.machine.to(PeerState.VERIFYING)
                mover.machine.to(PeerState.WAITING_FOR_OPPONENT)
                if outcome_first is not None:
                    break
            if outcome_first is not None:
                break
    except (Equivocation, ProtocolViolation, IllegalMove, IllegalTransition) as exc:
        note = f"{type(exc).__name__}: {exc}"
        outcome_first = Outcome.TECHNICAL_LOSS

    if outcome_first is None:
        outcome_first = Outcome.SURVIVAL          # the thief lasted the whole step ceiling
    outcome_second = outcome_first

    # Both reveal, THEN both verify. Interleaving them makes whoever goes first record a skipped
    # audit against an inbox the other side has not written to yet.
    claim = outcome_first.value
    a.send_audit(claim)
    b.send_audit(claim)
    audit_a = a.verify_audit()
    audit_b = b.verify_audit()

    ra = SubGameResult(n, a_role, outcome_first, a.step, a.records, audit_a, len(b.records), note)
    rb = SubGameResult(n, b_role, outcome_second, b.step, b.records, audit_b, len(a.records), note)
    return ra, rb


def run_series(cfg: SparConfig, out_dir: Path, *, clock: Clock | None = None,
               sub_games: int | None = None, check_vectors: bool = True,
               transport_factory=pair) -> SeriesResult:
    """Play a whole series and write the artifacts.

    ``transport_factory`` exists so the test suite can hand in a fault-injecting transport and
    assert the outcome ledger is unchanged. That comparison — same result, hostile transport — is
    the strongest single statement this package makes about SPEC section 7.1.
    """
    assert_uncounted_group(cfg.group_id)
    report = assert_sparring_ready(cfg, check_vectors=check_vectors)
    clock = clock or MonotonicClock()
    count = sub_games or min(cfg.num_games, SUB_GAMES_PER_SERIES)

    ours, theirs = cfg.group_id, f"{cfg.group_id}-opponent"
    game_id = kitref.game_id(ours, theirs)
    game_uid = kitref.game_uid(cfg.terms(), ours, theirs)
    # The opponent side of a self-play run is a real config with its own group id, so both
    # verification directions see an honest (own, opponent) pair.
    cfg_b = replace(cfg, group_id=theirs)

    # The handshake runs per sub-game, exactly as it does against a real peer — and is verified
    # both ways, so a self-play run exercises the refusal paths rather than skipping them.
    lock_hashes = locks(cfg.scent_model)
    natural = Role(cfg.natural_role)

    artifacts = ArtifactSet(out_dir, game_id, game_uid, report.mail_scan_sha256)
    spar_repos = {"cop": KIT_REPO_URL, "thief": KIT_REPO_URL}
    groups = [{"group_id": ours, "group_name": cfg.group_name, "llm_model": "template",
               "members": [], "repos": spar_repos, "mcp_servers": {}},
              {"group_id": theirs, "group_name": f"{cfg.group_name} (opponent side)",
               "llm_model": "template", "members": [], "repos": spar_repos, "mcp_servers": {}}]
    written = [artifacts.declaration(groups, count)]

    result = SeriesResult(game_id=game_id, game_uid=game_uid)
    totals = {ours: 0, theirs: 0}
    won = {ours: 0, theirs: 0}

    for n in range(1, count + 1):
        a_role = role_for(natural, n)
        t_a, t_b = transport_factory(f"{ours}#{n}", f"{theirs}#{n}")

        # Self-play knows both sides a priori, so each greeting declares the derived game_uid
        # (SPEC section 7.3) and verify_peer's uid check is exercised on every handshake. The
        # opponent side is a real config with its own group id — a wire-level group_id override
        # would leave the reverse verification deriving a uid over (ours, ours), and the uid
        # declaration would then (correctly) refuse the degenerate pair.
        greeting_a = our_greeting(cfg, a_role.value, n, f"{n:032x}", lock_hashes, theirs)
        greeting_b = our_greeting(cfg_b, a_role.other.value, n, f"{n + 500:032x}", lock_hashes,
                                  ours)
        try:
            verify_peer(cfg, greeting_a, greeting_b.to_wire())
            verify_peer(cfg_b, greeting_b, greeting_a.to_wire())
        except Refused as exc:
            result.settled = False
            result.ledger.append({"sub_game_number": n, "refused": exc.code, "note": exc.message})
            continue

        ra, rb = _play_sub_game(cfg, n, a_role, (t_a, t_b), clock, cfg.seed)
        written.append(artifacts.config(n, cfg.terms()))

        for who, res in ((ours, ra), (theirs, rb)):
            summary = {"sub_game_number": n, "group_id": who, "role": res.role.value,
                       "result": res.outcome.value, "steps": res.steps,
                       "audit": res.our_audit.to_wire() if res.our_audit else {}}
            if who == ours:
                written.append(artifacts.log(n, summary, res.records, {
                    "opponent_group_id": theirs,
                    "sha256": kitref.canonical_hash({"sub_game": n, "result": res.outcome.value}),
                    "confirmed": bool(res.our_audit and res.our_audit.passed)}))

        audits_present = bool(ra.our_audit and not ra.our_audit.skipped
                              and rb.our_audit and not rb.our_audit.skipped)
        audits_passed = bool(audits_present and ra.our_audit.passed and rb.our_audit.passed)
        outcome, row_settled = settled_outcome(ra.outcome, audits_present, audits_passed)
        result.settled = result.settled and row_settled

        score_a = score_for(outcome, ra.role)
        score_b = score_for(outcome, rb.role)
        totals[ours] += score_a
        totals[theirs] += score_b
        row_tie = is_tie_row(outcome, score_a, score_b)
        if score_a > score_b:
            won[ours] += 1
        elif score_b > score_a:
            won[theirs] += 1
        elif row_tie:
            # A zeroed sub-game (timeout / technical loss / tamper forfeit) reaches neither
            # branch: 0-0 is a sanction, not a tie, and it counts for nobody.
            result.ties += 1

        result.sub_games.append({
            "sub_game_number": n,
            "roles": {ours: ra.role.value, theirs: rb.role.value},
            "result": outcome.value,
            "winner_group": ours if score_a > score_b else (theirs if score_b > score_a else None),
            "tie": row_tie,
            "score": {ours: score_a, theirs: score_b},
            "tokens": {ours: 0, theirs: 0},
            "audit": {"log_verified": audits_passed,
                      "tampered": bool(audits_present and not audits_passed)},
        })
        result.ledger.append({
            "sub_game_number": n, "role": ra.role.value, "outcome": ra.outcome.value,
            "steps": ra.steps, "score": {ours: score_a, theirs: score_b},
            "final_commit": ra.final_commit,
        })

    result.totals = totals
    result.won = won
    result.series_tie = totals[ours] == totals[theirs]
    result.winner = None if result.series_tie else max(totals, key=lambda k: totals[k])

    if not result.settled:
        # No result artifact. See the module docstring: a report that quietly drops a game is
        # what rule 35 punishes, and the habit is worth keeping even where nothing is owed.
        result.artifacts = written
        return result

    # On a series tie the App. F tie score is ADDED into each side's total — the reference's
    # own aggregate behaviour, observed live against it. A result carrying the raw sum beside
    # a separate tie field describes the same match with different numbers than a
    # reference-shaped opponent's report — the rule-35 contradiction (imreeyal's dogfood
    # verification, N1, 2026-08-04). `tie_score_each` stays as documentation of the addend.
    awarded = ({g: v + TIE_SCORE for g, v in totals.items()} if result.series_tie else totals)
    final = {
        "total_score": awarded,
        "sub_games_won": won,
        "ties": result.ties,
        "winner_group": result.winner,
        "series_tie": result.series_tie,
        "tie_score_each": TIE_SCORE if result.series_tie else None,
        "tokens_total_series": {ours: 0, theirs: 0},
    }
    written.append(artifacts.result(groups, result.sub_games, final))
    result.artifacts = written
    return result
