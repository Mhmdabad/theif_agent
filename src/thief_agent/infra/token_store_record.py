"""The checked credential itself, as an object callers may hold.

Split out of :mod:`.token_store`, which re-exports these names; see its
module docstring for why each rule here exists.
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class StoredToken:
    """A credential read from disk, already checked.

    Holds the refresh token because refreshing needs it, and defines no
    ``__str__``: the default dataclass ``repr`` would print it, so callers must
    never log this object. :attr:`summary` is what is safe to show.
    """

    client_id: str
    refresh_token: str
    scopes: tuple[str, ...]
    expiry: datetime | None = None
    role: str = ""

    @property
    def expired(self) -> bool:
        """Whether the *access* token has run out. Not a problem — just a refresh."""
        return self.expiry is not None and self.expiry <= datetime.now(UTC)

    @property
    def summary(self) -> str:
        state = "expired" if self.expired else "current"
        return (
            f"token for client {self.client_id.split('.')[0]}… ({state}, {len(self.scopes)} scope)"
        )


ROLE_FIELD = "declared_role"
"""Which agent authorized. Ours, not Google's — see the module docstring."""
