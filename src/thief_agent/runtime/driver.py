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

**It writes and stops.** No mail. FR-7.16 requires both sides to agree the
result before either reports one, so the report goes to disk with ``agreed``
false and a person sends it later, having actually agreed.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.axes import AxisConvention
from ..domain.board import BoardState
from ..infra.declaration import Endpoints, Team, build
from ..infra.inboxes import PeerInboxes
from ..infra.mcp_client import ClientSettings, OpponentClient
from ..infra.mcp_transport import FastMcpTransport
from ..infra.report import Repositories
from ..infra.step_zero import SIGNING_KEY_ENV, collect, provenance
from ..infra.tunnel import discover
from ..shared.config import load as load_shared
from ..strategy.loader import load_brain
from .match import MatchRunner
from .orchestrator import Orchestrator

ROLE = "thief"
SHARED_CONFIG = Path("config/game.json")


def _team(section: dict[str, Any], key: str, fallback: str) -> Team:
    """One side of the declaration, from the private config's ``[teams]``."""
    block = section.get(key, {})
    return Team(
        name=str(block.get("name", fallback)),
        members=tuple(str(m) for m in block.get("members", ["unnamed"])),
        cop_repo=str(block.get("cop_repo", "")),
        thief_repo=str(block.get("thief_repo", "")),
    )


def open_match(
    *,
    inboxes: PeerInboxes,
    private: dict[str, Any],
    environ: dict[str, str],
    game_id: str,
    sub_games: int,
    directory: Path,
) -> tuple[Path, ...]:  # pragma: no cover - the other side of this is another team
    """Run a whole match and write its evidence. Returns the files written.

    Uncovered, and the reason is that the thing under test would be **an
    opponent**. Every step it composes is covered against a real peer over real
    sockets in ``test_localhost_match``; what is left here is the argument
    order, which no test short of a second team can exercise. The pure helpers
    below — the ones that parse config and can silently produce a wrong board —
    are covered.
    """
    network = private.get("network", {})
    client = OpponentClient(
        transport=FastMcpTransport(), settings=ClientSettings.from_config(network, environ)
    )
    orchestrator = Orchestrator(inboxes=inboxes, client=client, role=ROLE)

    endpoint = discover(environ)
    ours = orchestrator.greeting(
        endpoint.url if endpoint else "", str(private.get("game", {}).get("group_id", ""))
    )
    directory.mkdir(parents=True, exist_ok=True)
    peering = orchestrator.open_series(ours, directory, game_id)

    parameters = load_shared(SHARED_CONFIG)
    teams = private.get("teams", {})
    us, them = _team(teams, "us", "us"), _team(teams, "them", "them")
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
        brain=load_brain(private),
        axes=AxisConvention(),
        start=BoardState(
            grid_size=int(board.get("grid_size", 8)),
            cop=_cell(board.get("cop_start"), (0, 0)),
            thief=_cell(board.get("thief_start"), (6, 5)),
            barriers=frozenset(),
            step=0,
        ),
        sub_games=sub_games,
        max_steps=int(parameters.get("movement_and_barriers", {}).get("max_moves", 40)),
        directory=directory,
        now=_now,
    )

    runner.agree()
    for number in range(1, sub_games + 1):
        runner.play_sub_game(number)

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


def _cell(value: object, fallback: tuple[int, int]) -> tuple[int, int]:
    """A start position from JSON, which has lists rather than tuples."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), int(value[1]))
    return fallback


def _now() -> str:
    """An ISO-8601 UTC timestamp, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


__all__ = ["open_match"]
