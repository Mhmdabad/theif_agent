"""Send, receive, and verify the frozen one-series Step-0 V2 exchange."""
# ruff: noqa: ANN401

from __future__ import annotations

import time
from typing import Any

from .counted_v3_step0_model import StepZeroSpec, build_payload, verify_payload
from .counted_v3_wire import send_step_zero, step_zero_queue


def exchange(
    client: Any, inboxes: Any, spec: StepZeroSpec, timeout: float
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    ours = build_payload(spec)
    send_step_zero(client, ours)
    queue = step_zero_queue(inboxes)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if queue:
            theirs = queue.popleft()
            commits = verify_payload(theirs, spec)
            print("  Step-0 V2 authenticated; both role commits accepted")
            return ours, theirs, commits
        time.sleep(0.1)
    raise RuntimeError(f"Step-0 timed out after {timeout:g}s")
