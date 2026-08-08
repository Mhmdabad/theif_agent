"""The attempt loop behind :meth:`.mcp_client.OpponentClient.call`.

Separated from :mod:`.mcp_client`, which owns the client this loop runs on
behalf of. Every value the loop depends on — the address, the deadline, the
budget, the liveness hook — is read off that owning client at the moment it is
used, never copied in when the call starts. Two of them are rebound while a
match is running: :meth:`.mcp_client.OpponentClient.repoint` replaces the
settings when a free tunnel moves, and the orchestrator installs its watchdog
heartbeat as ``on_attempt`` after the client already exists. A snapshot of
either is a client that keeps calling a dead address, or a watchdog that
reports a stall over a recovery that is working.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from ..shared.config import canonical_bytes
from .mcp_client_faults import OpponentUnreachableError, PeerNotReadyError, deferred
from .transport_log import CONNECT, RETRY, SENT, TIMEOUT, UNREACHABLE

if TYPE_CHECKING:
    from .mcp_client import OpponentClient

__all__ = [
    "attempt_series",
    "back_off",
]


def attempt_series(client: OpponentClient, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run ``client``'s whole retry budget for one call. See that method."""
    url = client._settings.opponent_url
    frozen = canonical_bytes(payload)
    client.log.record(SENT, tool, url, detail=hashlib.sha256(frozen).hexdigest())
    last: Exception | None = None
    shut = ""
    for attempt in range(client._settings.max_retries + 1):
        client.attempts += 1
        client.on_attempt(tool)
        try:
            answer = client._transport.call(
                url, tool, json.loads(frozen), client._settings.response_timeout_sec
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            last = exc
            client.log.record(TIMEOUT, tool, url, detail=f"{type(exc).__name__}: {exc}")
            back_off(client, attempt, tool, url)
        else:
            if url not in client._connected:
                client._connected.add(url)
                client.log.record(CONNECT, tool, url)
            if not deferred(answer):
                return answer
            shut = str(answer.get("detail", ""))
            client.log.record(TIMEOUT, tool, url, detail=f"deferred: {shut}")
            back_off(client, attempt, tool, url)
    spent = f"{tool} failed after {client._settings.max_retries + 1} attempts against {url}"
    client.log.record(UNREACHABLE, tool, url, detail=shut or str(last))
    if shut:
        raise PeerNotReadyError(f"{spent}; the last answer was {shut!r}")
    raise OpponentUnreachableError(spent) from last


def back_off(client: OpponentClient, attempt: int, tool: str, url: str) -> None:
    """Wait out the agreed gap before the next attempt, if there is one."""
    if attempt >= client._settings.max_retries:
        return
    client.log.record(
        RETRY,
        tool,
        url,
        detail=(
            f"attempt {attempt + 2} of {client._settings.max_retries + 1} "
            f"after {client._settings.retry_backoff_sec:g}s"
        ),
    )
    client._sleep(client._settings.retry_backoff_sec)
