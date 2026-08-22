"""Counted FastMCP surface, including the direct Step-0 negotiate shape."""
# ruff: noqa: ANN401

from __future__ import annotations

from collections import deque
from typing import Any


def step_zero_queue(inboxes: Any) -> deque[dict[str, Any]]:
    queue = getattr(inboxes, "step_zero", None)
    if queue is None:
        queue = deque()
        inboxes.step_zero = queue
    return queue


def build_server(cfg: Any, inboxes: Any) -> Any:
    from fastmcp import FastMCP

    queue = step_zero_queue(inboxes)
    mcp = FastMCP(name=f"copthief-counted-{cfg.group_id}")

    @mcp.tool
    def negotiate(
        message: dict[str, Any] | None = None,
        kind: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        if kind == "step0" and message is None and isinstance(payload, dict):
            queue.append(payload)
            return {"ok": True}
        if kind is None and payload is None and isinstance(message, dict):
            inboxes.agreements.append(message)
            return {"ok": True}
        raise ValueError("negotiate requires message or kind='step0' with payload")

    @mcp.tool
    def receive_turn(message: dict[str, Any]) -> dict[str, bool]:
        inboxes.turns.append(message)
        return {"ok": True}

    @mcp.tool
    def submit_audit(payload: dict[str, Any]) -> dict[str, bool]:
        inboxes.audits.append(payload)
        return {"ok": True}

    @mcp.tool
    def receive_control(message: dict[str, Any]) -> dict[str, bool]:
        inboxes.controls.append(message)
        return {"ok": True}

    return mcp


def send_step_zero(client: Any, payload: dict[str, Any]) -> None:
    last: Exception | None = None
    for _attempt in range(2):
        client._ensure_session()
        try:
            call = client._client.call_tool("negotiate", {"kind": "step0", "payload": payload})
            client._await(call)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            client._entered = False
            client._client = None
    raise RuntimeError(f"Step-0 negotiate failed: {last}") from last
