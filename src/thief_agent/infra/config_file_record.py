"""The locked-config record itself: its fields, its digest, its filename.

Split out of :mod:`.config_file`, which keeps the two operations that cross the
boundary of the process — locking parameters after validating them against
Appendix F, and reading a file back while recomputing what it claims. What
remains here is the value: the parameters the two sides agreed, the digest taken
over those parameters alone, and the canonical dictionary that is serialised.

Nothing in this module validates against Appendix F; construction only rejects a
record that could not describe a match at all. The digest and the serialisation
live here because they are properties of the value, and they are the bytes both
peers must produce identically.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..shared.config import config_sha256
from ..shared.naming import config_filename
from .report_reference import links


class ConfigFileError(ValueError):
    """Raised when a locked config cannot be built, read or trusted."""


_SELF_DESCRIBING = ("_note", "_schema", "schema_version")
"""Carried explicitly above rather than swept in with the terms.

``agreed_between`` is not on this list either: it is a term the digest covers,
so it must reach the file from :attr:`parameters` and not from the tuple beside
them. Writing the tuple instead put a key in the file that the digest had never
seen, and the file then failed its own verification.

``world`` is *not* on this list, though the reference's sample omits it. The
digest is taken over the agreed terms, and :func:`~.config_file.load`
recomputes it from what the file holds rather than trusting the stored value --
a hand edit travelling under a stale hash is the one thing it exists to catch.
Dropping a term would leave the file unable to verify itself, which is a worse
trade than one extra key against the sample."""

SCHEMA = "".join(
    [
        "Agreed game configuration for one match. Values come from the master parameter table ",
        "(Appendix F). Per the appendix's mandatory rules both teams must hold BYTE-IDENTICAL ",
        "values, lock them cryptographically (config_sha256), give the file a unique name per ",
        "game, and attach it to GitHub. 'status' recap: minimum = may only be raised; permanent ",
        "= must not change; negotiation = any agreed value.",
    ]
)
"""The reference's own description of this document, carried verbatim."""


@dataclass(frozen=True, slots=True)
class LockedConfig:
    """One sub-game's agreed parameters, with the digest that pins them."""

    game_id: str
    game_uid: str
    sub_game: int
    parameters: dict[str, Any]
    agreed_between: tuple[str, str]

    def __post_init__(self) -> None:
        if not self.game_uid:
            raise ConfigFileError("every artefact of a match shares a game_uid; this has none")
        if not self.parameters:
            raise ConfigFileError("a config with no parameters agrees to nothing")
        if len(set(self.agreed_between)) != 2:
            raise ConfigFileError(
                f"a config is agreed between two teams, got {self.agreed_between!r}"
            )
        config_filename(self.game_id, self.sub_game)  # validates both, raising NamingError

    @property
    def sha256(self) -> str:
        """The digest, over the parameters alone.

        Recomputed on every access rather than stored. A cached digest is a
        second copy of a fact that already exists, and the only way the two can
        differ is the way that matters.
        """
        return config_sha256(self.parameters)

    @property
    def filename(self) -> str:
        return config_filename(self.game_id, self.sub_game)

    def to_dict(self) -> dict[str, Any]:
        """The reference sample's layout: the agreed terms flat, not nested.

        ``config_sha256`` is unaffected -- it is taken over the negotiated terms
        through :func:`~..shared.config.canonical_bytes`, never over this
        rendering, so how the file arranges them cannot move the digest the two
        peers compare.
        """
        terms = {k: v for k, v in self.parameters.items() if k not in _SELF_DESCRIBING}
        return {
            "_schema": SCHEMA,
            "schema_version": str(self.parameters.get("schema_version", "1.1")),
            "_note": str(self.parameters.get("_note", "")),
            **terms,
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "sub_game_number": self.sub_game,
            "links": links(self.game_id),
            "config_name": self.filename,
            "config_sha256": self.sha256,
        }

    def agrees_with(self, their_sha256: str) -> bool:
        """Whether the opponent's digest matches ours. #121 refuses play if not."""
        return self.sha256 == their_sha256

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self.filename
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        return path
