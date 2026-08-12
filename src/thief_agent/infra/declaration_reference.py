"""The declaration document, in the shape the lecturer's own tooling reads.

Modelled on ``docs/sample-run/declaration_*.json`` in the reference. One
document describes **both** teams: each is an entry under ``groups`` carrying
its own identity, repositories, MCP addresses, model, hardware and signature.

That shape answers a question our old one could not. Naming the opponent's
repositories in *our* document required us to know them, and nothing tells us:
the greeting carries a role, a group id, a URL and a protocol version. So the
fields sat in the private config as ``OPPONENT_GROUP_ID`` placeholders, and a
placeholder in a signed pre-game document is worse than an absent field.

Here each side declares its own half and signs it. What we cannot observe is
recorded as ``null`` rather than guessed, which is a statement a reader can act
on: the opponent's hardware is unknown to us because they never sent it, and
their own copy of this document is where it is known.

Roles are deliberately absent. They alternate every sub-game, so a role in a
document about the whole series would be wrong five times out of six.
"""

from typing import TYPE_CHECKING, Any

from .report_reference import SCHEMA_VERSION, TIMEZONE, links

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from .declaration_record import MatchDeclaration

__all__ = ["declaration_document", "hardware_spec"]


def hardware_spec(hardware: dict[str, Any] | None) -> dict[str, Any]:
    """Our hardware in the reference's units: GB rather than MB, GHz labels.

    ``None`` throughout when a probe found nothing, which is the honest answer
    on a machine whose kernel does not expose it -- and distinguishable from a
    zero, which would claim a measurement.
    """
    probe = hardware or {}
    ram_mb, vram_mb = probe.get("ram_mb"), probe.get("vram_mb")
    return {
        "cpu_type": probe.get("os"),
        "cpu_freq_mhz": probe.get("cpu_max_mhz"),
        "cpu_cores": probe.get("logical_cores"),
        "ram_gb": round(ram_mb / 1024, 1) if ram_mb else None,
        "gpu_model": probe.get("gpu"),
        "vram_gb": round(vram_mb / 1024, 1) if vram_mb else None,
    }


def _ours(declaration: "MatchDeclaration") -> dict[str, Any]:
    """Our own entry: everything we can state about this machine, signed."""
    return {
        "group_id": declaration.us.name,
        "group_name": declaration.us.name,
        "members": list(declaration.us.members),
        "repos": {"cop": declaration.us.cop_repo, "thief": declaration.us.thief_repo},
        "mcp_servers": dict.fromkeys(("cop", "thief"), declaration.endpoints.ours),
        "llm_model": declaration.llm_model,
        "hardware_spec": hardware_spec(declaration.hardware.to_dict()),
        "signature": declaration.signature,
    }


def _theirs(declaration: "MatchDeclaration") -> dict[str, Any]:
    """The opponent's entry, holding only what they actually told us.

    Their URL arrives in the greeting and their group id with it. Their
    hardware, model and signature do not cross the wire at all, so they are
    ``null`` here: this is our copy of the document, and theirs is the one that
    can fill them in.
    """
    them = declaration.them
    return {
        "group_id": them.name,
        "group_name": them.name,
        "members": list(them.members),
        "repos": {"cop": them.cop_repo, "thief": them.thief_repo},
        "mcp_servers": dict.fromkeys(("cop", "thief"), declaration.endpoints.theirs),
        "llm_model": None,
        "hardware_spec": hardware_spec(None),
        "signature": None,
    }


def declaration_document(declaration: "MatchDeclaration") -> dict[str, Any]:
    """The whole declaration, as the reference lays it out.

    ``group_1`` is us and ``group_2`` is the opponent. The reference numbers
    them without assigning meaning, so the only rule that matters is that each
    entry is internally consistent -- and ours is the one we can sign.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "declaration_type": "pre_game_declaration",
        "game_id": declaration.game_id,
        "game_uid": declaration.game_uid,
        "links": links(declaration.game_id),
        "timezone": TIMEZONE,
        "game_started_at": declaration.started_at,
        "game_ended_at": declaration.ended_at,
        "num_sub_games": declaration.num_sub_games,
        "max_tokens_per_game": declaration.token_ceiling,
        "groups": {"group_1": _ours(declaration), "group_2": _theirs(declaration)},
    }
