"""Phase 2 of the ceremony: the acknowledgement that fixes both moves."""

from dataclasses import dataclass
from typing import Any

from ..domain.actions import ROLES
from .ceremony_errors import DIGEST, CeremonyError
from .validation import InvalidPayloadError, require_int, require_mapping, require_str

ACK_FIELDS = ("step", "sender", "acknowledges", "timestamp")
"""Everything phase 2 may carry."""


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """Phase 2. *I have your commitment and I am locked on it.*

    The rulebook gives this phase one job and states it plainly: the
    acknowledgement *"ensures the reveal happens only once both sides have
    already fixed their moves"*. It does two things at once — it stops the
    sender walking back a commitment we have already seen, and it stops us
    revealing into a peer who has not committed yet.

    ``acknowledges`` carries the digest being acknowledged rather than a bare
    "yes". A yes is unfalsifiable: a peer that later claims it acknowledged a
    *different* commitment cannot be contradicted by it, and the whole phase
    turns on being able to say precisely what was locked.
    """

    step: int
    sender: str
    acknowledges: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.sender not in ROLES:
            raise CeremonyError(f"sender must be one of {sorted(ROLES)}, got {self.sender!r}")
        if self.step < 0:
            raise CeremonyError(f"step must be >= 0, got {self.step}")
        if not DIGEST.match(self.acknowledges):
            raise CeremonyError(
                f"acknowledges must be 64 lowercase hex characters, got {self.acknowledges!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "sender": self.sender,
            "acknowledges": self.acknowledges,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Acknowledgement":
        """Parse an inbound acknowledgement.

        Raises:
            CeremonyError: on anything we would not want to act on.
        """
        try:
            body = require_mapping(data, "acknowledgement")
            return cls(
                step=require_int(body, "step", minimum=0, maximum=10_000),
                sender=require_str(body, "sender"),
                acknowledges=require_str(body, "acknowledges"),
                timestamp=require_str(body, "timestamp"),
            )
        except InvalidPayloadError as exc:
            raise CeremonyError(str(exc)) from exc
