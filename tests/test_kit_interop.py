"""Direct pins from the vendored cohort interoperability kit."""

import json
from pathlib import Path

import pytest

from thief_agent.infra.declaration import Team
from thief_agent.infra.handshake import Greeting, HandshakeError, Peering
from thief_agent.shared.pairing_identity import validate_pairing_identity
from thief_agent.shared.result_claim import claim_sha256

KIT = Path(__file__).parents[1] / "compat" / "copthief_league_protocol"


def team(name: str) -> Team:
    return Team(
        name, ("Member",), f"https://github.com/{name}/cop", f"https://github.com/{name}/thief"
    )


def greeting(role: str, group: str) -> Greeting:
    return Greeting(role, group, f"https://{group}.example/mcp", "1.0")


def pairing() -> tuple[Team, Team, Greeting, Peering]:
    us, them = team("z-team"), team("a-team")
    ours, theirs = greeting("police", us.name), greeting("thief", them.name)
    return us, them, ours, Peering(ours, theirs, 1)


def test_settlement_hash_matches_the_kit_vector() -> None:
    fixture = json.loads((KIT / "vectors" / "report_consensus.json").read_text())
    vector = fixture["vectors"][0]
    assert claim_sha256(vector["report"]) == vector["signature"]
    assert claim_sha256(vector["report"]) != vector["compact_form_sha256"]


def test_sorted_wire_pair_is_accepted() -> None:
    us, them, ours, peering = pairing()
    validate_pairing_identity("a-team-vs-z-team", us, them, ours, peering)


def test_placeholder_game_id_is_refused() -> None:
    us, them, ours, peering = pairing()
    with pytest.raises(HandshakeError, match="sorted group pair"):
        validate_pairing_identity("THEIR_GROUP-vs-z-team", us, them, ours, peering)


def test_stale_opponent_config_is_refused() -> None:
    us, _, ours, peering = pairing()
    with pytest.raises(HandshakeError, match="peer announced"):
        validate_pairing_identity("a-team-vs-z-team", us, team("old-team"), ours, peering)
