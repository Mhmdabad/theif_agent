"""Phase 4 of the ceremony: every nonce of the match, at once, at the end."""

from dataclasses import dataclass
from typing import Any

from ..domain.actions import ROLES
from .ceremony_errors import NONCE, NONCE_LENGTH, CeremonyError
from .validation import InvalidPayloadError, require_mapping, require_str


@dataclass(frozen=True, slots=True)
class FinalReveal:
    """Phase 4. Every nonce of the match, disclosed at once, at the end.

    **At once and at the end are both load-bearing.** A nonce released while
    the match is running reopens the commitment it belongs to, and because
    every step uses the same construction it also narrows every other one — so
    the rulebook's *"only at the end of the whole game are all the Nonce values
    revealed"* is a single event by necessity rather than by tidiness.

    Disclosing them **all** matters for the opposite reason. A step whose nonce
    is missing is a step nobody can re-derive, and an audit that cannot
    re-derive a step proves nothing about it either way — which is exactly the
    step a cheat would omit. A partial final reveal is therefore refused rather
    than partially accepted.
    """

    sender: str
    nonces: dict[int, str]
    timestamp: str

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        for step, value in sorted(self.nonces.items()):
            if step < 0:
                raise CeremonyError(f"step must be >= 0, got {step}")
            if not NONCE.match(value):
                raise CeremonyError(
                    f"nonce for step {step} is not {NONCE_LENGTH} hex characters: {value!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        """The wire form. Step keys become strings, as JSON requires."""
        return {
            "sender": self.sender,
            "nonces": {str(step): value for step, value in sorted(self.nonces.items())},
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: object) -> "FinalReveal":
        """Parse an inbound final reveal.

        Raises:
            CeremonyError: on anything malformed. A step key that is not an
                integer is refused rather than skipped: a nonce we cannot file
                against a step is a nonce that verifies nothing, and silently
                dropping it would turn their formatting error into our
                unverifiable step.
        """
        try:
            body = require_mapping(data, "final reveal")
            raw = body.get("nonces")
            if not isinstance(raw, dict):
                raise CeremonyError(f"'nonces' must be an object, got {type(raw).__name__}")
            nonces: dict[int, str] = {}
            for key, value in raw.items():
                try:
                    step = int(key)
                except (TypeError, ValueError) as exc:
                    raise CeremonyError(f"step key {key!r} is not an integer") from exc
                if not isinstance(value, str):
                    raise CeremonyError(f"nonce for step {step} is not a string")
                nonces[step] = value
            return cls(
                sender=require_str(body, "sender"),
                nonces=nonces,
                timestamp=require_str(body, "timestamp"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc
