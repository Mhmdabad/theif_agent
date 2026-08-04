"""The public address this peer is reachable at.

Most machines sit behind NAT and a firewall, so the server binding ``0.0.0.0``
is necessary but not sufficient: nobody outside can route to it. A tunnel
(ngrok, Localtonet) performs the NAT traversal and hands back a public URL —
and from the opponent's side that URL is the *entire* description of us.

**This module does not start a tunnel.** Spawning ``ngrok`` as a subprocess
would bind the agent to one vendor's binary, put a network dependency in the
test suite, and — worse — make the match depend on a process we manage badly.
The tunnel is an operational thing, started beside the agent (see
``docs/TUNNELING.md``); what the code owns is *discovering* the resulting URL
and *refusing to advertise a bad one*.

That refusal is the point of the module. Handing an opponent
``http://127.0.0.1:8801/mcp`` is not a small mistake: they cannot reach it,
every call times out, the deadline tracker converts that into a technical loss,
and a technical loss scores **zero for both sides**. The failure surfaces at
first contact with another team, at the worst possible moment, and looks
exactly like their fault. Checking at startup costs nothing and turns it into a
message on our own terminal.

The check is deliberately conservative about what it *rejects*, not about what
it accepts. An address literal can be classified with certainty, so private and
loopback ranges are refused outright. A hostname cannot be classified without
resolving it, and resolution would make a pure function depend on the network —
so a name is accepted unless it is one of the reserved local forms. We would
rather let an unusual name through than fail a legitimate tunnel host because
DNS was slow.
"""

import ipaddress
import json
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

MCP_PATH = "/mcp"
"""Where FastMCP's HTTP transport serves. A URL without a path gets this one."""

PUBLIC_URL_ENV = "PUBLIC_URL"
"""Explicit override, checked first.

Vendor-neutral on purpose: ngrok has a local API, Localtonet does not, and a
league match is not the place to discover that our discovery only speaks one
dialect. Whatever the tunnel is, its URL can be pasted into an environment
variable.
"""

NGROK_API = "http://127.0.0.1:4040/api/tunnels"
"""The ngrok agent's local inspection API. Loopback by nature — it is ours."""

SCHEMES = ("https", "http")
"""Accepted schemes, in preference order. HTTPS first when a tunnel offers both."""

LOCAL_NAMES = frozenset({"localhost", ""})
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
"""Reserved names that are never routable from outside this network."""


class NotPublicError(ValueError):
    """Raised when a URL could not be reached by an opponent elsewhere.

    A hard error rather than a warning. A warning about an unreachable address
    is a warning nobody reads until the match is already lost.
    """


def host_is_public(host: str) -> bool:
    """Whether ``host`` could be routed to from another machine on the internet.

    Address literals are decided by :mod:`ipaddress`, which knows every
    reserved range rather than the two everyone remembers. Names are decided by
    the reserved-suffix list; anything else is taken on trust, because deciding
    it properly means a DNS lookup and this must stay a pure function.
    """
    name = host.strip().lower().strip("[]")
    if name in LOCAL_NAMES or name.endswith(LOCAL_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return True
    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def normalise(raw: str, path: str = MCP_PATH) -> str:
    """Canonicalise a tunnel URL into the form the opponent will call.

    A tunnel prints its base address (``https://a1b2.ngrok-free.app``), while
    the opponent needs the MCP endpoint on it. Appending the path here rather
    than expecting whoever copies the URL to remember removes the most likely
    transcription error in the whole handshake.

    Raises:
        NotPublicError: if the scheme is unusable or the host is missing.
    """
    parsed = urlparse(raw.strip())
    if parsed.scheme not in SCHEMES:
        raise NotPublicError(f"{raw!r} must use one of {list(SCHEMES)}, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise NotPublicError(f"{raw!r} has no host")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or path, "", "", ""))


@dataclass(frozen=True, slots=True)
class PublicEndpoint:
    """A verified public address for one peer's MCP server."""

    url: str

    def __post_init__(self) -> None:
        canonical = normalise(self.url)
        object.__setattr__(self, "url", canonical)
        host = urlparse(canonical).hostname or ""
        if not host_is_public(host):
            raise NotPublicError(
                f"{canonical} is not reachable from another machine (host {host!r}); "
                "start a tunnel and advertise the address it prints. Running on "
                "localhost is permitted only during early coding."
            )

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""

    @property
    def secure(self) -> bool:
        """Whether the tunnel terminates TLS. Recorded, not required."""
        return urlparse(self.url).scheme == "https"


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


def discover(
    environ: Mapping[str, str],
    ngrok_reader: Callable[[], str | bytes] | None = read_ngrok_api,
) -> PublicEndpoint | None:
    """The address to advertise, or ``None`` when this peer is not exposed yet.

    ``None`` rather than an error, because ``localhost`` is explicitly
    permitted while coding and an agent that refused to start without a tunnel
    would make the whole local test loop conditional on a running tunnel.
    Refusal happens where it matters — at the handshake, where an unreachable
    address would be handed to an opponent.

    An explicit :data:`PUBLIC_URL_ENV` beats discovery, and a *bad* explicit
    value raises rather than falling through. Someone who set the variable
    meant to expose this peer; silently ignoring their typo and playing on
    localhost is the outcome they would least want.
    """
    explicit = environ.get(PUBLIC_URL_ENV, "").strip()
    if explicit:
        return PublicEndpoint(explicit)
    if ngrok_reader is None:
        return None
    try:
        payload = ngrok_reader()
    except OSError:
        return None
    return PublicEndpoint(from_ngrok(payload))
