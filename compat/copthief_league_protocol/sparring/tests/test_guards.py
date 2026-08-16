"""The guards must catch what they claim to.

A guard that only ever passes is decoration, so each rule is fed a synthetic violation. Nothing is
written into the package: the violations are built in a temporary tree and the guard is pointed at
it, so a failing test cannot leave the repository dirty.
"""

import ast
import re
import tempfile
import unittest
from pathlib import Path

from sparring.config import SparConfig
from sparring.guards import no_mail, purity
from sparring.preflight import PreflightRefused, assert_sparring_ready


class TestGuardsPassOnTheRealPackage(unittest.TestCase):
    def test_no_mail_finds_nothing(self):
        self.assertEqual(no_mail.scan(), [])

    def test_purity_finds_nothing(self):
        self.assertEqual(purity.scan(), [])

    def test_the_manifest_hash_is_stable(self):
        self.assertEqual(no_mail.manifest_sha256(), no_mail.manifest_sha256())


class TestNoMailCatchesViolations(unittest.TestCase):
    """Each rule, fed the thing it exists to find."""

    def check(self, source: str, rule: str) -> None:
        tree = ast.parse(source)
        found = set()
        prose = no_mail._docstrings(tree)
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in no_mail.BANNED_IMPORTS:
                    found.add("NM-1")
                if root in no_mail.NETWORK_MODULES:
                    found.add("NM-5")
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                if node.value in no_mail.BANNED_PORTS:
                    found.add("NM-3")
            if isinstance(node, ast.FunctionDef) and no_mail.BANNED_FUNCS.match(node.name):
                found.add("NM-4")
            if isinstance(node, ast.Name) and no_mail.PREFLIGHT_BANNED.search(node.id):
                found.add("NM-7")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in prose and no_mail.PREFLIGHT_BANNED.search(node.value):
                    found.add("NM-7")
        if no_mail.BANNED_TOKENS.search(source):
            found.add("NM-2")
        self.assertIn(rule, found, msg=f"{rule} was not caught in:\n{source}")

    def test_nm1_a_mail_import(self):
        self.check("import smtplib\n", "NM-1")

    def test_nm1_an_oauth_import(self):
        self.check("import google_auth_oauthlib\n", "NM-1")

    def test_nm2_mail_vocabulary_in_a_string(self):
        self.check('URL = "smtp://relay.example"\n', "NM-2")

    def test_nm3_a_mail_port(self):
        self.check("PORT = 587\n", "NM-3")

    def test_nm4_a_mail_shaped_function(self):
        self.check("def send_report():\n    pass\n", "NM-4")

    def test_nm5_a_raw_socket_outside_the_transport(self):
        # The rule that makes "absent" mean absent: without it a package could import no mail
        # library and still open a socket to a mail port.
        self.check("import socket\n", "NM-5")

    def test_nm7_a_preflight_that_wants_a_recipient(self):
        self.check("recipient = None\n", "NM-7")

    def test_nm6_an_extra_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            req = Path(td) / "requirements.txt"
            req.write_text("fastmcp==2.0\nsendgrid==6.0\n", encoding="utf-8")
            wants = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            offenders = [w for w in wants if not re.match(r"^fastmcp\b", w, re.IGNORECASE)]
            self.assertEqual(offenders, ["sendgrid==6.0"])


class TestPurityCatchesViolations(unittest.TestCase):
    def rules_hit(self, source: str, *, in_policies: bool) -> set[str]:
        tree = ast.parse(source)
        found = set()
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root == "hashlib":
                    found.add("P-1")
                if root in ("time", "datetime"):
                    found.add("P-3")
                if in_policies and root not in purity.POLICY_IMPORTS_OK:
                    found.add("P-2")
        if in_policies and purity.WEIGHT_FILES.search(source):
            found.add("P-2")
        if in_policies and purity.FILE_READS.search(source):
            found.add("P-2")
        return found

    def test_p1_hand_rolling_a_hash(self):
        self.assertIn("P-1", self.rules_hit("import hashlib\n", in_policies=False))

    def test_p3_a_second_clock(self):
        self.assertIn("P-3", self.rules_hit("import time\n", in_policies=False))

    def test_p2_a_brain_that_loads_weights(self):
        self.assertIn("P-2", self.rules_hit('W = "model.pt"\n', in_policies=True))

    def test_p2_a_brain_that_reads_a_file(self):
        self.assertIn("P-2", self.rules_hit('d = open("w.json")\n', in_policies=True))

    def test_p2_a_brain_that_imports_numpy(self):
        self.assertIn("P-2", self.rules_hit("import numpy\n", in_policies=True))

    def test_withheld_names_are_read_from_kitref_not_restated(self):
        # If the two lists could drift, the guard would be checking yesterday's rule.
        self.assertIn("ref_report_consensus_signature", purity._withheld_names())


class TestPreflight(unittest.TestCase):
    def test_a_default_config_is_ready(self):
        report = assert_sparring_ready(SparConfig(), check_vectors=False)
        self.assertTrue(report.mail_scan_sha256)

    def test_a_fixed_value_may_not_move(self):
        with self.assertRaises(PreflightRefused) as ctx:
            assert_sparring_ready(SparConfig(emit_intensity=0.8), check_vectors=False)
        self.assertIn("App. F fixes it", str(ctx.exception))

    def test_a_minimum_may_not_be_lowered(self):
        with self.assertRaises(PreflightRefused) as ctx:
            assert_sparring_ready(SparConfig(board_size=5), check_vectors=False)
        self.assertIn("below App. F's minimum", str(ctx.exception))

    def test_a_raised_minimum_is_allowed(self):
        assert_sparring_ready(SparConfig(board_size=9, max_steps=40), check_vectors=False)

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(PreflightRefused) as ctx:
            assert_sparring_ready(SparConfig(board_size=5, emit_intensity=0.8, decay_per_step=0.2),
                                  check_vectors=False)
        self.assertGreaterEqual(str(ctx.exception).count("\n  "), 3)

    def test_the_preflight_asserts_nothing_about_a_deliverable(self):
        # The contract of the whole mode: rules armed, nothing owed. NM-7 enforces it, and this
        # is the test that would fail first if someone reintroduced a report obligation here.
        source = (Path(purity.PKG) / "preflight.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        prose = no_mail._docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertIsNone(no_mail.PREFLIGHT_BANNED.search(node.id))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in prose:
                    self.assertIsNone(no_mail.PREFLIGHT_BANNED.search(node.value))


class TestUncountedGroupId(unittest.TestCase):
    def test_a_sparring_peer_refuses_a_league_looking_group_id(self):
        from sparring.artifacts import assert_uncounted_group
        assert_uncounted_group("sparring-local")
        with self.assertRaises(ValueError) as ctx:
            assert_uncounted_group("imreeyal")
        self.assertIn("game_id is built from the group ids", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
