"""The commit-reveal loop, CLOSED — regression cases for anrbj666's findings A1-A3 and B4.

The founding probe is theirs, quoted from the 2026-08-04 audit: a wholly fabricated log — a
game that was never played, carrying diagonal moves at off-board coordinates — passed the
first revision of `audit_records`, because the only check was re-hashing each record against
the commit embedded in that same record. These tests keep every layer of the closure honest.
"""

import unittest

from sparring import kitref
from sparring.audit import audit_records
from sparring.rules.board import Board
from sparring.rules.engine import IllegalMove, SubGameEngine
from sparring.rules.outcome import Outcome, Role, settled_outcome
from sparring.rules.scent import REFERENCE_MODEL, Trail


def sealed(payload: dict, nonce: str = "f" * 32) -> dict:
    return {"payload": payload, "nonce": nonce, "commit": kitref.commit(payload, nonce)}


def honest_walk(steps: int = 3) -> list[dict]:
    """A physically legal record trail: (0,0) marching east, one cell per step."""
    return [sealed({"step": s, "position": [0, s], "move": "MOVE:E", "intent": "truth"})
            for s in range(1, steps + 1)]


class TestTheFoundingProbe(unittest.TestCase):
    def test_the_fabricated_log_now_fails(self):
        """anrbj666's A1/A2 probe, verbatim: self-consistent commits, impossible game."""
        fake = [sealed({"step": s, "position": [9, 9], "move": "MOVE:NE", "intent": "truth"})
                for s in (1, 2, 3)]
        result = audit_records(fake, board_size=7, barriers_max=14, max_steps=35)
        self.assertFalse(result.passed)
        self.assertIn("off the 7x7 board", result.detail)
        # Judged from the POSITION TRAIL, not from the spelling of the move — so it is a
        # physics failure and not an integrity one, and must not be called tampering.
        self.assertEqual([], result.tampered_steps)

    def test_a_diagonal_is_caught_by_the_trail_whatever_it_is_called(self):
        """A1/A2's diagonal, on-board and named in a vocabulary this kit does not know.

        The old token whitelist would have caught `MOVE:NE` and missed `NE`; the trail catches
        both, because a diagonal is two orthogonal steps however the peer spells it.
        """
        for token in ("MOVE:NE", "NE", "northeast", None):
            with self.subTest(token=token):
                diag = [sealed({"step": s, "position": [s, s], "move": token})
                        for s in (1, 2, 3)]
                result = audit_records(diag, board_size=7, barriers_max=14, max_steps=35)
                self.assertFalse(result.passed)
                self.assertIn("more than one orthogonal step", result.detail)


class TestForeignVocabularies(unittest.TestCase):
    """A revealed payload's SCHEMA is not an interop constraint — `vectors/commit_reveal.json`
    ("the canonical form must match cross-team even though the payload does not").

    An earlier revision rejected any `move` token outside this kit's own `MOVE:<D>` spelling,
    unconditionally, and so called an honest sealed counted series TAMPERED: both real league
    teams name their moves `"E"`, and the pairing's signed config declared
    `move_set: ["N", "S", "E", "W", "STAY"]`. Found by the reciprocal audit of anrbj666's
    counted artifacts, 2026-08-05, inside the copy of OUR OWN records they had sealed.
    """

    def test_a_legal_walk_named_in_another_teams_vocabulary_verifies(self):
        recs = [sealed({"step": s, "position": [0, s], "move": "E", "intent": "truth"})
                for s in (1, 2, 3)]
        result = audit_records(recs, board_size=7, barriers_max=14, max_steps=35)
        self.assertTrue(result.passed, result.detail)

    def test_a_token_this_kit_does_not_know_is_not_tampering(self):
        """`BARRIER` is one real team's word for "this turn placed a barrier". Unknown here,
        and a position that does not move is legal, so there is nothing to complain about."""
        recs = [sealed({"step": s, "position": [2, 2], "move": "BARRIER"}) for s in (1, 2)]
        result = audit_records(recs, board_size=7, barriers_max=14, max_steps=35)
        self.assertTrue(result.passed, result.detail)

    def test_a_recognised_token_is_still_checked_against_the_trail(self):
        """Where the spelling IS ours, it must describe the step the positions show."""
        recs = [sealed({"step": 1, "position": [0, 1], "move": "MOVE:E"}),
                sealed({"step": 2, "position": [1, 1], "move": "MOVE:E"})]   # actually south
        result = audit_records(recs, board_size=7, barriers_max=14, max_steps=35)
        self.assertFalse(result.passed)
        self.assertIn("but the positions moved", result.detail)
        self.assertEqual([], result.tampered_steps)

    def test_a_real_hash_mismatch_is_still_tampering(self):
        recs = honest_walk()
        recs[1]["commit"] = "0" * 64
        result = audit_records(recs, board_size=7, barriers_max=14, max_steps=35)
        self.assertFalse(result.passed)
        self.assertEqual([2], result.tampered_steps)
        self.assertIn("THREE different commit constructions", result.detail)


class TestBinding(unittest.TestCase):
    """Layer 2: the revealed game must be the game that was on the wire."""

    def test_a_clean_reveal_matches_what_was_played(self):
        records = honest_walk()
        played = {r["payload"]["step"]: r["commit"] for r in records}
        self.assertTrue(audit_records(records, played=played).passed)

    def test_revealing_a_different_game_fails(self):
        # Played one game, revealed another: every commit self-verifies, none match the wire.
        played = {r["payload"]["step"]: r["commit"] for r in honest_walk()}
        other = [sealed({"step": s, "position": [s, 0], "move": "MOVE:S", "intent": "truth"})
                 for s in (1, 2, 3)]
        result = audit_records(other, played=played)
        self.assertFalse(result.passed)
        self.assertIn("a different game than the one on the wire", result.detail)

    def test_withholding_a_played_step_fails(self):
        records = honest_walk()
        played = {r["payload"]["step"]: r["commit"] for r in records}
        result = audit_records(records[:-1], played=played)
        self.assertFalse(result.passed)
        self.assertIn("missing from the reveal", result.detail)

    def test_revealing_a_step_we_never_received_fails(self):
        records = honest_walk()
        played = {r["payload"]["step"]: r["commit"] for r in records}
        del played[2]
        result = audit_records(records, played=played)
        self.assertFalse(result.passed)
        self.assertIn("never received in play", result.detail)

    def test_the_unconsumed_tail_is_tolerated(self):
        # The receiver legitimately stops polling once the game ends for it, so revealed steps
        # PAST its consumed frontier are not a fault — without this, every honest terminal
        # message would read as tampering.
        records = honest_walk(4)
        played = {r["payload"]["step"]: r["commit"] for r in records[:3]}
        self.assertTrue(audit_records(records, played=played).passed)


class TestPhysics(unittest.TestCase):
    """Layer 3: moves are hidden until the audit, so the audit is where physics is enforced."""

    def test_a_position_jump_fails(self):
        records = [sealed({"step": 1, "position": [0, 0], "move": "MOVE:E", "intent": "truth"}),
                   sealed({"step": 2, "position": [3, 3], "move": "MOVE:E", "intent": "truth"})]
        result = audit_records(records, board_size=7)
        self.assertFalse(result.passed)
        self.assertIn("more than one orthogonal step", result.detail)

    def test_barrier_placements_beyond_the_quota_fail(self):
        records = [sealed({"step": s, "position": [0, 0], "move": "STAY", "intent": "truth",
                           "verdict": "placed_barrier"}) for s in range(1, 4)]
        result = audit_records(records, board_size=7, barriers_max=2)
        self.assertFalse(result.passed)
        self.assertIn("exceeds the signed quota", result.detail)

    def test_steps_past_the_ceiling_fail(self):
        records = [sealed({"step": 37, "position": [0, 0], "move": "STAY", "intent": "truth"})]
        result = audit_records(records, max_steps=35)
        self.assertFalse(result.passed)
        self.assertIn("past the ceiling", result.detail)

    def test_a_step_zero_declaration_is_exempt(self):
        # Step-0 records seal identity, not motion — they carry no position and no wire commit.
        records = [sealed({"step": 0, "type": "system_spec", "spec": {"os": "any"}})]
        self.assertTrue(audit_records(records, board_size=7, max_steps=35).passed)


class TestLiveInboundChecks(unittest.TestCase):
    """A3's in-play half: quota and sender-role are checked as barriers arrive, not just at
    the audit."""

    def _engine(self, barriers_max: int = 2) -> SubGameEngine:
        return SubGameEngine(board=Board(7), role=Role.THIEF, position=(3, 3),
                             trail=Trail(model=REFERENCE_MODEL, board_size=7),
                             barriers_max=barriers_max)

    def test_inbound_barriers_beyond_the_quota_refuse(self):
        engine = self._engine(barriers_max=2)
        engine.observe_barrier((0, 0))
        engine.observe_barrier((0, 1))
        with self.assertRaises(IllegalMove) as ctx:
            engine.observe_barrier((0, 2))
        self.assertIn("signed quota", str(ctx.exception))

    def test_a_redeclared_barrier_does_not_consume_quota(self):
        engine = self._engine(barriers_max=2)
        engine.observe_barrier((0, 0))
        engine.observe_barrier((0, 0))      # at-least-once redelivery of the same cell
        engine.observe_barrier((0, 1))      # still within quota
        self.assertEqual(engine.opponent_barriers, 2)


class TestSettlementRule(unittest.TestCase):
    """B4: one settlement model for both drivers — and TAMPER_FORFEIT finally assignable."""

    def test_clean_audits_settle_the_played_outcome(self):
        self.assertEqual(settled_outcome(Outcome.CAPTURE, True, True),
                         (Outcome.CAPTURE, True))

    def test_a_failed_audit_settles_as_tamper_forfeit(self):
        self.assertEqual(settled_outcome(Outcome.CAPTURE, True, False),
                         (Outcome.TAMPER_FORFEIT, True))

    def test_a_zeroed_outcome_settles_without_an_audit(self):
        # The pair-agreed technical-loss row (PAIRING-PLAYBOOK stage 7): settled, reportable.
        self.assertEqual(settled_outcome(Outcome.TECHNICAL_LOSS, False, False),
                         (Outcome.TECHNICAL_LOSS, True))
        self.assertEqual(settled_outcome(Outcome.TIMEOUT, False, False),
                         (Outcome.TIMEOUT, True))

    def test_a_played_outcome_without_an_audit_does_not_settle(self):
        self.assertEqual(settled_outcome(Outcome.SURVIVAL, False, False),
                         (Outcome.SURVIVAL, False))


if __name__ == "__main__":
    unittest.main()
