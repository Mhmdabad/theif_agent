"""Waiting for the other side to come up, before a match can begin.

Split out of :mod:`.driver` so the retry policy — the one piece of the startup
path with a deadline, a message and a named failure — reads on its own. The
driver still calls :func:`await_opponent` through its own module namespace, so
tests that replace it keep working.
"""

import time
from collections.abc import Callable
from pathlib import Path

from ..infra.handshake import Greeting, Peering
from .orchestrator import Orchestrator

DEFAULT_PATIENCE = 180.0
"""Seconds to wait for the opponent's agent to appear before giving up.

Three minutes: long enough that two people starting their commands from a chat
message do not have to synchronise watches, short enough that a genuinely
absent opponent is reported while somebody is still looking at the terminal.
"""


class StartupTimeout(RuntimeError):
    """Raised when the opponent never came up. Not a technical loss — no match began."""


def await_opponent(
    orchestrator: Orchestrator,
    ours: Greeting,
    directory: Path,
    game_id: str,
    patience: float = DEFAULT_PATIENCE,
    pause: float = 3.0,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Peering:
    """Keep announcing until the opponent is listening, then trade greetings.

    Args:
        patience: seconds to keep trying. Generous on purpose — the two people
            running these commands are typing them in different rooms.

    Raises:
        StartupTimeout: when the opponent never appeared. Named rather than
            surfacing the transport's own ``502 Bad Gateway``, which describes
            a proxy and not the situation.

    Only the *announcement* is retried. Once it lands, the handshake proceeds
    normally and a failure there is a real failure — an opponent who accepted
    our greeting and then went quiet is a different problem from one who had
    not started yet, and collapsing the two would hide the first.
    """
    deadline = now() + patience
    attempts = 0
    while not orchestrator.try_announce(ours):
        attempts += 1
        if now() >= deadline:
            raise StartupTimeout(
                f"the opponent never came up: {attempts} attempts over {patience:g}s. "
                "Their agent has to be running and their tunnel forwarding to it — "
                "ask them to run `check`, and confirm the port their tunnel points at "
                "matches the one their agent listens on"
            )
        if attempts == 1:
            print("  waiting for the opponent to come up…", flush=True)
        sleep(pause)
    return orchestrator.open_series(ours, directory, game_id)
