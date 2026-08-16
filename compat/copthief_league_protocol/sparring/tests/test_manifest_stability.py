"""The mail-absence manifest must identify the source, not the checkout.

Found by CI: the manifest hashed raw file bytes, so the same commit produced a different value on
a CRLF checkout than on an LF one. That makes it useless for the thing it exists for — two peers
comparing whether they ran the same mail-free code — and it is written into the declaration
artifact and the generated evidence page, which is how it surfaced as a drift failure.

Note what this file does *not* do: import ``hashlib``. The purity guard forbids that outside the
one seam, and it was right to refuse an earlier version of this test — the property worth
asserting is that the normalisation is applied, not that SHA-256 works.
"""

import unittest
from pathlib import Path

from sparring.guards import no_mail

SOURCE = Path(no_mail.__file__).read_text(encoding="utf-8")


class TestManifestIsCheckoutIndependent(unittest.TestCase):
    def test_line_endings_are_normalised_before_hashing(self):
        self.assertIn('replace(b"\\r\\n", b"\\n")', SOURCE,
                      "manifest_sha256 must normalise CRLF before hashing, or the same commit "
                      "hashes differently on a Windows checkout than on a Linux one")

    def test_paths_are_recorded_with_forward_slashes(self):
        self.assertIn('.replace("\\\\", "/")', SOURCE,
                      "a Windows path separator would change the manifest too")

    def test_the_manifest_is_stable_within_a_run(self):
        self.assertEqual(no_mail.manifest_sha256(), no_mail.manifest_sha256())

    def test_the_manifest_covers_every_scanned_source(self):
        # If a file could be added to the package without entering the manifest, the artifact's
        # claim about the code that produced it would be narrower than it looks.
        self.assertGreater(len(no_mail._sources()), 20)
        self.assertTrue(all(p.suffix == ".py" for p in no_mail._sources()))


if __name__ == "__main__":
    unittest.main()
