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

from collections.abc import Callable, Mapping

from .tunnel_address import (
    LOCAL_NAMES,
    LOCAL_SUFFIXES,
    MCP_PATH,
    SCHEMES,
    NotPublicError,
    PublicEndpoint,
    host_is_public,
    normalise,
)
from .tunnel_ngrok import NGROK_API, from_ngrok, read_ngrok_api

__all__ = [
    "LOCAL_NAMES",
    "LOCAL_SUFFIXES",
    "MCP_PATH",
    "NGROK_API",
    "PUBLIC_URL_ENV",
    "SCHEMES",
    "NotPublicError",
    "PublicEndpoint",
    "discover",
    "from_ngrok",
    "host_is_public",
    "normalise",
    "read_ngrok_api",
    "rehearsal_url",
]

PUBLIC_URL_ENV = "PUBLIC_URL"
"""Explicit override, checked first.

Vendor-neutral on purpose: ngrok has a local API, Localtonet does not, and a
league match is not the place to discover that our discovery only speaks one
dialect. Whatever the tunnel is, its URL can be pasted into an environment
variable.
"""


def rehearsal_url(environ: Mapping[str, str], port: int = 8801, path: str = MCP_PATH) -> str:
    """The address to advertise during a **solo rehearsal**, loopback allowed.

    :class:`PublicEndpoint` refuses a loopback host, which is right: announcing
    ``127.0.0.1`` to another team means every call they make times out. It also
    makes it impossible to run this project's two agents against each other on
    one machine, and the rulebook permits localhost during early coding.

    That matters more than it sounds. A rehearsal over a public tunnel opens a
    fresh TLS connection per tool call, and a free tunnel stops accepting them
    long before a sub-game finishes — so the network, not the game, decides how
    far a practice run gets. Over loopback there is no tunnel to exhaust.

    Separate from :func:`discover` on purpose: a caller has to name the
    rehearsal to get the relaxed rule, so nothing on the league path can reach
    it by forgetting a flag.

    Raises:
        NotPublicError: on a malformed address. Being a rehearsal excuses a
            private host, not a typo.
    """
    return normalise(environ.get(PUBLIC_URL_ENV, "").strip() or f"http://127.0.0.1:{port}", path)


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
