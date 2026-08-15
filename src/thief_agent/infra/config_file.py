"""``config_<game_id>_g<NN>.json`` — the physics both sides agreed, locked.

One per sub-game. It carries every quantitative parameter from Appendix F, and
its whole purpose is that the two copies are **identical**: the same board, the
same decay, the same barrier quota, the same scoring. A disagreement here is not
a disagreement about tactics, it is two agents playing different games and
reporting incompatible results.

So the file is written with its own digest inside it, and the digest is what the
two peers exchange (#121). Three consequences shape this module:

**The digest covers the parameters, not the file.** ``config_sha256`` is taken
over the canonical bytes of the parameters alone — never over the object that
already contains the digest. That is the same rule as the declaration's
signature, for the same reason: a hash of a document containing its own hash
cannot be recomputed by anybody, including us.

**Appendix F is checked before anything is locked.** A *fixed* parameter that
deviates disqualifies the team, and locking a bad value would produce a file
that is cryptographically perfect and disqualifying. :func:`~..shared.config.validate`
runs first, so the failure is "this config is illegal" rather than "both sides
agreed on something that loses the match".

**Loading verifies.** :func:`load` recomputes the digest from the parameters it
just read and refuses a file whose stored digest does not match. A config file
is committed to the repository (Appendix F, mandatory rule 4) and therefore
edited by hand sometimes; a loader that trusted the stored digest would let a
hand edit travel under a hash that no longer describes it.
"""

import json
from pathlib import Path
from typing import Any

from ..shared.config import ConfigError, config_sha256, validate
from .config_file_record import ConfigFileError, LockedConfig

__all__ = [
    "ConfigFileError",
    "LockedConfig",
    "load",
    "lock",
]


def lock(
    *,
    game_id: str,
    game_uid: str,
    sub_game: int,
    parameters: dict[str, Any],
    agreed_between: tuple[str, str],
) -> LockedConfig:
    """Validate against Appendix F, then lock.

    Raises:
        ConfigFileError: if the parameters violate Appendix F. Checked *before*
            locking, so the failure reads as "this config is illegal" rather
            than producing a cryptographically perfect file that disqualifies
            the team the moment an auditor opens it.
    """
    try:
        validate(parameters)
    except ConfigError as exc:
        raise ConfigFileError(
            f"refusing to lock a config that violates Appendix F: {exc}. A *fixed* "
            "parameter that deviates disqualifies the team, and a locked bad value "
            "is still a bad value"
        ) from exc
    return LockedConfig(
        game_id=game_id,
        game_uid=game_uid,
        sub_game=sub_game,
        parameters=parameters,
        agreed_between=agreed_between,
    )


_NOT_A_TERM = frozenset(
    {"_schema", "game_id", "game_uid", "sub_game_number", "links", "config_name", "config_sha256"}
)
"""Keys the file carries about *itself*. Everything else is an agreed term, and
the digest is recomputed over exactly that -- so the flat layout the reference
uses still verifies, because nothing the digest covers was left out of it."""


def load(path: Path) -> LockedConfig:
    """Read a locked config, recomputing its digest rather than trusting it.

    Config files are committed to the repository, so they get opened, diffed
    and occasionally edited. A loader that believed the stored digest would let
    a hand edit travel under a hash that no longer describes it — which is the
    one thing the digest exists to prevent.

    Raises:
        ConfigFileError: on unreadable JSON, a missing field, or a digest that
            does not match the parameters beside it.
    """
    try:
        body = json.loads(path.read_text())
    except OSError as exc:
        raise ConfigFileError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigFileError(f"{path.name} is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ConfigFileError(f"{path.name} is not a config object")

    missing = [
        name
        for name in ("game_id", "game_uid", "sub_game_number", "config_sha256")
        if name not in body
    ]
    if missing:
        raise ConfigFileError(f"{path.name} is missing {missing}")
    parameters = {k: v for k, v in body.items() if k not in _NOT_A_TERM}
    if not all(isinstance(v, dict | list | str | int | float) for v in parameters.values()):
        raise ConfigFileError(f"{path.name} has parameters that are not an object")

    recomputed = config_sha256(parameters)
    if recomputed != body["config_sha256"]:
        raise ConfigFileError(
            f"{path.name} carries digest {str(body['config_sha256'])[:16]}… but its "
            f"parameters produce {recomputed[:16]}…; the file has been edited since it "
            "was locked, and the two peers no longer agree on the same game"
        )

    agreed = body.get("agreed_between", [])
    if not isinstance(agreed, list) or len(agreed) != 2:
        raise ConfigFileError(f"{path.name} does not name two teams")

    return LockedConfig(
        game_id=str(body["game_id"]),
        game_uid=str(body["game_uid"]),
        sub_game=int(body["sub_game_number"]),
        parameters=parameters,
        agreed_between=(str(agreed[0]), str(agreed[1])),
    )
