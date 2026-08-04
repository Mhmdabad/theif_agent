"""Which Gmail permissions this agent asks for, and which it refuses to hold.

The agent sends one kind of message to one hard-coded address. That is the
entire mail requirement, and ``gmail.send`` is the entire scope it needs.

**Least privilege here is not paperwork.** ``token.json`` is a file on a student
laptop that grants whatever the scope says, and it is one careless commit away
from being public. Granted `gmail.send`, a stolen token can send mail as the
account — bad, noisy, recoverable. Granted `gmail.readonly` as well, the same
file hands over years of the account owner's correspondence, permanently and
silently. FR-7.25 is right to call the narrow scope the difference between a
weapon and a nearly harmless tool.

So there are two defences, and they guard different failure modes:

* **What we ask for** — :data:`SCOPES` is the only scope list in the package,
  and ``test_only_the_send_scope_appears_anywhere_in_the_source`` reads the
  source tree to keep it the only one. That stops the scope creeping wider in
  some future edit, which is how it actually happens: never deliberately, always
  as one extra string added beside working code.

* **What we were granted** — :func:`check_granted` refuses a token that carries
  more than we asked for. Asking narrowly does not guarantee receiving narrowly.
  Google returns the scopes actually granted, and if the same client was
  authorized more broadly at some earlier point the response can come back with
  the union. A token we did not ask for the power of is still a token that has
  it, and using it would mean the least-privilege argument was never true.

Nothing here talks to Google. Deciding what we are allowed to do is a separate
question from doing it, and a policy module that needed the network could not be
tested against the case that matters.
"""

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
"""Permission to send as the account. Not to read, not to modify, not to list."""

SCOPES: tuple[str, ...] = (SEND_SCOPE,)
"""The complete set this agent requests. The only scope list in the package.

A tuple rather than a list so it cannot be appended to by accident, and named
in the plural because that is the shape every Google client library wants —
matching their signature here avoids someone constructing a second list at the
call site, which is precisely the thing this module exists to prevent.
"""


class ScopeError(PermissionError):
    """Raised when a credential carries authority this agent will not hold."""


def check_granted(granted: object) -> tuple[str, ...]:
    """Accept a granted scope list only if it is exactly what we asked for.

    Args:
        granted: whatever the token file or the auth library reported. Typed
            loosely because it arrives from parsed JSON, where a single scope
            may be a bare string and a missing one may be ``None`` — and a
            module whose job is refusing bad input should not crash on it.

    Returns:
        The granted scopes, normalised to a tuple.

    Raises:
        ScopeError: if anything was granted beyond :data:`SCOPES`, if the send
            scope is missing, or if the value is not a scope list at all.

    Extra scope is refused rather than trimmed. Trimming would describe a token
    as narrow while the token itself remains broad — the file on disk is what an
    attacker gets, and it does not read our variables. The only real remedy is
    to revoke it and authorize again, so this raises and says so.
    """
    if isinstance(granted, str):
        granted = granted.split()
    if not isinstance(granted, (list, tuple)) or not all(
        isinstance(scope, str) for scope in granted
    ):
        raise ScopeError(f"expected a list of scope strings, got {granted!r}")

    held = tuple(granted)
    extra = sorted(set(held) - set(SCOPES))
    if extra:
        raise ScopeError(
            f"this credential also grants {extra}, which this agent will not hold; "
            "revoke it at https://myaccount.google.com/permissions and authorize "
            "again — trimming the list here would leave the token itself just as wide"
        )
    if SEND_SCOPE not in held:
        raise ScopeError(f"credential grants {list(held)}, which cannot send mail")
    return held
