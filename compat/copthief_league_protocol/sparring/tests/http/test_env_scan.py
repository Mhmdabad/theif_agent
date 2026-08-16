"""The environment half of the mail-absence claim, in the tier where the dependency exists.

This lives in the HTTP tier because it is only meaningful once the one pinned dependency and its
transitive tree are actually installed — which is exactly the situation that found the bug it now
guards against.
"""

import os
import unittest

from sparring.guards import no_mail


def flagged(name: str) -> bool:
    name = name.lower()
    if name in no_mail.ENV_ALLOW:
        return False
    return any(name == s or name.startswith(f"{s}-") for s in no_mail.ENV_SENDERS)


class TestEnvironmentScan(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("CI"),
        "asserts a property of the AMBIENT site-packages, which only CI's environment "
        "guarantees — a contributor with (say) google-auth-oauthlib installed for unrelated "
        "work would go red for a reason that is not their code (anrbj666's audit, E8). The "
        "runtime guard still scans and refuses at sparring startup regardless of this skip.")
    def test_the_installed_environment_is_clean(self):
        self.assertEqual(no_mail._scan_environment(), [])

    def test_real_senders_are_flagged(self):
        for name in ("sendgrid", "aiosmtplib", "yagmail", "google-api-python-client",
                     "google-auth-oauthlib", "exchangelib"):
            self.assertTrue(flagged(name), msg=name)

    def test_a_validator_is_not_a_sender(self):
        """The false positive that failed a build.

        `email-validator` arrives transitively with the one pinned dependency and checks the shape
        of an address string; it opens no connection. A substring match on "mail" failed on it,
        and a guard that fails on a name collision teaches people to switch the guard off.
        """
        self.assertFalse(flagged("email-validator"))

    def test_the_dependency_itself_is_not_flagged(self):
        self.assertFalse(flagged("fastmcp"))

    def test_every_allowance_carries_a_reason(self):
        for name, reason in no_mail.ENV_ALLOW.items():
            self.assertTrue(reason.strip(), msg=f"{name} is allowed without a stated reason")


if __name__ == "__main__":
    unittest.main()
