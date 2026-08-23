# ruff: noqa: I001
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from thief_agent import reference_v3 as _reference_v3  # noqa: F401

from sparring.config import SparConfig
from sparring.transport.loopback import Inboxes

from thief_agent.counted_v3_contract import CANONICAL_SHA, RAW_SHA, canonical_bytes, load_contract
from thief_agent.counted_v3_step0_model import (
    StepZeroSpec,
    authenticated_preimage,
    build_payload,
    verify_payload,
)
from thief_agent.counted_v3_wire import build_server, step_zero_queue

FAKE_KEY = "test-only-counted-auth-secret"
KEY_ID = "mars777-counted-1"
MARS_COMMITS = {
    "police": "57622d841727f588dee45665b48c487dd6ee556f",
    "thief": "0e330cc5b6bc36002d21c475699cbf954c68217d",
}
S82_COMMITS = {"police": "d" * 40, "thief": "6" * 40}


def _team(group: str, members: list[str], police: str, thief: str) -> dict[str, Any]:
    return {
        "group_name": group,
        "members": members,
        "repos": {"cop": police, "thief": thief},
        "code_version": "1.02",
        "llm_model": "none-deterministic-agent" if group == "MaRs-777" else "template",
    }


MARS = _team(
    "MaRs-777",
    ["Mohamed Awad", "Rawey Sleiman"],
    "https://github.com/mohammedawad99/mars-777-police-agent",
    "https://github.com/mohammedawad99/mars-777-thief-agent",
)
S82 = _team(
    "s82kma9e",
    ["Mohammed Abad", "Muhammad Swalha"],
    "https://github.com/Mhmdabad/police_agent",
    "https://github.com/Mhmdabad/theif_agent",
)


def _spec(ours: str, token_budget: int = 200000) -> StepZeroSpec:
    mars = ours == "MaRs-777"
    expected: dict[str, str | None] = dict(S82_COMMITS if mars else MARS_COMMITS)
    return StepZeroSpec(
        game_id="MaRs-777-vs-s82kma9e",
        game_uid="43994252-2e4d-2b5c-9baa-4bf7aef5b5d6",
        group_id=ours,
        opponent_group="s82kma9e" if mars else "MaRs-777",
        public_url="https://example.invalid/mcp",
        token_budget=token_budget,
        own_team=MARS if mars else S82,
        peer_team=S82 if mars else MARS,
        own_commits=MARS_COMMITS if mars else S82_COMMITS,
        expected_peer_commits=expected,
        key_id=KEY_ID,
        secret=FAKE_KEY,
    )


def test_frozen_game_contract_hashes() -> None:
    path = Path("config/game.json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == RAW_SHA
    assert hashlib.sha256(canonical_bytes(load_contract())).hexdigest() == CANONICAL_SHA


def test_step_zero_v2_golden_vector() -> None:
    hardware = {
        "os": "Linux",
        "cpu_cores": 8,
        "cpu_freq_ghz": "2.4",
        "ram_gb": 16,
        "gpu": False,
    }
    payload = build_payload(
        _spec("MaRs-777", 100000),
        started_at="2026-08-23T12:00:00Z",
        hardware=hardware,
    )
    declaration = payload["declaration"]
    assert declaration["teams"]["group_a"]["hardware"]["cpu_freq_ghz"] == "2.4"
    preimage = authenticated_preimage(declaration, "group_a")
    assert json.loads(preimage[5:])["teams"]["group_a"]["hardware"]["cpu_freq_ghz"] == 2.4
    assert len(preimage) == 732
    assert hashlib.sha256(preimage).hexdigest() == (
        "f135f40bcbe5002de423d0508cba49ffef26e0d18525d5f38af00a397601a74f"
    )
    assert payload["auth"]["value"] == (
        "07246bbe1efa3509b0891f2da78542aa15d44d05390c121ca9ab6f69a5b9731f"
    )
    decoded_wire = json.loads(json.dumps(payload, ensure_ascii=False))
    assert verify_payload(decoded_wire, _spec("s82kma9e", 100000)) == MARS_COMMITS


def test_each_producer_uses_explicit_null_and_verifies() -> None:
    mars_payload = build_payload(_spec("MaRs-777"))
    assert mars_payload["declaration"]["teams"]["group_b"] is None
    assert verify_payload(mars_payload, _spec("s82kma9e")) == MARS_COMMITS
    s82_payload = build_payload(_spec("s82kma9e"))
    assert s82_payload["declaration"]["teams"]["group_a"] is None
    assert verify_payload(s82_payload, _spec("MaRs-777")) == S82_COMMITS


def test_tampered_role_commit_is_refused() -> None:
    payload = json.loads(json.dumps(build_payload(_spec("MaRs-777"))))
    payload["declaration"]["teams"]["group_a"]["github_commits"]["police"] = "f" * 40
    with pytest.raises(ValueError, match="commit|HMAC"):
        verify_payload(payload, _spec("s82kma9e"))


def test_real_fastmcp_surface_routes_step_zero_and_game_negotiate() -> None:
    inboxes = Inboxes()

    async def calls() -> None:
        async with Client(build_server(SparConfig(), inboxes)) as client:
            await client.call_tool("negotiate", {"kind": "step0", "payload": {"x": 1}})
            await client.call_tool("negotiate", {"message": {"terms": {}}})

    asyncio.run(calls())
    assert step_zero_queue(inboxes).popleft() == {"x": 1}
    assert inboxes.agreements.popleft() == {"terms": {}}
