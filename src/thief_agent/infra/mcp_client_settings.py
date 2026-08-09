"""How this peer talks to its opponent: the address, the deadline, the budget.

Separated from :mod:`.mcp_client`, which owns the client that spends what is
declared here. The split keeps the numbers that decide a match — a timeout, a
retry count, a backoff — readable in one screen next to the reasoning for each.

The names here are re-exported from :mod:`.mcp_client`; importers should keep
using that module rather than reaching in here.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..shared.appendix_f import book_int
from .tunnel import normalise

__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RESPONSE_TIMEOUT_SEC",
    "DEFAULT_RETRY_BACKOFF_SEC",
    "OPPONENT_URL_ENV",
    "ClientSettings",
]


OPPONENT_URL_ENV = "OPPONENT_URL"
"""Overrides ``opponent_url`` in the private TOML. See :meth:`ClientSettings.from_config`."""

NETWORK_SECTION = "network_and_league"
LIMITER_SECTION = "rate_limiter_gatekeeper"

DEFAULT_RESPONSE_TIMEOUT_SEC = float(book_int(NETWORK_SECTION, "response_timeout_sec"))
DEFAULT_MAX_RETRIES = book_int(LIMITER_SECTION, "max_retries")
DEFAULT_RETRY_BACKOFF_SEC = float(book_int(LIMITER_SECTION, "retry_backoff_sec"))
"""The three Appendix F numbers this client spends, read from the table.

Restating them as literals here would leave a copy that agrees with the book
today and can disagree with it silently tomorrow.
"""


@dataclass(frozen=True, slots=True)
class ClientSettings:
    """How this peer talks to its opponent.

    Defaults follow Appendix F. ``response_timeout_sec`` is negotiable and
    ``max_retries``/``retry_backoff_sec`` are minimums, so all three are
    parameters rather than constants.
    """

    opponent_url: str
    response_timeout_sec: float = DEFAULT_RESPONSE_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_sec: float = DEFAULT_RETRY_BACKOFF_SEC

    def __post_init__(self) -> None:
        if not self.opponent_url.strip():
            raise ValueError("opponent_url must be set; it is all we know about the opponent")
        if self.response_timeout_sec <= 0:
            raise ValueError(f"response_timeout_sec must be > 0, got {self.response_timeout_sec}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        object.__setattr__(self, "opponent_url", normalise(self.opponent_url))

    @property
    def worst_case_seconds(self) -> float:
        """Longest one call can take before it gives up.

        Every attempt may burn the full response timeout before failing, and
        every gap between attempts costs the backoff:

            (max_retries + 1) * response_timeout_sec + max_retries * retry_backoff_sec

        At the Appendix F defaults that is ``4 * 30 + 3 * 5 = 135`` seconds —
        **more than twice** ``watchdog_timeout_sec`` of 60. That is not a bug
        in either number; it means a peer waiting out a dead tunnel looks
        identical to a peer that has hung, unless it says otherwise. It does:
        :class:`OpponentClient` reports liveness on every attempt.

        Exposed rather than left implicit because ``max_retries`` is a raisable
        minimum, and raising it moves this number without anyone noticing.
        """
        attempts = self.max_retries + 1
        return attempts * self.response_timeout_sec + self.max_retries * self.retry_backoff_sec

    @classmethod
    def from_config(
        cls, network: dict[str, Any], environ: Mapping[str, str] | None = None
    ) -> "ClientSettings":
        """Read the opponent URL, letting the environment override the file.

        The committed TOML points at ``127.0.0.1`` because that is the local
        development loop. League play points somewhere else, and that address
        is a poor thing to commit twice over: it is **ephemeral**, since a
        free-tier tunnel issues a new one on every restart, and it is **not
        ours** — it belongs to whichever team we drew this round, and a repo
        full of other teams' addresses is a record of nothing.

        So :data:`OPPONENT_URL_ENV` wins when it is set. The file keeps the
        loopback default, which means checking out this repository and running
        the two agents against each other still works with no setup — and a
        match against a real opponent is one exported variable, not an edit
        that has to be reverted before the next commit.
        """
        source = os.environ if environ is None else environ
        override = source.get(OPPONENT_URL_ENV, "").strip()
        if not override and "opponent_url" not in network:
            raise ValueError(
                f"private config [network] must define opponent_url, or set {OPPONENT_URL_ENV}"
            )
        return cls(opponent_url=override or str(network["opponent_url"]))
