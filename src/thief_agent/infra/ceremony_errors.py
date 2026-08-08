"""What every phase of the ceremony agrees on: the failure, and the two shapes.

Split out of :mod:`.ceremony` so each phase module can depend on the vocabulary
without depending on the phases that come after it.
"""

import re

from ..domain.crypto import NONCE_BYTES

DIGEST = re.compile(r"^[0-9a-f]{64}$")
"""A SHA-256 digest as ``hexdigest`` renders it: 64 lowercase hex characters.

Checked rather than assumed. An uppercase or truncated digest still compares
unequal to ours, so it would surface as a forgery verdict against an opponent
whose only crime was formatting — and a forgery verdict is unappealable.
"""

NONCE_LENGTH = NONCE_BYTES * 2
NONCE = re.compile(rf"^[0-9a-f]{{{NONCE_LENGTH}}}$")
"""A nonce as :func:`~..domain.crypto.nonce` renders it."""


class CeremonyError(ValueError):
    """Raised when a phase message is malformed or arrives out of order."""
