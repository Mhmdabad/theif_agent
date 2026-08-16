"""netplay's live-opponent paths, held to the same contract self-play implements.

Regression cases for anrbj666's B1/B2/B3 (2026-08-04 audit): the driver that meets strangers
crashed on inbound violations, moved on stale state under redelivery, and sealed past the step
ceiling. Each test drives `_play_one` with a scripted transport — no network, no fastmcp.
"""

import unittest

from sparring import kitref
from sparring.config import SparConfig
from sparring.deadlines import Budgets, FakeClock
from sparring.netplay import _play_one
from sparring.policies import REGISTRY
from sparring.proto.messages import TurnMessage
from sparring.rules.outcome import Outcome, Role
from sparring.turnloop import SubGamePeer


class ScriptedTransport:
    """Feeds a fixed inbound script; records everything sent."""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.sent: list[dict] = []

    def send_turn(self, message: dict) -> dict:
        self.sent.append(message)
        return {"ok": True}

    def poll_turn(self):
        return self.script.pop(0) if self.script else None


def turn(step: int, sender: str = "police", **over) -> dict:
    payload = {"step": step, "who": sender}
    nonce = f"{step:032x}"
    base = TurnMessage(step=step, sender=sender, commit=kitref.commit(payload, nonce),
                      hint="", smell_grid={}).to_wire()
    base.update(over)
    return base


def make_peer(role: Role, cfg: SparConfig, transport, clock) -> SubGamePeer:
    return SubGamePeer(cfg=cfg, role=role, sub_game_number=1,
                       policy=REGISTRY[cfg.policy][role.value](), transport=transport,
                       clock=clock, budgets=cfg.budgets, seed=1234)


class TestInboundViolationsAreClassified(unittest.TestCase):
    def test_an_equivocation_settles_as_technical_loss_instead_of_crashing(self):
        # B1: same step, two different commits — tampering evidence. The first revision let
        # the exception unwind the whole series; a live opponent's fault became our crash.
        cfg = SparConfig(budgets=Budgets(turn_timeout=5.0, poll_interval=0.5, connect_timeout=2.0))
        first = turn(1)
        second = turn(1)
        second["commit"] = "0" * 64          # different commit for the played step
        transport = ScriptedTransport([first, second])
        clock = FakeClock()
        peer = make_peer(Role.THIEF, cfg, transport, clock)
        outcome = _play_one(peer, Role.THIEF, cfg, cfg.budgets, clock)
        self.assertIs(outcome, Outcome.TECHNICAL_LOSS)

    def test_a_thief_sent_barrier_settles_as_technical_loss(self):
        # A3's live half, reaching through netplay: only the cop places barriers.
        cfg = SparConfig(budgets=Budgets(turn_timeout=5.0, poll_interval=0.5, connect_timeout=2.0))
        bad = turn(1, sender="thief", barrier_placed=[0, 0])
        transport = ScriptedTransport([bad])
        clock = FakeClock()
        peer = make_peer(Role.POLICE, cfg, transport, clock)
        outcome = _play_one(peer, Role.POLICE, cfg, cfg.budgets, clock)
        self.assertIs(outcome, Outcome.TECHNICAL_LOSS)


class TestExpectedStepWait(unittest.TestCase):
    def test_a_redelivery_does_not_provoke_a_second_own_turn(self):
        # B2: the cop's poll used to be discharged by ANY raw message. A duplicate of the
        # thief's step-1 message (absorbed, nothing applied) let the cop fall through and take
        # a second consecutive turn on stale state. Now the wait is for the message we are
        # OWED: after one applied message the cop has taken exactly one own turn, and the
        # duplicate has renewed nothing.
        cfg = SparConfig(budgets=Budgets(turn_timeout=5.0, poll_interval=0.5, connect_timeout=2.0))
        original = turn(1)
        duplicate = dict(original)
        transport = ScriptedTransport([original, duplicate])
        clock = FakeClock()
        peer = make_peer(Role.POLICE, cfg, transport, clock)
        outcome = _play_one(peer, Role.POLICE, cfg, cfg.budgets, clock)
        # The script dries up, so the sub-game times out — the point is what happened first:
        self.assertIs(outcome, Outcome.TIMEOUT)
        own_steps = [m["step"] for m in transport.sent]
        self.assertEqual(own_steps, sorted(set(own_steps)),
                         "an own step was sealed twice — moved on stale state")
        self.assertEqual(peer.inbox.absorbed, 1, "the duplicate should be absorbed, once")

    def test_junk_never_renews_the_deadline(self):
        # A flood of duplicates must not hold us past our own budget (LEAGUE-OPS §5).
        cfg = SparConfig(budgets=Budgets(turn_timeout=3.0, poll_interval=0.5, connect_timeout=2.0))
        original = turn(1)
        flood = [dict(original) for _ in range(50)]
        transport = ScriptedTransport([original] + flood)
        clock = FakeClock()
        peer = make_peer(Role.POLICE, cfg, transport, clock)
        outcome = _play_one(peer, Role.POLICE, cfg, cfg.budgets, clock)
        self.assertIs(outcome, Outcome.TIMEOUT)
        self.assertLessEqual(clock.now(), 3.0 * 3,
                             "the flood held the deadline open far past the budget")


class TestStepCeiling(unittest.TestCase):
    def test_the_cop_never_seals_past_max_steps(self):
        # B3: a thief that never claims survival used to draw the cop into sealing steps
        # 36..70. The ceiling now binds both roles; the cop stops sealing and waits.
        cfg = SparConfig(max_steps=3, survival_threshold=3,
                         budgets=Budgets(turn_timeout=5.0, poll_interval=0.5, connect_timeout=2.0))
        # A thief that answers every step but never sends win_claim:
        script = [turn(s, sender="thief") for s in range(1, 10)]
        transport = ScriptedTransport(script)
        clock = FakeClock()
        peer = make_peer(Role.POLICE, cfg, transport, clock)
        _play_one(peer, Role.POLICE, cfg, cfg.budgets, clock)
        self.assertLessEqual(peer.step, cfg.max_steps,
                             f"sealed {peer.step} steps against a ceiling of {cfg.max_steps}")


class TestRule46Concession(unittest.TestCase):
    """Issue #37: a rule-46/47 ending is a fact only the thief can see, so the thief must SAY
    it — and because saying it is worth five points over the zeroed row it replaces, the cop
    must CORROBORATE it (imreeyal's refinement). Unit pins for both halves of that bargain,
    deterministic and network-free — the live shape forked at seeds 4242/777, sub-game 3."""

    def _cfg(self) -> SparConfig:
        return SparConfig(budgets=Budgets(turn_timeout=5.0, poll_interval=0.5,
                                          connect_timeout=2.0))

    def test_a_walled_in_thief_concedes_in_its_terminal_message(self):
        # The send path that was missing: before this, a self-captured thief with no pending
        # answer returned None here and the cop burned its budget into a timeout.
        cfg = self._cfg()
        peer = make_peer(Role.THIEF, cfg, ScriptedTransport([]), FakeClock())
        peer.engine.observe_barrier(list(peer.engine.position))     # rule 46: walled in place
        self.assertIs(peer.engine.self_captured(), Outcome.CAPTURE)
        final = peer.terminal_message()
        self.assertIsNotNone(final, "a self-captured thief must still say so")
        self.assertEqual(final.claim_response,
                         {"claim": list(peer.engine.position), "caught": True},
                         "the concession names the thief's OWN final cell, caught=true")

    def test_the_cop_settles_a_concession_and_classifies_it(self):
        # The fork in miniature: the thief's concession reaches the cop as a caught=true that
        # answers no claim of ours — it must settle CAPTURE (not run to timeout) and be held
        # for the audit, because it is a concession, not an answer.
        cfg = self._cfg()
        cop = make_peer(Role.POLICE, cfg, ScriptedTransport([]), FakeClock())
        cop.last_claim = [0, 0]
        concession = turn(12, sender="thief",
                          claim_response={"claim": [4, 5], "caught": True})
        outcome = cop.adjudicate(TurnMessage.from_wire(concession), None)
        self.assertIs(outcome, Outcome.CAPTURE)
        self.assertEqual(cop.conceded, {"claim": [4, 5], "caught": True})

    def test_an_answer_to_our_own_claim_is_not_held_as_a_concession(self):
        # The reference behaviour, unchanged: caught=true echoing OUR claimed cell is the
        # thief's obligatory answer, and the audit treats it exactly as before.
        cfg = self._cfg()
        cop = make_peer(Role.POLICE, cfg, ScriptedTransport([]), FakeClock())
        cop.last_claim = [4, 5]
        answer = turn(12, sender="thief",
                      claim_response={"claim": [4, 5], "caught": True})
        outcome = cop.adjudicate(TurnMessage.from_wire(answer), None)
        self.assertIs(outcome, Outcome.CAPTURE)
        self.assertIsNone(cop.conceded)
        self.assertEqual(cop.answered_at, [4, 5],
                         "the answer path is held for its OWN audit half (F-2)")

    @staticmethod
    def _sealed_trail(cells: list[list[int]], with_position: bool = True) -> list[dict]:
        # Honest records: the sealed move token matches the delta the positions show, or
        # K-1's token-vs-trail cross-check (rightly) complains about the fixture itself.
        deltas = {(-1, 0): "MOVE:N", (1, 0): "MOVE:S", (0, 1): "MOVE:E", (0, -1): "MOVE:W",
                  (0, 0): "STAY"}
        records = []
        prev = None
        for step, pos in enumerate(cells, start=1):
            move = deltas[(pos[0] - prev[0], pos[1] - prev[1])] if prev else "STAY"
            payload = {"step": step, "role": "thief", "sub_game": 1,
                       "move": move, "intent": "truth", "hint": "", "verdict": "settled",
                       "state": f"grid=7x7;self={pos};barriers=[]"}
            if with_position:
                payload["position"] = pos
            nonce = f"{step:032x}"
            records.append({"payload": payload, "nonce": nonce,
                            "commit": kitref.commit(payload, nonce)})
            prev = pos
        return records

    def test_a_true_concession_is_corroborated_by_the_cop_s_own_barrier_record(self):
        from sparring.audit import audit_records
        records = self._sealed_trail([[4, 6], [4, 5]])          # trail ends ON our barrier
        result = audit_records(records, board_size=7,
                               concession={"claim": [4, 5], "caught": True},
                               own_barriers=[[4, 5]])
        self.assertTrue(result.passed, result.detail)

    def test_a_false_concession_fails_the_audit_and_names_why(self):
        # The five-point lie: caught=true over a cell our barriers never touched. The audit —
        # not trust — is what stands between it and a clean-looking 20.
        from sparring.audit import audit_records
        records = self._sealed_trail([[2, 3], [2, 2]])          # honest trail, no capture there
        result = audit_records(records, board_size=7,
                               concession={"claim": [2, 2], "caught": True},
                               own_barriers=[[4, 5]])
        self.assertFalse(result.passed)
        self.assertIn("CONCESSION", result.detail)

    def test_a_concession_naming_a_cell_the_trail_never_reached_fails(self):
        from sparring.audit import audit_records
        records = self._sealed_trail([[4, 6], [4, 5]])
        result = audit_records(records, board_size=7,
                               concession={"claim": [6, 6], "caught": True},
                               own_barriers=[[5, 6], [6, 5]])   # (6,6) IS boxed in — but the
        self.assertFalse(result.passed)                          # revealed trail ends at (4,5)
        self.assertIn("CONCESSION", result.detail)

    def test_an_honest_concession_from_a_position_less_schema_is_not_tampering(self):
        # imreeyal's F-1 (severe): a conforming peer whose reveal seals action+state and no
        # `position` key failed corroboration on EVERY honest rule-46/47 ending — our own
        # payload schema applied as an interop constraint, the K-1 mistake in a second home.
        # The trail half degrades to a note; the barrier half still runs and still passes.
        from sparring.audit import audit_records
        records = self._sealed_trail([[4, 6], [4, 5]], with_position=False)
        result = audit_records(records, board_size=7,
                               concession={"claim": [4, 5], "caught": True},
                               own_barriers=[[4, 5]])
        self.assertTrue(result.passed, result.detail)

    def test_a_false_concession_from_a_position_less_schema_still_fails_the_barrier_half(self):
        # Degrading is not disarming: with no trail to check, the barrier half alone still
        # refuses a concession our own record never captured.
        from sparring.audit import audit_records
        records = self._sealed_trail([[2, 3], [2, 2]], with_position=False)
        result = audit_records(records, board_size=7,
                               concession={"claim": [2, 2], "caught": True},
                               own_barriers=[[4, 5]])
        self.assertFalse(result.passed)
        self.assertIn("CONCESSION", result.detail)

    def test_a_false_answer_echoing_our_claim_fails_the_audit(self):
        # imreeyal's F-2: echoing the cop's own claimed cell routed the lie around the
        # corroboration as an "answer" — and a false answer pays the thief 5 AND the cop 20,
        # so both peers profit and neither can be left to catch it. The revealed trail must
        # end at the cell the answer says the capture happened on.
        from sparring.audit import audit_records
        records = self._sealed_trail([[2, 3], [2, 2]])           # trail never near [4, 6]
        result = audit_records(records, board_size=7, answered_at=[4, 6])
        self.assertFalse(result.passed)
        self.assertIn("ANSWER", result.detail)

    def test_an_honest_answer_still_verifies(self):
        from sparring.audit import audit_records
        records = self._sealed_trail([[4, 5], [4, 6]])           # trail ends where claimed
        result = audit_records(records, board_size=7, answered_at=[4, 6])
        self.assertTrue(result.passed, result.detail)

    def test_an_answer_from_a_position_less_schema_degrades_instead_of_accusing(self):
        from sparring.audit import audit_records
        records = self._sealed_trail([[4, 5], [4, 6]], with_position=False)
        result = audit_records(records, board_size=7, answered_at=[4, 6])
        self.assertTrue(result.passed, result.detail)


if __name__ == "__main__":
    unittest.main()
