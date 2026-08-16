"""Assembling a match from config, and running it against a live opponent.

The wiring between ``python -m thief_agent play`` and :class:`~.match.MatchRunner`:
read the two config files, build the pieces, run the five steps, write the files.

**Everything here is composition; the decisions live elsewhere.** The handshake
is :meth:`~.orchestrator.Orchestrator.open_series`, the digest exchange is
``agree_config``, the ceremony is :class:`~.subgame.SubGame`, the scoring is
:mod:`..domain.scoring`, the coherence check is :class:`~.artefacts.ArtefactSet`.
This module chooses none of it — it puts the arguments in the right order, which
is where every defect in this project has been.

The addresses ``open_series`` agrees are handed to the runner rather than kept
here, because the boundaries between sub-games are the *series*' business. A
peering that stopped at this line is a series that cannot re-handshake, which is
a series a rotated tunnel ends.

**Somebody has to start first, and it must not be punished for it.**
``open_series`` announces unforgivingly, right during a match and wrong at
startup, where whoever types the command first would always fail —
:func:`await_opponent` retries until the other side appears, so the two
commands need only start within a couple of minutes of each other.

**It agrees, writes, and stops.** Rule 35 requires both sides to agree the
result before either reports one, so the match ends by publishing our score and
reading theirs, recording the answer rather than assuming it. Mailing stays a
separate act — ``report --send``. The rule 37 ledger is read before the first
packet and written after the evidence.
"""

from pathlib import Path
from typing import Any

from ..domain.axes import AxisConvention
from ..infra.inboxes import PeerInboxes
from ..infra.match_ledger import MatchLedger
from ..infra.mcp_client import ClientSettings, OpponentClient
from ..infra.mcp_transport import FastMcpTransport
from ..infra.tunnel import discover, rehearsal_url
from ..shared.config import SHARED_CONFIG
from ..shared.config import load as load_shared
from ..strategy.loader import load_brains
from .driver_config import _cell, _max_moves, _side, _start_board, _them, _us
from .driver_declaration import _conclude, _declaration, _now
from .driver_startup import DEFAULT_PATIENCE, StartupTimeout, await_opponent
from .match import MatchRunner
from .orchestrator import Orchestrator

ROLE = "thief"
"""This repository's natural role in sub-game 1."""


def open_match(
    *,
    inboxes: PeerInboxes,
    private: dict[str, Any],
    environ: dict[str, str],
    game_id: str,
    directory: Path,
    rehearsal: bool = False,
    starting_role: str = ROLE,
) -> tuple[Path, ...]:  # pragma: no cover - the other side of this is another team
    """Run a whole match and write its evidence. Returns the files written.

    The series length comes from the signed configuration, never this call.
    """
    parameters = load_shared(SHARED_CONFIG)
    network = private.get("network", {})
    transport = FastMcpTransport()
    client = OpponentClient(
        transport=transport, settings=ClientSettings.from_config(network, environ)
    )
    orchestrator = Orchestrator(inboxes=inboxes, client=client, role=starting_role)

    if rehearsal:
        address = rehearsal_url(environ, int(network.get("my_port", 8801)))
    else:
        endpoint = discover(environ)
        address = endpoint.url if endpoint else ""
    ours = orchestrator.greeting(address, str(private.get("game", {}).get("group_id", "")))
    directory.mkdir(parents=True, exist_ok=True)
    peering = await_opponent(orchestrator, ours, directory, game_id)

    us, them = _us(private), _them(private)
    ledger = MatchLedger(directory)
    first_meeting = them.name not in ledger.opponents()
    declaration = _declaration(
        game_id=game_id,
        role=starting_role,
        private=private,
        environ=environ,
        parameters=parameters,
        us=us,
        them=them,
        ours=ours,
        peering=peering,
        games_already_played=ledger.played(),
    )

    runner = MatchRunner(
        orchestrator=orchestrator,
        declaration=declaration,
        parameters=parameters,
        brains=load_brains(private.get("strategy"), trash_talk=private.get("trash_talk")),
        axes=AxisConvention(),
        start=_start_board(parameters.get("board_and_agents", {})),
        max_steps=_max_moves(parameters),
        directory=directory,
        now=_now,
        peering=peering,
    )

    agreed = False
    try:
        runner.agree()
        runner.play_series()
        agreed = runner.agree_result()
    finally:
        transport.close()

    for failure in runner.failures():
        print(f"  AUDIT FAILURE: {failure}")
    if not agreed:
        print("  RESULT NOT AGREED: the opponent did not publish the score we did")

    return _conclude(
        runner,
        declaration,
        us,
        them,
        agreed,
        rehearsal,
        declaration.games_already_played + (0 if rehearsal else 1),
        first_meeting,
    )


__all__ = [
    "DEFAULT_PATIENCE",
    "ROLE",
    "StartupTimeout",
    "_cell",
    "_now",
    "_side",
    "_them",
    "_us",
    "await_opponent",
    "open_match",
]
