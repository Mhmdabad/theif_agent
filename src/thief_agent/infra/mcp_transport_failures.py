"""Naming a transport failure, before anything decides what to do about it.

Split out of :mod:`.mcp_transport`, which re-exports every name here. The
vocabulary is not local colour: :class:`~.mcp_client.OpponentClient` classifies
by exception type, so what a failure is called here is what decides whether a
match is retried or lost.
"""

HTTP_CLIENT_MODULES = frozenset({"httpx", "httpcore"})
"""Libraries whose exceptions mean *the request never completed*.

``httpx.ConnectError`` is not an ``OSError``, not a ``RuntimeError``, and
carries no response — so it matched nothing in the retry vocabulary and
propagated raw out of a turn. That is the third variant of one mistake: the
retry budget classifies by exception type, and every layer between us and the
socket invents its own hierarchy. Rather than enumerate their classes, treat
*any* exception from the HTTP client that is not an HTTP status as what it is:
the request did not get through.
"""

UPSTREAM_DEAD = frozenset({502, 503, 504})
"""Statuses that mean *the proxy is fine, the peer behind it is not*.

Bad Gateway, Service Unavailable, Gateway Timeout. Deliberately not 4xx: a 404
or a 401 comes from something that answered, and retrying it three times before
declaring the opponent unreachable would report the wrong failure.
"""


def from_http_client(error: BaseException) -> bool:
    """Whether this came from the HTTP client rather than from our own code.

    Checked by module rather than by class for the reason the status is read by
    shape: the classes change between releases, and the first symptom of that
    here would be a match lost to an unhandled exception mid-turn.
    """
    return type(error).__module__.split(".")[0] in HTTP_CLIENT_MODULES


def why(error: BaseException) -> str:
    """The most specific text in the chain, for exceptions that often have none.

    ``httpx.ConnectError`` is routinely raised with an empty message, and its
    ``__cause__`` is frequently another empty one. Walking to the first thing
    that actually says something is the difference between a report and a
    class name.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        said = str(current).strip()
        if said:
            return f"{said} ({type(current).__name__})"
        current = current.__cause__ or current.__context__
    return f"{type(error).__name__} with no detail"


def upstream_status(error: object) -> int | None:
    """The HTTP status inside a client library's exception, if there is one.

    Read by shape rather than by importing ``httpx`` and catching its class, for
    the same reason :func:`~.gatekeeper.status_code_of` is: a rule that only
    works with one library stops working silently when a dependency changes
    underneath it, and the first symptom here would be a match lost to an
    unhandled exception in the middle of a turn.
    """
    code = getattr(getattr(error, "response", None), "status_code", None)
    return code if isinstance(code, int) else None
