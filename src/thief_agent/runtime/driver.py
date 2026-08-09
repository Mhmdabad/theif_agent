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

**Somebody has to start first, and it must not be punished for it.** Two peers
opening a match are each other's prerequisite: the first one up announces to a
server that does not exist yet. ``open_series`` announces unforgivingly, which
is right *during* a match — an unreachable opponent is a technical loss and
should stay one — and wrong at startup, where it means whoever types the command
first always fails. :func:`await_opponent` retries until the other side appears
or the patience runs out, so the two commands only have to be started within a
couple of minutes of each other rather than simultaneously.

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
from ..strategy.loader import load_brain
from .driver_config import _cell, _max_moves, _side, _start_board, _them, _us
from .driver_declaration import _conclude, _declaration, _now
from .driver_startup import DEFAULT_PATIENCE, StartupTimeout, await_opponent
from .match import MatchRunner
from .orchestrator import Orchestrator

ROLE = "thief"


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
    sockets in ``test_localhost_match``; what is left is the argument order,
    which no test short of a second team can exercise. The pure helpers — the
    ones that parse config and can silently produce a wrong board — are covered.

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
    declaration = _declaration(
        game_id=game_id,
        role=ROLE,
        private=private,
        environ=environ,
        parameters=parameters,
        us=us,
        them=them,
        ours=ours,
        peering=peering,
        games_already_played=MatchLedger(directory).played(),
    )

    runner = MatchRunner(
        orchestrator=orchestrator,
        declaration=declaration,
        parameters=parameters,
        brain=load_brain(private.get("strategy")),
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

    return _conclude(runner, declaration, us, them, agreed, rehearsal)


__all__ = [
    "DEFAULT_PATIENCE",
    "ROLE",
    "StartupTimeout",
    "_cell",
    "_max_moves",
    "_now",
    "_side",
    "_them",
    "_us",
    "await_opponent",
    "open_match",
]
