"""The parts a second implementation has to agree with: bytes, and decisions.

These are the tests worth copying into your own suite. If your peer passes them and passes
``verify_vectors.py``, the remaining ways to lose a game to us are operational rather than
protocol — which is what ``docs/LEAGUE-OPS.md`` is for.
"""

import json
import unittest
from pathlib import Path

from sparring import kitref
from sparring.config import SparConfig
from sparring.deadlines import Budgets, BudgetError, DeadlineTracker, FakeClock
from sparring.identity import info_mode_doc, locks, scent_doc, smell_binding_doc, wire_doc
from sparring.inbox import Equivocation, Inbox, ProtocolViolation
from sparring.negotiate import Refused, our_greeting, verify_peer
from sparring.rules.scent import BOOK_MODEL, REFERENCE_MODEL, Trail
from sparring.state import IllegalTransition, PeerState, PeerStateMachine

VECTORS = kitref.KIT_ROOT / "vectors"


def vector(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


class TestSealingReproducesTheFixtures(unittest.TestCase):
    """The peer seals with the kit's own function, so it must reproduce the published vectors."""

    def test_commit_vectors(self):
        for case in vector("commit_reveal.json")["vectors"]:
            self.assertEqual(kitref.commit(case["payload"], case["nonce"]), case["commit"],
                             msg=case.get("note", ""))

    def test_non_ascii_hint_is_not_escaped(self):
        # The single most important fact in the kit: escape it and every non-ASCII step fails the
        # opponent's audit, and the match voids for BOTH sides.
        canonical = kitref.canonical_str({"hint": "אני ליד הנמל"})
        self.assertIn("אני", canonical)
        self.assertNotIn("\\u", canonical)

    def test_the_peer_hashes_nothing_by_hand(self):
        # Structural, not stylistic: guards/purity.py rule P-1 keeps hashlib out of every module
        # except kitref, so the peer physically cannot grow a second construction.
        pkg = Path(kitref.__file__).resolve().parent
        offenders = [p.name for p in pkg.rglob("*.py")
                     if "hashlib" in p.read_text(encoding="utf-8")
                     and "tests" not in p.parts
                     and p.name not in ("kitref.py", "no_mail.py", "purity.py")]
        self.assertEqual(offenders, [])


class TestScentMatchesTheKit(unittest.TestCase):
    def test_reference_trail_equals_the_pinned_functions(self):
        trail = Trail(REFERENCE_MODEL, 7)
        field = trail.full_turn((3, 3))
        expected = kitref.smell_decay(kitref.smell_emit([3, 3], 0.9, 5, 7), 0.1)
        self.assertEqual(field, {k: v for k, v in expected.items() if v > 0})

    def test_book_trail_equals_the_pinned_function(self):
        trail = Trail(BOOK_MODEL, 7)
        self.assertEqual(trail.full_turn((3, 3)), kitref.book_full_turn({}, [3, 3], 0.1, 0.9, 7))

    def test_the_two_models_disagree(self):
        a = Trail(REFERENCE_MODEL, 7).full_turn((3, 3))
        b = Trail(BOOK_MODEL, 7).full_turn((3, 3))
        self.assertNotEqual(a, b)


class TestLockedModelDeclarations(unittest.TestCase):
    def test_our_docs_hash_to_the_kits_registrations(self):
        registered = {e["doc"]["name"]: e["sha256"] for e in vector("locked_model.json")["registered"]}
        self.assertEqual(kitref.lock_hash(scent_doc(REFERENCE_MODEL)),
                         registered[REFERENCE_MODEL])
        self.assertEqual(kitref.lock_hash(scent_doc(BOOK_MODEL)), registered[BOOK_MODEL])
        self.assertEqual(kitref.lock_hash(wire_doc()), registered["reference-v3"])
        self.assertEqual(kitref.lock_hash(info_mode_doc()), registered["belief"])
        self.assertEqual(kitref.lock_hash(smell_binding_doc()), registered["none"])

    def test_we_declare_what_a_second_implementation_declared_live(self):
        live = vector("locked_model.json")["live_reproduction"][
            "observed_declarations_matching_registrations"]
        ours = locks(BOOK_MODEL)
        self.assertEqual(ours["scent_model"], live["scent_model_sha256"])
        self.assertEqual(ours["wire_shape"], live["wire_shape_sha256"])
        self.assertEqual(ours["info_mode"], live["info_mode_sha256"])


class TestReceiverContract(unittest.TestCase):
    """SPEC section 7.1, checked against the kit's own decision table."""

    def setUp(self):
        self.inbox = Inbox(window=2)

    def offer(self, step, commit="c"):
        return self.inbox.offer({"step": step, "commit": f"{commit}{step}"})

    def test_in_order_delivery_applies(self):
        self.assertEqual(len(self.offer(1)), 1)
        self.assertEqual(len(self.offer(2)), 1)

    def test_redelivery_is_absorbed_and_changes_nothing(self):
        self.offer(1)
        self.assertEqual(self.offer(1), [])
        self.assertEqual(self.inbox.absorbed, 1)
        self.assertEqual(self.inbox.next_step, 2)

    def test_a_different_commit_for_a_played_step_stays_loud(self):
        # The load-bearing distinction. A (kind, step) key would have collapsed this into the
        # test above, silently discarding tampering evidence.
        self.offer(1)
        with self.assertRaises(Equivocation):
            self.inbox.offer({"step": 1, "commit": "something-else"})

    def test_out_of_order_inside_the_window_buffers_then_replays_in_order(self):
        self.assertEqual(self.offer(2), [])
        self.assertEqual(self.offer(3), [])
        ready = self.offer(1)
        self.assertEqual([m["step"] for m in ready], [1, 2, 3])

    def test_past_the_window_is_a_violation(self):
        with self.assertRaises(ProtocolViolation):
            self.offer(9)

    def test_a_zero_window_receiver_would_violate_on_an_ordinary_retry_race(self):
        # Not a tightening: under App. E rule 35 this is a self-inflicted technical loss that
        # takes the opponent's points too. Budgets refuses to construct one at all.
        with self.assertRaises(BudgetError):
            Budgets(inbound_buffer_limit=0)


class TestDeadlines(unittest.TestCase):
    def test_tolerated_traffic_cannot_renew_a_deadline(self):
        clock = FakeClock()
        tracker = DeadlineTracker(clock)
        tracker.expect("turn 3", 10.0)
        clock.advance(9.0)
        self.assertFalse(tracker.expired())
        # There is deliberately no renew(): arriving traffic does not discharge what is owed.
        self.assertFalse(hasattr(tracker, "renew"))
        clock.advance(1.0)
        self.assertTrue(tracker.expired())

    def test_budgets_report_every_violation_at_once(self):
        with self.assertRaises(BudgetError) as ctx:
            Budgets(watchdog_timeout=0, poll_interval=999, inbound_buffer_limit=0)
        self.assertGreaterEqual(str(ctx.exception).count("\n  "), 3)

    def test_the_stall_timeout_always_outlasts_the_turn_deadline(self):
        b = Budgets()
        self.assertGreater(b.io_stall_timeout, b.turn_timeout)


class TestStateMachine(unittest.TestCase):
    def test_the_happy_path(self):
        m = PeerStateMachine()
        for target in (PeerState.COMPUTING_MOVE, PeerState.COMMITTING, PeerState.AWAITING_REVEAL,
                       PeerState.VERIFYING, PeerState.WAITING_FOR_OPPONENT):
            m.to(target)
        self.assertIs(m.state, PeerState.WAITING_FOR_OPPONENT)

    def test_illegal_transitions_are_rejected(self):
        m = PeerStateMachine()
        with self.assertRaises(IllegalTransition):
            m.to(PeerState.VERIFYING)

    def test_technical_loss_is_absorbing(self):
        m = PeerStateMachine()
        m.fail()
        self.assertTrue(m.finished)
        with self.assertRaises(IllegalTransition):
            m.to(PeerState.COMPUTING_MOVE)


class TestTurnMessageStamp(unittest.TestCase):
    """Dogfood finding 3: nothing ever set `TurnMessage.timestamp`, so every outbound turn
    carried "" — and a receiver pinned to the reference's ISO stamp refuses the frame. The
    stamp comes through the clock seam (purity rule P-3), so self-play stays reproducible."""

    def _peer(self, clock):
        from sparring.policies import REGISTRY
        from sparring.rules.outcome import Role
        from sparring.turnloop import SubGamePeer
        cfg = SparConfig()
        return SubGamePeer(cfg=cfg, role=Role.POLICE, sub_game_number=1,
                           policy=REGISTRY[cfg.policy]["police"](), transport=None,
                           clock=clock, budgets=Budgets(), seed=1234)

    def test_outbound_turns_carry_an_iso_utc_stamp(self):
        # Asserted by shape rather than by parsing: importing datetime HERE would itself
        # violate purity rule P-3 — the guard caught exactly that in this test's first draft.
        msg = self._peer(FakeClock(start=42.0)).take_turn()
        self.assertTrue(msg.timestamp)
        self.assertIn("T", msg.timestamp)
        self.assertTrue(msg.timestamp.endswith("+00:00"))

    def test_the_fake_clock_stamp_is_deterministic(self):
        # Two peers at the same fake instant stamp identically — which is what keeps the
        # golden and the generated EVIDENCE byte-reproducible under a seed.
        a = self._peer(FakeClock(start=7.0)).take_turn()
        b = self._peer(FakeClock(start=7.0)).take_turn()
        self.assertEqual(a.timestamp, b.timestamp)

    def test_the_terminal_message_carries_the_field_not_an_empty_grid(self):
        # Dogfood finding 4: a terminal STAY is a real turn, so the field advances with it —
        # {} is the not-transmitted convention, not "game over".
        peer = self._peer(FakeClock())
        peer.take_turn()
        peer.pending_answer = {"answer": "no", "position": None}
        final = peer.terminal_message()
        self.assertIsNotNone(final)
        self.assertTrue(final.smell_grid)
        self.assertTrue(final.timestamp)


class TestHandshakeRefusals(unittest.TestCase):
    """Every refusal names which side's fix it is — the distinction that cost hours to see."""

    def setUp(self):
        self.cfg = SparConfig()
        self.ours = our_greeting(self.cfg, "police", 1, "0" * 32, locks(self.cfg.scent_model))
        self.theirs = our_greeting(self.cfg, "thief", 1, "1" * 32, locks(self.cfg.scent_model))

    def wire(self, **over):
        return {**self.theirs.to_wire(), "group_id": "sparring-other", **over}

    def test_a_matching_greeting_agrees(self):
        agreed = verify_peer(self.cfg, self.ours, self.wire())
        self.assertEqual(agreed.game_id, kitref.game_id(self.cfg.group_id, "sparring-other"))
        self.assertEqual(agreed.game_uid,
                         kitref.game_uid(self.cfg.terms(), self.cfg.group_id, "sparring-other"))

    def test_terms_absent_is_diagnosed_as_a_wire_fault(self):
        raw = self.wire()
        del raw["terms"]
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, raw)
        self.assertEqual(ctx.exception.code, "SPAR-N01")
        self.assertIn("no `terms` at all", ctx.exception.message)

    def test_terms_differing_is_diagnosed_separately_and_shows_the_diff(self):
        raw = self.wire(terms={**self.cfg.terms(), "setting": "Elsewhere"})
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, raw)
        self.assertEqual(ctx.exception.code, "SPAR-N03")
        self.assertIn("setting", ctx.exception.message)
        self.assertIn("canonical", ctx.exception.message.lower())

    def test_a_bad_signature_points_at_serialization(self):
        raw = self.wire(signature="0" * 64)
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, raw)
        self.assertEqual(ctx.exception.code, "SPAR-N04")
        self.assertIn("ensure_ascii", ctx.exception.message)

    def test_sub_game_mismatch_refuses(self):
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(sub_game_number=4))
        self.assertEqual(ctx.exception.code, "SPAR-N06")

    def test_role_collision_refuses(self):
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(role="police"))
        self.assertEqual(ctx.exception.code, "SPAR-N07")

    def test_a_scent_lock_mismatch_refuses(self):
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(scent_model_sha256="0" * 64))
        self.assertEqual(ctx.exception.code, "SPAR-N05")

    def test_an_info_mode_lock_mismatch_refuses(self):
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(info_mode_sha256="0" * 64))
        self.assertEqual(ctx.exception.code, "SPAR-N05")
        self.assertIn("info_mode", ctx.exception.message)

    def test_a_bare_string_info_mode_is_silence_not_a_mismatch(self):
        # The pre-2026-08-01 form: `info_mode` as a plain string. It rides a different key than
        # the doc hash, so even a *contradictory* string never reaches the lock comparison —
        # uncomparable is silence, and silence never refuses.
        raw = self.wire(info_mode="exact")
        raw.pop("info_mode_sha256", None)
        self.assertTrue(verify_peer(self.cfg, self.ours, raw).game_uid)

    def test_a_matching_uid_declaration_plays(self):
        uid = kitref.game_uid(self.cfg.terms(), self.cfg.group_id, "sparring-other")
        self.assertEqual(verify_peer(self.cfg, self.ours, self.wire(game_uid=uid)).game_uid, uid)

    def test_a_wrong_input_uid_refuses_at_the_handshake(self):
        # The WARNINGS §2 failure: a uid derived from a WIDER input than the flat terms is
        # stable, self-consistent, and wrong only cross-team. Declared at negotiate, it surfaces
        # here — the only moment before two reports are diffed.
        wrong = kitref.game_uid({**self.cfg.terms(), "extra_key": True},
                                self.cfg.group_id, "sparring-other")
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(game_uid=wrong))
        self.assertEqual(ctx.exception.code, "SPAR-N10")
        self.assertIn("WIDER input", ctx.exception.message)

    def test_an_uncomparable_uid_is_silence(self):
        self.assertTrue(verify_peer(self.cfg, self.ours, self.wire(game_uid=12345)).game_uid)

    def test_the_greeting_declares_uid_and_info_mode_when_opponent_is_known(self):
        mine = our_greeting(self.cfg, "police", 2, "2" * 32, locks(self.cfg.scent_model),
                            opponent_group="sparring-other")
        onwire = mine.to_wire()
        self.assertEqual(onwire["game_uid"],
                         kitref.game_uid(self.cfg.terms(), self.cfg.group_id, "sparring-other"))
        self.assertEqual(onwire["info_mode_sha256"], kitref.lock_hash(info_mode_doc()))
        # The fourth family: `unbound` is declared out loud (SPEC section 7.4, anrbj666's E13).
        self.assertEqual(onwire["smell_binding_sha256"], kitref.lock_hash(smell_binding_doc()))

    def test_a_smell_binding_mismatch_refuses(self):
        with self.assertRaises(Refused) as ctx:
            verify_peer(self.cfg, self.ours, self.wire(smell_binding_sha256="0" * 64))
        self.assertEqual(ctx.exception.code, "SPAR-N05")
        self.assertIn("smell_binding", ctx.exception.message)

    def test_omission_never_refuses_in_either_direction(self):
        # The rule that keeps the unmodified reference peer — which declares none of these —
        # playable. A guard that fail-fasts on silence forfeits that game to itself.
        raw = self.wire()
        for key in ("role", "sub_game_number", "scent_model_sha256", "wire_shape_sha256",
                    "info_mode_sha256", "info_mode", "game_uid"):
            raw.pop(key, None)
        self.assertTrue(verify_peer(self.cfg, self.ours, raw).game_uid)


if __name__ == "__main__":
    unittest.main()
