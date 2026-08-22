"""Build and persist the frozen counted Step-0 context."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sparring import kitref

from .counted_v3_contract import canonical_bytes
from .counted_v3_step0_model import StepZeroSpec


def step_zero_spec(
    args: argparse.Namespace,
    private: dict[str, Any],
    shared: dict[str, Any],
    terms: dict[str, Any],
    commits: dict[str, str],
) -> StepZeroSpec:
    key_id = os.getenv("COUNTED_STEP0_KEY_ID", "")
    secret = os.getenv("COUNTED_STEP0_SECRET", "")
    if not key_id or not secret:
        raise RuntimeError("COUNTED_STEP0_KEY_ID and COUNTED_STEP0_SECRET are required")
    own = dict(private["game"])
    own["code_version"] = private["version"]
    own["llm_model"] = private.get("llm", {}).get("model", "template")
    peer = private["teams"]["them"]
    return StepZeroSpec(
        game_id=kitref.game_id(args.group_id, args.opponent_group),
        game_uid=kitref.game_uid(terms, args.group_id, args.opponent_group),
        group_id=args.group_id,
        opponent_group=args.opponent_group,
        public_url=args.public,
        token_budget=int(shared["network_and_league"]["token_budget_per_series"]),
        own_team=own,
        peer_team=peer,
        own_commits=commits,
        expected_peer_commits={
            "police": args.opponent_cop_commit,
            "thief": args.opponent_thief_commit,
        },
        key_id=key_id,
        secret=secret,
    )


def arm_consensus(shared: dict[str, Any]) -> None:
    series = shared["series_protocol"]
    os.environ["SERIES_CONSENSUS"] = "1"
    os.environ["SERIES_CONSENSUS_TIMEOUT"] = str(series["consensus_timeout_sec"])
    os.environ["SERIES_CONSENSUS_RETRY"] = str(series["consensus_retry_sec"])


def save_step_zero(
    directory: Path, game_id: str, ours: dict[str, Any], theirs: dict[str, Any]
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"step0_{game_id}.json"
    path.write_bytes(canonical_bytes({"ours": ours, "theirs": theirs}))
    return path
