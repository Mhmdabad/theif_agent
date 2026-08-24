"""Load and pin the current opponent's byte-frozen counted contract."""
# ruff: noqa: ANN401

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

RAW_SHA = "a91f9c43e503cf31a99533f88a2d22c9c8f68497426fd8a9b71cdf113990cb35"
CANONICAL_SHA = "e549689465dcefd63aaa5e7e829237d65eb07fb830ff32a7d58a3d6d512d131a"
TERMS_SHA = "ad9e1bfd724e9debcde523833381cb7982a5d619d693d3738b59e0da61f4d81a"
SCENT_MODEL = "subtractive_chebyshev_v1"
SCENT_SHA = "81ebee59640e80eae8ca9ee5f86abd26e7edf5cdbb27d15925cb6ee45ca6ddf4"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def load_contract(path: Path = Path("config/game.json")) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise RuntimeError("config/game.json is not the byte-frozen counted contract")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise RuntimeError("config/game.json is not an object")
    if hashlib.sha256(canonical_bytes(body)).hexdigest() != CANONICAL_SHA:
        raise RuntimeError("config/game.json canonical hash is not the frozen value")
    pheromones = body.get("pheromones", {})
    if (pheromones.get("model_id"), pheromones.get("registration_sha256")) != (
        SCENT_MODEL,
        SCENT_SHA,
    ):
        raise RuntimeError("counted scent registration differs from the frozen contract")
    return cast(dict[str, Any], body)
