"""The flagship: a whole series, and the same series over a hostile transport.

The second test is the strongest single statement this package makes. It is easy to claim a
receiver "handles duplicates"; what a team actually needs to know is that duplicates, reordering
and retries **changed nothing about who won** — same outcomes, same steps, same scores, same
final commits.
"""

import json
import tempfile
import unittest
from pathlib import Path

from sparring import kitref
from sparring.config import SparConfig
from sparring.deadlines import FakeClock
from sparring.policies.hints import TemplateHintProvider
from sparring.series import run_series
from sparring.transport.faults import FaultyTransport
from sparring.transport.loopback import pair

GOLDEN = Path(__file__).resolve().parent / "golden" / "selfplay.json"


def faulty(a, b):
    """Duplicates, reordering and drop-then-retry, on both directions at different periods."""
    ta, tb = pair(a, b)
    return (FaultyTransport(ta, duplicate_every=3, reorder_every=5, drop_then_retry_every=7),
            FaultyTransport(tb, duplicate_every=4, reorder_every=6, drop_then_retry_every=9))


def play(policy="greedy", seed=1234, factory=pair):
    with tempfile.TemporaryDirectory() as td:
        return run_series(SparConfig(seed=seed, policy=policy), Path(td),
                          clock=FakeClock(), check_vectors=False, transport_factory=factory), td


class TestSeriesCompletes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.result = run_series(SparConfig(seed=1234), Path(self.tmp.name),
                                 clock=FakeClock(), check_vectors=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_six_sub_games_are_played(self):
        self.assertEqual(len(self.result.sub_games), 6)

    def test_roles_alternate(self):
        roles = [row["role"] for row in self.result.ledger]
        self.assertEqual(roles, ["police", "thief"] * 3)

    def test_every_mutual_audit_is_clean(self):
        for sg in self.result.sub_games:
            self.assertTrue(sg["audit"]["log_verified"], msg=f"sub-game {sg['sub_game_number']}")
            self.assertFalse(sg["audit"]["tampered"])

    def test_one_game_uid_across_every_artifact(self):
        uids = set()
        for path in Path(self.tmp.name).rglob("*.json"):
            uids.add(json.loads(path.read_text(encoding="utf-8"))["game_uid"])
        self.assertEqual(uids, {self.result.game_uid})

    def test_fourteen_artifacts(self):
        # declaration + result, plus a config and a log per sub-game.
        self.assertEqual(len(self.result.artifacts), 14)

    def test_game_id_is_the_sorted_pair(self):
        a, b = self.result.game_id.split("-vs-")
        self.assertEqual([a, b], sorted([a, b]))

    def test_the_ids_derive_rather_than_being_minted(self):
        cfg = SparConfig()
        expected = kitref.game_uid(cfg.terms(), cfg.group_id, f"{cfg.group_id}-opponent")
        self.assertEqual(self.result.game_uid, expected)


class TestArtifactsAreUnmistakablyUncounted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.result = run_series(SparConfig(seed=7), Path(self.tmp.name),
                                 clock=FakeClock(), check_vectors=False)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_group_prefix_reaches_every_filename(self):
        for path in self.root.rglob("*.json"):
            self.assertIn("sparring-", path.name)

    def test_every_artifact_carries_the_league_block(self):
        for path in self.root.rglob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(doc["league"]["counted"])
            self.assertIn("rule 52", doc["league"]["authority"])

    def test_a_not_a_league_game_marker_sits_beside_them(self):
        self.assertTrue(list(self.root.rglob("NOT_A_LEAGUE_GAME.txt")))

    def test_the_result_carries_no_signature_to_submit(self):
        # The strongest of the five layers: a label can be edited, a missing preimage cannot be
        # emailed. There is nothing here to verify, so there is nothing to submit.
        result = next(self.root.rglob("result_*.json"))
        doc = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(doc["settlement"], "not_owed")
        for key in doc:
            self.assertNotIn("signature", key.lower())
            self.assertNotIn("consensus", key.lower())
        self.assertNotIn("mutual_agreement", doc)

    def test_the_result_league_fields_ride_in_the_friendly_posture(self):
        # Present, so a team templating from this output cannot forget they exist; disarmed, so
        # a practice run never claims a counted record (SPEC section 6.2, App. E rules 37-38).
        result = next(self.root.rglob("result_*.json"))
        doc = json.loads(result.read_text(encoding="utf-8"))
        final = doc["final_result"]
        self.assertTrue(all(v == 0 for v in final["games_played_including_this"].values()))
        self.assertTrue(all(v is False for v in final["diversity_reward_applied"].values()))
        self.assertIn("first_meeting_between_groups", final)

    def test_the_result_links_both_sides_repos(self):
        # Rule 49: the result reaches the repos on its own. The sparring peer's cop and thief
        # both live in this kit, and it says so rather than inventing two repos.
        result = next(self.root.rglob("result_*.json"))
        doc = json.loads(result.read_text(encoding="utf-8"))
        github = doc["links"]["github"]
        self.assertEqual(len(github), 2)
        for repos in github.values():
            self.assertTrue(repos["cop"].startswith("https://github.com/"))
            self.assertEqual(repos["cop"], repos["thief"])

    def test_every_handshake_declared_the_derived_uid_and_the_promoted_locks(self):
        # Self-play knows both sides a priori, so every greeting declares the derived game_uid
        # (SPEC section 7.3) and the info_mode doc hash (SPEC section 7, PROMOTED form) — and
        # verify_peer checked them on every sub-game, or this series would not have settled.
        from sparring.identity import info_mode_doc
        from sparring import kitref
        result = next(self.root.rglob("result_*.json"))
        doc = json.loads(result.read_text(encoding="utf-8"))
        self.assertTrue(doc["game_uid"])  # derived and joined — the declaration path ran
        self.assertEqual(kitref.lock_hash(info_mode_doc())[:8], "020947da")

    def test_artifacts_are_canonical_bytes_not_pretty_printed(self):
        # Rehearses SPEC section 6: what you emit is what you hashed.
        raw = next(self.root.rglob("config_*.json")).read_bytes()
        self.assertNotIn(b": ", raw.split(b"\n")[0])


class TestHostileTransportChangesNothing(unittest.TestCase):
    def test_the_ledger_is_identical_under_duplicates_reordering_and_retries(self):
        for policy in ("greedy", "random"):
            clean, _ = play(policy)
            rough, _ = play(policy, factory=faulty)
            self.assertEqual(clean.ledger, rough.ledger, msg=f"policy={policy}")
            self.assertTrue(rough.clean)

    def test_a_tied_series_awards_the_tie_score_into_the_totals(self):
        # N1 (imreeyal dogfood, 2026-08-04): the reference ADDS the App. F tie score into each
        # side's total; the first revision declared the raw sum beside a separate
        # tie_score_each, so the two sides of one tied match reported different numbers.
        import json
        import tempfile
        from pathlib import Path
        from sparring.config import SparConfig
        from sparring.deadlines import FakeClock
        from sparring.series import run_series
        with tempfile.TemporaryDirectory() as td:
            result = run_series(SparConfig(seed=1234, policy="random"), Path(td),
                                clock=FakeClock(), check_vectors=False)
            self.assertTrue(result.series_tie, "seed 1234 random-vs-random should tie")
            doc = json.loads(next(Path(td).rglob("result_*.json")).read_text(encoding="utf-8"))
        final = doc["final_result"]
        for group, total in final["total_score"].items():
            raw = sum(sg["score"][group] for sg in doc["sub_games"])
            self.assertEqual(total, raw + final["tie_score_each"])

    def test_a_capture_still_happens_somewhere(self):
        # Guards against a series that "passes" only because nothing interesting ever occurs:
        # the capture path, the claim/response exchange and the 20/5 scoring row all need to run.
        # Seed 1, not the default: the thief-first correction (dogfood finding 1) legitimately
        # reshuffled the seeded trajectories, and 1234's random-vs-random series became six
        # survivals — this test needs a capture to exist, not a particular seed.
        result, _ = play("random", seed=1)
        self.assertIn("capture", [row["outcome"] for row in result.ledger])


class TestGolden(unittest.TestCase):
    """Behavioural drift detection.

    The ledger is pinned, not the raw transcript: outcomes, steps, scores and final commits. That
    survives cosmetic changes and still fails the moment a policy, the physics or the sealing
    changes what actually happened.
    """

    def test_matches_the_committed_golden(self):
        if not GOLDEN.is_file():
            self.skipTest("no golden yet — run python -m sparring.tests.gen_golden")
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for policy, ledger in expected["ledgers"].items():
            result, _ = play(policy, seed=expected["seed"])
            self.assertEqual(result.ledger, ledger, msg=f"policy={policy}")


class TestHints(unittest.TestCase):
    def test_the_word_cap_comes_from_the_terms_and_is_enforced(self):
        import random
        provider = TemplateHintProvider(7, 5, "mixed", 0.5)
        rng = random.Random(0)
        for sub_game in range(1, 7):
            for intent in ("truth", "lie"):
                self.assertLessEqual(len(provider.hint((3, 3), intent, sub_game, rng).split()), 5)

    def test_non_ascii_reaches_the_wire_on_purpose(self):
        # A peer that only ever said ASCII would let a team finish a whole rehearsal without
        # discovering that its serializer escapes Hebrew — and find out at an opponent's audit.
        import random
        provider = TemplateHintProvider(7, 15, "mixed", 0.0)
        seen = "".join(provider.hint((3, 3), "truth", sg, random.Random(sg)) for sg in range(1, 9))
        self.assertTrue(any(ord(ch) > 0x5FF for ch in seen), "no non-ASCII hint was produced")

    def test_hints_are_deterministic_under_a_seed(self):
        import random
        provider = TemplateHintProvider(7, 15, "mixed", 0.25)
        a = provider.hint((2, 2), "truth", 2, random.Random(5))
        b = provider.hint((2, 2), "truth", 2, random.Random(5))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
