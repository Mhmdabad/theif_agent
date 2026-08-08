"""Reading the public URL out of a locally running ngrok agent.

The one vendor-specific corner of tunnel discovery, kept apart from the
vendor-neutral gate so that a team on a different tunnel never executes it.

Split out of :mod:`.tunnel`, which re-exports every name here.
"""

import json
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .tunnel_address import SCHEMES, NotPublicError

NGROK_API = "http://127.0.0.1:4040/api/tunnels"
"""The ngrok agent's local inspection API. Loopback by nature — it is ours."""


def from_ngrok(payload: str | bytes) -> str:
    """Pull the public URL out of a response from :data:`NGROK_API`.

    The agent reports every tunnel it is running, so the HTTPS one is preferred
    and the HTTP one is the fallback — free-tier ngrok publishes both for the
    same port, and picking arbitrarily would make the address we advertise
    depend on dictionary order.

    Raises:
        NotPublicError: if the response carries no usable tunnel.
    """
    try:
        body: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise NotPublicError(f"ngrok API returned no usable JSON: {exc}") from exc
    tunnels = body.get("tunnels") if isinstance(body, dict) else None
    found = {
        urlparse(str(t["public_url"])).scheme: str(t["public_url"])
        for t in tunnels or []
        if isinstance(t, dict) and t.get("public_url")
    }
    for scheme in SCHEMES:
        if scheme in found:
            return found[scheme]
    raise NotPublicError(f"ngrok API listed no {list(SCHEMES)} tunnel: {body!r}")


def read_ngrok_api(url: str = NGROK_API, timeout: float = 2.0) -> bytes:
    """Fetch :data:`NGROK_API`. Short timeout: it is a loopback call or nothing.

    Two seconds because the only two outcomes are an immediate answer from a
    local process and a connection refused. Waiting longer would delay startup
    for every team that uses Localtonet instead.
    """
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback
        return bytes(response.read())
