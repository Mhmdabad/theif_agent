"""Frozen one-series Step-0 V2 declaration and HMAC profile."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from .counted_v3_step0_hardware import collect_hardware, decode_frequency
from .counted_v3_step0_peer import validate_declaration


@dataclass(frozen=True)
class StepZeroSpec:
    game_id: str
    game_uid: str
    group_id: str
    opponent_group: str
    public_url: str
    game_start: str
    token_budget: int
    own_team: dict[str, Any]
    peer_team: dict[str, Any]
    own_commits: dict[str, str]
    expected_peer_commits: dict[str, str | None]
    key_id: str
    secret: str


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _slot(group_id: str, opponent: str) -> str:
    ordered = sorted((group_id, opponent))
    return "group_a" if group_id == ordered[0] else "group_b"


def _team(spec: StepZeroSpec, hardware: dict[str, Any] | None = None) -> dict[str, Any]:
    team = spec.own_team
    return {
        "group_id": spec.group_id,
        "group_name": team["group_name"],
        "members": team["members"],
        "repos": {"police": team["repos"]["cop"], "thief": team["repos"]["thief"]},
        "github_commits": spec.own_commits,
        "mcp_endpoint": spec.public_url,
        "hardware": hardware or collect_hardware(),
        "llm_model": team.get("llm_model", "template"),
        "code_version": team["code_version"],
    }


def _core(declaration: dict[str, Any], slot: str) -> dict[str, Any]:
    team = dict(declaration["teams"][slot])
    hardware = dict(team["hardware"])
    hardware["cpu_freq_ghz"] = decode_frequency(hardware.get("cpu_freq_ghz"))
    team["hardware"] = hardware
    return {
        "game_id": declaration["game_id"],
        "game_uid": declaration["game_uid"],
        "teams": {slot: team},
        "times": {"game_start": declaration["times"]["game_start"]},
        "token_budget_per_series": declaration["token_budget_per_series"],
    }


def authenticated_preimage(declaration: dict[str, Any], slot: str) -> bytes:
    return b"step0" + _canonical(_core(declaration, slot))


def _mac(declaration: dict[str, Any], slot: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), authenticated_preimage(declaration, slot), hashlib.sha256
    ).hexdigest()


def build_payload(
    spec: StepZeroSpec,
    *,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slot = _slot(spec.group_id, spec.opponent_group)
    teams: dict[str, dict[str, Any] | None] = {"group_a": None, "group_b": None}
    teams[slot] = _team(spec, hardware)
    declaration = {
        "game_id": spec.game_id,
        "game_uid": spec.game_uid,
        "token_budget_per_series": spec.token_budget,
        "times": {
            "game_start": spec.game_start,
            "game_end": None,
        },
        "teams": teams,
    }
    return {
        "declaration": declaration,
        "auth": {
            "profile": "HMAC_SHA256",
            "key_id": spec.key_id,
            "value": _mac(declaration, slot, spec.secret),
        },
    }


def verify_payload(payload: dict[str, Any], spec: StepZeroSpec) -> dict[str, str]:
    declaration, auth = payload.get("declaration"), payload.get("auth")
    if not isinstance(declaration, dict) or not isinstance(auth, dict):
        raise ValueError("Step-0 lacks declaration/auth objects")
    if auth.get("profile") != "HMAC_SHA256" or auth.get("key_id") != spec.key_id:
        raise ValueError("Step-0 authentication profile or key_id mismatch")
    validate_declaration(declaration, spec)
    slot = _slot(spec.opponent_group, spec.group_id)
    expected = _mac(declaration, slot, spec.secret)
    if not hmac.compare_digest(str(auth.get("value", "")), expected):
        raise ValueError("Step-0 HMAC verification failed")
    commits = declaration["teams"][slot]["github_commits"]
    return {role: str(value) for role, value in commits.items()}
