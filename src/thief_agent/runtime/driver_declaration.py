"""Filling in the match declaration, which is the paperwork half of the driver.

Step zero's evidence — the hardware sheet, the provenance stamp, the signing
key — is gathered and handed to :func:`~..infra.declaration.build` here so that
:mod:`.driver` reads as the order the pieces are assembled in rather than as
twenty keyword arguments. The role is passed in rather than imported, because
naming the role is the driver's job in each repository.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..infra.declaration import Endpoints, MatchDeclaration, Team, build
from ..infra.handshake import Greeting, Peering
from ..infra.report import Repositories
from ..infra.step_zero import SIGNING_KEY_ENV, collect, provenance
from .match import MatchRunner


def _now() -> str:
    """An ISO-8601 UTC timestamp, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _declaration(
    *,
    game_id: str,
    role: str,
    private: dict[str, Any],
    environ: dict[str, str],
    parameters: dict[str, Any],
    us: Team,
    them: Team,
    ours: Greeting,
    peering: Peering,
) -> MatchDeclaration:
    """The signed declaration for this match, from config and step-zero evidence."""
    hardware = collect(str(private.get("trash_talk", {}).get("model", "template")), environ)

    return build(
        game_id=game_id,
        game_uid=game_id,
        role=role,
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


def _conclude(
    runner: MatchRunner, declaration: MatchDeclaration, us: Team, them: Team
) -> tuple[Path, ...]:  # pragma: no cover - reached only with an opponent on the wire
    """Write the played match to disk, and answer with the files written."""
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
