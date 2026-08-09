"""Saying what went wrong, even when the exception itself says nothing.

Pulled out of the command module because it is diagnosis, not command-line
handling: the walk over cause chains and exception groups has its own rules,
its own depth bound, and its own history of going wrong.
"""


def safely_describe(exc: BaseException) -> str:
    """:func:`describe_failure`, but incapable of replacing a failure with its own.

    A reporter that raises turns a diagnosable problem into an unrelated
    traceback and loses the original entirely. That happened once here, so the
    call is wrapped: whatever goes wrong inside, the caller still gets the
    ``repr`` it would have had anyway.
    """
    try:
        return describe_failure(exc)
    except Exception as broke:  # noqa: BLE001 - a broken reporter must still report
        return f"{exc!r} (the failure description itself failed: {broke!r})"


def describe_failure(exc: BaseException) -> str:
    """Say what went wrong, even when the exception itself says nothing.

    ``f"{exc}"`` is empty for a surprising number of real failures, and a match
    that ends with ``the match did not finish:`` and nothing after the colon is
    worse than a traceback — it reports that something happened and withholds
    every fact about it. That is not hypothetical: it is how the sixth live
    warm-up ended, after the run had played most of a sub-game.

    Three shapes get in the way and each is unwrapped here:

    * **Exception groups.** ``anyio`` and the MCP client raise them, and the
      group's own message is often blank while the exceptions inside it are the
      whole story.
    * **Multi-argument exceptions.** ``MatchAborted(TechnicalLoss.TIMEOUT, why)``
      renders as a bare tuple with an enum ``repr`` in it. Joining the arguments
      says the same thing in words.
    * **Genuinely silent exceptions.** Some carry no message at all; then the
      class name and the cause are all there is, so both are printed rather
      than an empty string.

    **The walk is guarded, because the graph is not a tree.** A group can hold
    an exception whose ``__context__`` is the group, and ``anyio`` re-raising
    across task boundaries produces exactly that. The first version of this
    function had no guard and recursed until the interpreter gave up — so a
    helper written to stop a run from failing silently instead made it fail
    loudly, in the error handler, taking the traceback with it. Diagnostics
    must not be able to do that, so cycles and depth are both bounded.
    """
    return _describe(exc, set(), 0)


MAX_DEPTH = 8
"""How far down a cause chain to walk. Deeper is noise, not diagnosis."""


def _describe(exc: BaseException, seen: set[int], depth: int) -> str:
    """One node of the walk. ``seen`` holds ids, because exceptions are unhashable-ish.

    Identity rather than equality: two distinct exceptions can compare equal,
    and collapsing them would hide one of them.
    """
    if id(exc) in seen or depth > MAX_DEPTH:
        return type(exc).__name__
    seen.add(id(exc))

    inner = getattr(exc, "exceptions", None)
    if isinstance(inner, (list, tuple)) and inner:
        parts = [_describe(one, seen, depth + 1) for one in inner]
        return "; ".join(dict.fromkeys(parts))

    said = "; ".join(part for part in (str(a).strip() for a in exc.args) if part)
    if not said:
        said = str(exc).strip()
    label = type(exc).__name__
    if said:
        return said if label in said else f"{said} ({label})"

    because = exc.__cause__ or exc.__context__
    if because is not None:
        return f"{label}, which carried no message; caused by {_describe(because, seen, depth + 1)}"
    return f"{label} with no message — nothing recorded why, which is itself the bug"
