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

from ..domain.providers import declared_model
from ..infra.declaration import Endpoints, MatchDeclaration, Team, build
from ..infra.handshake import Greeting, Peering
from ..infra.match_ledger import MatchLedger
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
    games_already_played: int = 0,
) -> MatchDeclaration:
    """The signed declaration for this match, from config and step-zero evidence.

    ``games_already_played`` is counted by the caller from
    :class:`~..infra.match_ledger.MatchLedger` rather than here, because this
    function assembles a document and the ledger is the driver's to read — and a
    count taken twice, in two places, is the one that eventually disagrees.
    """
    hardware = collect(declared_model(private.get("trash_talk")), environ)

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
        ),
        llm_model=hardware.llm_model,
        token_ceiling=int(
            parameters.get("network_and_league", {}).get("token_budget_per_series", 200_000)
        ),
        started_at=_now(),
        games_already_played=games_already_played,
        key=environ.get(SIGNING_KEY_ENV),
    )


def _record_game(
    directory: Path, declaration: MatchDeclaration, them: Team, rehearsal: bool
) -> None:
    """Add this match to the league ledger, unless it was only a rehearsal.

    Appendix E rule 52 allows warm-ups and counts one game per opponent, so a
    loopback rehearsal is deliberately not recorded: a count inflated by games
    nobody played is the false declaration rule 38 names, reached by
    carelessness rather than intent.
    """
    if rehearsal:
        return
    MatchLedger(directory).record(declaration.game_id, them.name, _now())


def _conclude(
    runner: MatchRunner,
    declaration: MatchDeclaration,
    us: Team,
    them: Team,
    agreed: bool,
    rehearsal: bool = False,
) -> tuple[Path, ...]:  # pragma: no cover - reached only with an opponent on the wire
    """Write the played match to disk, and answer with the files written.

    ``agreed`` is passed in rather than decided here: it is the outcome of a
    conversation with the opponent (Appendix E rule 35), and this function only
    does paperwork.

    The token total is read off the brain's voice rather than written as a
    literal. It was a hardcoded ``0`` — true while the language model never
    ran, and a false statement under Appendix E rule 54 the moment a provider
    other than ``template`` is configured.

    The ledger is written **after** the artefacts, so a match that failed to
    produce evidence is not counted as one that was played.
    """
    written = runner.write(
        runner.result(
            commit_hash=declaration.provenance.github_commit or "unknown",
            total_tokens=runner.spent_tokens,
            agreed=agreed,
            repositories=Repositories(
                cop_repo=us.cop_repo,
                thief_repo=us.thief_repo,
                opponent_cop_repo=them.cop_repo,
                opponent_thief_repo=them.thief_repo,
            ),
        )
    )
    _record_game(runner.directory, declaration, them, rehearsal)
    return written
