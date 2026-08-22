"""Load and pin the byte-frozen MaRs-777 counted contract."""
# ruff: noqa: ANN401

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

RAW_SHA = "2b401af481725fcf50e9143d44c50ab712b976e688b54cecd061b4546a60fbef"
CANONICAL_SHA = "290b4bcefc3824868d47070eade2564b0ecdb0b78560e163db348000b4caa1fb"
TERMS_SHA = "ad9e1bfd724e9debcde523833381cb7982a5d619d693d3738b59e0da61f4d81a"
SCENT_MODEL = "multiplicative_book_v1"
SCENT_SHA = "934c220d5bf62acaa3297c6c9d723ea954c220260b02292ca17f6d5daef9f4d9"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def load_contract(path: Path = Path("config/game.json")) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise RuntimeError("config/game.json is not the byte-frozen MaRs-777 contract")
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
