"""What counts as an address another team can actually reach.

The classifier, the canonical form and the verified endpoint type live together
because they are one decision taken in three places: :func:`host_is_public`
decides, :func:`normalise` puts the URL in the shape the opponent will call, and
:class:`PublicEndpoint` is the value that cannot exist unless both agreed.

Split out of :mod:`.tunnel`, which re-exports every name here.
"""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

MCP_PATH = "/mcp"
"""Where FastMCP's HTTP transport serves. A URL without a path gets this one."""

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
