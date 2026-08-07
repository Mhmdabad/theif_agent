"""Assembling a match from config, and running it against a live opponent.

The wiring between ``python -m thief_agent play`` and :class:`~.match.MatchRunner`:
read the two config files, build the pieces, run the five steps, write the files.

**Everything here is composition; the decisions live elsewhere.** The handshake
is :meth:`~.orchestrator.Orchestrator.open_series`, the digest exchange is
``agree_config``, the ceremony is :class:`~.subgame.SubGame`, the scoring is
:mod:`..domain.scoring`, the coherence check is :class:`~.artefacts.ArtefactSet`.
This module chooses none of it — it puts the arguments in the right order, which
is exactly the thing that had no home and is where every defect in this project
has been.

The addresses ``open_series`` agrees are handed to the runner rather than kept
here, because the boundaries between sub-games are the *series*' business and
that is what the runner owns. A peering that stopped at this line is a series
that cannot re-handshake, which is a series a rotated tunnel ends.

**Somebody has to start first, and it must not be punished for it.** Two peers
opening a match are each other's prerequisite: the first one up announces to a
server that does not exist yet. ``open_series`` announces unforgivingly, which
is right *during* a match — an unreachable opponent is a technical loss and
should stay one — and wrong at startup, where it means whoever types the command
first always fails. :func:`await_opponent` retries the announcement until the
other side appears or the patience runs out, so the two commands only have to be
started within a couple of minutes of each other rather than simultaneously.

**It writes and stops.** No mail. FR-7.16 requires both sides to agree the
result before either reports one, so the report goes to disk with ``agreed``
false and a person sends it later, having actually agreed.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.axes import AxisConvention
from ..domain.board import BoardState
from ..infra.declaration import Endpoints, Team, build
from ..infra.handshake import Greeting, Peering
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import ClientSettings, OpponentClient
from ..infra.mcp_transport import FastMcpTransport
from ..infra.report import Repositories
from ..infra.step_zero import SIGNING_KEY_ENV, collect, provenance
from ..infra.tunnel import discover, rehearsal_url
from ..shared.config import SHARED_CONFIG
from ..shared.config import load as load_shared
from ..strategy.loader import load_brain
from .match import MatchRunner
from .orchestrator import Orchestrator

ROLE = "thief"

DEFAULT_PATIENCE = 180.0
"""Seconds to wait for the opponent's agent to appear before giving up.

Three minutes: long enough that two people starting their commands from a chat
message do not have to synchronise watches, short enough that a genuinely
absent opponent is reported while somebody is still looking at the terminal.
"""


class StartupTimeout(RuntimeError):
    """Raised when the opponent never came up. Not a technical loss — no match began."""


def _side(block: dict[str, Any]) -> Team:
    """One side of the declaration, from a config block shaped like ``[game]``.

    Both sides are read the same way so the opponent's details can be pasted in
    the shape ours are already written in. FR-7.28 wants four repository links
    and :class:`Team` refuses a partial set, which is the right moment to find
    out — before a match rather than while writing the result nobody can trace.
    """
    repos = block.get("repos", {})
    return Team(
        name=str(block.get("group_name", "")),
        members=tuple(str(m) for m in block.get("members", [])),
        cop_repo=str(repos.get("cop", "")),
        thief_repo=str(repos.get("thief", "")),
    )


def _us(private: dict[str, Any]) -> Team:
    """Our own side, from ``[game]`` — where it already lives.

    Read from there rather than from a second ``[teams.us]`` block, because two
    places to state our own repositories is two places to disagree, and the
    declaration would carry whichever the code happened to read.
    """
    return _side(private.get("game", {}))


def _them(private: dict[str, Any]) -> Team:
    """The opponent, from ``[teams.them]`` — agreed with them beforehand.

    Nothing can derive this: their repositories and their members are theirs to
    state. It is the one section that must be edited per opponent.
    """
    return _side(private.get("teams", {}).get("them", {}))


def open_match(
    *,
    inboxes: PeerInboxes,
    private: dict[str, Any],
    environ: dict[str, str],
    game_id: str,
    directory: Path,
    rehearsal: bool = False,
) -> tuple[Path, ...]:  # pragma: no cover - the other side of this is another team
    """Run a whole match and write its evidence. Returns the files written.

    Uncovered, and the reason is that the thing under test would be **an
    opponent**. Every step it composes is covered against a real peer over real
    sockets in ``test_localhost_match``; what is left here is the argument
    order, which no test short of a second team can exercise. The pure helpers
    below — the ones that parse config and can silently produce a wrong board —
    are covered.

    **How many sub-games is not an argument.** It comes from the configuration
    both peers sign, which is loaded and validated before the first packet, so
    a deviation from Appendix F table 18 row 1 costs a startup message rather
    than a disqualification.
    """
    parameters = load_shared(SHARED_CONFIG)
    network = private.get("network", {})
    transport = FastMcpTransport()
    client = OpponentClient(
        transport=transport, settings=ClientSettings.from_config(network, environ)
    )
    orchestrator = Orchestrator(inboxes=inboxes, client=client, role=ROLE)

    if rehearsal:
        address = rehearsal_url(environ, int(network.get("my_port", 8801)))
    else:
        endpoint = discover(environ)
        address = endpoint.url if endpoint else ""
    ours = orchestrator.greeting(address, str(private.get("game", {}).get("group_id", "")))
    directory.mkdir(parents=True, exist_ok=True)
    peering = await_opponent(orchestrator, ours, directory, game_id)

    us, them = _us(private), _them(private)
    hardware = collect(str(private.get("trash_talk", {}).get("model", "template")), environ)

    declaration = build(
        game_id=game_id,
        game_uid=game_id,
        role=ROLE,
        us=us,
        them=them,
        endpoints=Endpoints(ours=ours.public_url or "local", theirs=peering.theirs.public_url),
        hardware=hardware,
        provenance=provenance(
            code_version=str(private.get("version", "1.0")),
            group_name=us.name,
            sub_game=1,
        ),
        llm_model=hardware.llm_model,
        token_ceiling=int(
            parameters.get("network_and_league", {}).get("token_budget_per_series", 200_000)
        ),
        started_at=_now(),
        key=environ.get(SIGNING_KEY_ENV),
    )

    board = parameters.get("board_and_agents", {})
    runner = MatchRunner(
        orchestrator=orchestrator,
        declaration=declaration,
        parameters=parameters,
        brain=load_brain(private.get("strategy")),
        axes=AxisConvention(),
        start=BoardState(
            grid_size=int(board.get("grid_size", 8)),
            cop=_cell(board.get("cop_start"), (0, 0)),
            thief=_cell(board.get("thief_start"), (6, 5)),
            barriers=frozenset(),
            step=0,
        ),
        max_steps=int(parameters.get("movement_and_barriers", {}).get("max_moves", 40)),
        directory=directory,
        now=_now,
        peering=peering,
    )

    try:
        runner.agree()
        runner.play_series()
    finally:
        transport.close()

    if not runner.opponent_played_fairly:
        for failure in runner.failures():
            print(f"  AUDIT FAILURE: {failure}")

    return runner.write(
        runner.result(
            commit_hash=declaration.provenance.github_commit or "unknown",
            total_tokens=0,
            agreed=False,
            repositories=Repositories(
                cop_repo=us.cop_repo,
                thief_repo=us.thief_repo,
                opponent_cop_repo=them.cop_repo,
                opponent_thief_repo=them.thief_repo,
            ),
        )
    )


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


def _cell(value: object, fallback: tuple[int, int]) -> tuple[int, int]:
    """A start position from JSON, which has lists rather than tuples."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), int(value[1]))
    return fallback


def _now() -> str:
    """An ISO-8601 UTC timestamp, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


__all__ = ["open_match"]
