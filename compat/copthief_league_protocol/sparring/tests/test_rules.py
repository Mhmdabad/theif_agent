"""Board physics and the four ways a sub-game ends."""

import unittest

from sparring.rules.board import Board
from sparring.rules.engine import IllegalMove, SubGameEngine
from sparring.rules.outcome import Outcome, Role, is_tie_row, role_for, score_for
from sparring.rules.scent import REFERENCE_MODEL, Trail


def engine(role=Role.THIEF, pos=(3, 3), barriers=(), size=7):
    return SubGameEngine(board=Board(size), role=role, position=pos,
                         trail=Trail(REFERENCE_MODEL, size), barriers=list(barriers))


class TestBoard(unittest.TestCase):
    def test_no_diagonals_exist_at_all(self):
        # App. F fixes the move set permanently: four orthogonal directions, or stay.
        moves = Board(7).legal_moves((3, 3), [])
        self.assertEqual(set(moves), {"MOVE:N", "MOVE:S", "MOVE:E", "MOVE:W", "STAY"})

    def test_edges_and_barriers_remove_moves(self):
        self.assertEqual(set(Board(7).legal_moves((0, 0), [])), {"MOVE:S", "MOVE:E", "STAY"})
        self.assertEqual(set(Board(7).legal_moves((0, 0), [(0, 1)])), {"MOVE:S", "STAY"})

    def test_stay_is_always_available(self):
        self.assertIn("STAY", Board(7).legal_moves((0, 0), [(1, 0), (0, 1)]))

    def test_barrier_targets_are_own_cell_plus_orthogonal(self):
        targets = set(Board(7).barrier_targets((3, 3), []))
        self.assertEqual(targets, {(3, 3), (2, 3), (4, 3), (3, 2), (3, 4)})

    def test_barrier_targets_exclude_existing_barriers_and_off_board(self):
        self.assertEqual(set(Board(7).barrier_targets((0, 0), [(0, 1)])), {(0, 0), (1, 0)})


class TestTerminalConditions(unittest.TestCase):
    def test_barrier_on_the_thiefs_own_cell_is_capture(self):
        # App. E rule 46 — and only the thief can see it, which is why it is checked here.
        e = engine(pos=(3, 3), barriers=[(3, 3)])
        self.assertIs(e.self_captured(), Outcome.CAPTURE)

    def test_thief_with_no_legal_move_is_capture(self):
        # rule 47: walled in on all four sides. Staying still does not rescue it.
        e = engine(pos=(3, 3), barriers=[(2, 3), (4, 3), (3, 2), (3, 4)])
        self.assertIs(e.self_captured(), Outcome.CAPTURE)

    def test_a_corner_thief_needs_only_two_barriers(self):
        e = engine(pos=(0, 0), barriers=[(1, 0), (0, 1)])
        self.assertIs(e.self_captured(), Outcome.CAPTURE)

    def test_police_never_self_captures(self):
        e = engine(role=Role.POLICE, pos=(3, 3), barriers=[(2, 3), (4, 3), (3, 2), (3, 4)])
        self.assertIsNone(e.self_captured())

    def test_survival_at_the_threshold(self):
        e = engine()
        e.step = 34
        self.assertFalse(e.survived())
        e.step = 35
        self.assertTrue(e.survived())


class TestClaimHonesty(unittest.TestCase):
    def test_thief_answers_truthfully_when_found(self):
        e = engine(pos=(2, 4))
        self.assertEqual(e.answer_capture_claim([2, 4]), {"claim": [2, 4], "caught": True})

    def test_thief_answers_truthfully_when_not_found(self):
        e = engine(pos=(2, 4))
        self.assertEqual(e.answer_capture_claim([5, 5]), {"claim": [5, 5], "caught": False})

    def test_police_does_not_answer_capture_claims(self):
        self.assertIsNone(engine(role=Role.POLICE).answer_capture_claim([1, 1]))


class TestIllegalMoves(unittest.TestCase):
    def test_moving_into_a_barrier_is_rejected(self):
        e = engine(pos=(3, 3), barriers=[(2, 3)])
        with self.assertRaises(IllegalMove):
            e.apply_own_move("MOVE:N")

    def test_moving_off_the_board_is_rejected(self):
        with self.assertRaises(IllegalMove):
            engine(pos=(0, 0)).apply_own_move("MOVE:N")

    def test_only_the_cop_places_barriers(self):
        with self.assertRaises(IllegalMove):
            engine(role=Role.THIEF).place_own_barrier((3, 4))

    def test_barrier_out_of_reach_is_rejected(self):
        with self.assertRaises(IllegalMove):
            engine(role=Role.POLICE, pos=(0, 0)).place_own_barrier((5, 5))


class TestStateString(unittest.TestCase):
    def test_state_carries_only_our_own_position(self):
        # Hidden positions: there is no shared board frame, so `state` is self-only by design.
        e = engine(pos=(2, 4), barriers=[(1, 1)])
        self.assertEqual(e.state_string(), "grid=7x7;self=[2, 4];barriers=[[1, 1]]")


class TestScoring(unittest.TestCase):
    def test_the_binding_table_values(self):
        self.assertEqual(score_for(Outcome.CAPTURE, Role.POLICE), 20)
        self.assertEqual(score_for(Outcome.CAPTURE, Role.THIEF), 5)
        self.assertEqual(score_for(Outcome.SURVIVAL, Role.POLICE), 5)
        self.assertEqual(score_for(Outcome.SURVIVAL, Role.THIEF), 10)

    def test_technical_loss_zeroes_both_sides(self):
        for role in Role:
            self.assertEqual(score_for(Outcome.TECHNICAL_LOSS, role), 0)
            self.assertEqual(score_for(Outcome.TAMPER_FORFEIT, role), 0)

    def test_roles_alternate_across_the_series(self):
        got = [role_for(Role.POLICE, n).value for n in range(1, 7)]
        self.assertEqual(got, ["police", "thief"] * 3)

    def test_a_zeroed_sub_game_is_a_sanction_not_a_tie(self):
        # The published technical-loss row shape (PAIRING-PLAYBOOK stage 7): 0-0 with
        # `tie: false` and `winner_group: null`. Two zeroes mean nobody won.
        for outcome in (Outcome.TIMEOUT, Outcome.TECHNICAL_LOSS, Outcome.TAMPER_FORFEIT):
            self.assertFalse(is_tie_row(outcome, 0, 0))

    def test_an_equal_score_on_a_played_outcome_still_ties(self):
        self.assertTrue(is_tie_row(Outcome.SURVIVAL, 7, 7))
        self.assertFalse(is_tie_row(Outcome.CAPTURE, 20, 5))


if __name__ == "__main__":
    unittest.main()
