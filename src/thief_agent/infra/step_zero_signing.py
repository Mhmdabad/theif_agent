"""The declaration document and its HMAC signature.

Split out of :mod:`step_zero`, which re-exports every name here and keeps
the reading of the key itself, because the key comes from the environment
and from nowhere else.
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from ..shared.config import canonical_bytes
from .step_zero_hardware import Hardware
from .step_zero_provenance import Provenance

UNSIGNED = "unsigned"
"""What a declaration says when no key was available. Not an empty signature."""


@dataclass(frozen=True, slots=True)
class Declaration:
    """The whole Step-0 statement, and its signature.

    Signed over the **canonical bytes** of the declaration, using the same
    serialisation as every other digest in the system. A signature over
    ``str(dict)`` would verify only against a peer running the same Python
    version, which is a compatibility bug that looks like a forgery.
    """

    hardware: Hardware
    provenance: Provenance
    signature: str

    @property
    def signed(self) -> bool:
        """Whether this declaration can actually be checked by anyone."""
        return self.signature != UNSIGNED

    def to_dict(self) -> dict[str, Any]:
        return {**statement(self.hardware, self.provenance), "signature": self.signature}


def statement(hardware: Hardware, provenance: Provenance) -> dict[str, Any]:
    """The declaration's content — everything the signature covers.

    Separate from :meth:`Declaration.to_dict` on purpose: what is signed and
    what is sent differ by exactly the signature, and a function that returned
    both would eventually be used to sign a document containing its own
    signature.
    """
    return {"hardware": hardware.to_dict(), "provenance": provenance.to_dict()}


def sign(content: dict[str, Any], key: str | None) -> str:
    """HMAC-SHA256 over the canonical bytes, or :data:`UNSIGNED`.

    HMAC rather than a bare hash: a plain ``sha256`` of a public document is
    something anybody can compute, so it would authenticate nothing while
    looking exactly like a signature.

    A missing key yields :data:`UNSIGNED` rather than an empty string or a
    signature over an empty key. Both of those are values that *verify*, and a
    declaration that verifies against a key nobody holds is worse than one that
    says plainly it was never signed.
    """
    if not key:
        return UNSIGNED
    return hmac.new(key.encode("utf-8"), canonical_bytes(content), hashlib.sha256).hexdigest()


def verify_signature(declared: dict[str, Any], key: str | None) -> bool:
    """Re-derive a declaration's signature and compare in constant time.

    Used against the **opponent's** declaration, where the timing channel is
    real: their signature is a secret-keyed value we are comparing against one
    we computed, and that is exactly the comparison ``==`` should never make.
    """
    claimed = declared.get("signature")
    if not isinstance(claimed, str) or claimed == UNSIGNED:
        return False
    content = {name: declared.get(name) for name in ("hardware", "provenance")}
    return hmac.compare_digest(sign(content, key), claimed)
