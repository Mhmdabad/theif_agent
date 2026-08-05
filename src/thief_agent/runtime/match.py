"""A whole match against a live opponent: handshake, agree, play, audit, record.

The last thing between a pile of working components and a game against another
team. Everything below existed and had no caller — ``open_series`` traded
addresses, ``agree_config`` compared digests, ``SubGame`` played, ``ArtefactSet``
wrote the evidence — and nothing ran them in order.

The order is not negotiable and each step exists because skipping it costs a
match:

1. **Handshake** — trade public addresses and write both into the declaration.
   The address in the private config is only a bootstrap; what the opponent
   *announces* is where they are.
2. **Agree the config** — exchange ``config_sha256`` and refuse to play on any
   mismatch. Two peers with different parameters are playing different games
   and will report incompatible results, which scores zero for both.
3. **Play** — each sub-game through the four ceremony phases.
4. **Audit** — re-derive every step the opponent committed to, once their
   nonces arrive. This is the only moment the question is answerable.
5. **Score** — classify the final board through :mod:`..domain.scoring`, whose
   table comes from Appendix F. The scores are *fixed* parameters: inventing
   them here, or carrying a placeholder into a result file, is a deviation an
   audit finds.
6. **Record** — the four artefacts, checked for coherence before anything is
   written.

**Nothing here mails anybody.** The report is built and written to disk; sending
it is a separate, deliberate act by a person who has agreed the result with the
opponent first (FR-7.16). A match runner that mailed on completion would send a
report for a result the other side had not yet accepted.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.axes import AxisConvention
from ..domain.board import BoardState
from ..domain.scoring import Outcome, scores_for
from ..infra.artefacts import ArtefactSet
from ..infra.ceremony import AuditResult
from ..infra.config_file import LockedConfig, lock
from ..infra.declaration import MatchDeclaration
from ..infra.match_log import MatchLog
from ..infra.report import Report, Repositories, SubGameResult
from ..shared.config import config_sha256
from ..strategy.base import BrainBase
from .orchestrator import Orchestrator
from .peer import McpPeer
from .subgame import Played, SubGame


@dataclass(frozen=True, slots=True)
class SubGameOutcome:
    """One sub-game, and what we concluded about the other side's play."""

    number: int
    played: Played
    audit: AuditResult
    log: MatchLog
    game: "SubGame | None" = None
    """The sub-game that produced this, for anything wanting its ceremony.

    Optional because an outcome can be reconstructed from files without one.
    """

    @property
    def clean(self) -> bool:
        return self.audit.clean

    @property
    def outcome(self) -> Outcome:
        """How this sub-game finished, in the rulebook's vocabulary."""
        return Outcome.CAPTURE if self.played.captured else Outcome.SURVIVAL

    def scores(self) -> tuple[int, int]:
        """``(cop, thief)`` for this sub-game, from the Appendix F table."""
        return scores_for(self.outcome)


@dataclass
class MatchRunner:
    """Plays a whole match against one opponent."""

    orchestrator: Orchestrator
    declaration: MatchDeclaration
    parameters: dict[str, Any]
    brain: BrainBase
    axes: AxisConvention
    start: BoardState
    sub_games: int
    max_steps: int
    directory: Path
    now: Callable[[], str] = field(default=lambda: "")
    outcomes: list[SubGameOutcome] = field(default_factory=list, init=False)

    @property
    def game_id(self) -> str:
        return self.declaration.game_id

    @property
    def role(self) -> str:
        return self.orchestrator.role

    def agree(self) -> str:
        """Step 2: refuse to start unless both sides hold the same parameters.

        Before any move, because a mismatch discovered mid-match is a match
        already spoiled — the steps played under the wrong physics cannot be
        un-played, and both sides have logs nobody can reconcile.
        """
        return self.orchestrator.agree_config(self.parameters)

    def config_for(self, number: int) -> LockedConfig:
        return lock(
            game_id=self.game_id,
            game_uid=self.declaration.game_uid,
            sub_game=number,
            parameters=self.parameters,
            agreed_between=(self.declaration.us.name, self.declaration.them.name),
        )

    def play_sub_game(self, number: int, timeout: float = 30.0) -> SubGameOutcome:
        """Steps 3 and 4 for one sub-game."""
        log = MatchLog(
            game_id=self.game_id,
            sub_game=number,
            role=self.role,
            game_uid=self.declaration.game_uid,
            config_sha256=config_sha256(self.parameters),
        )
        game = SubGame(
            role=self.role,
            brain=self.brain,
            peer=McpPeer(
                role=self.role,
                client=self.orchestrator.client,
                inboxes=self.orchestrator.inboxes,
                now=self.now(),
                timeout=timeout,
            ),
            log=log,
            state=self.start,
            axes=self.axes,
            max_steps=self.max_steps,
            now=self.now,
        )
        played = game.play()
        outcome = SubGameOutcome(
            number=number, played=played, audit=game.audit(), log=log, game=game
        )
        self.outcomes.append(outcome)
        return outcome

    def result(
        self, commit_hash: str, total_tokens: int, agreed: bool, repositories: Repositories
    ) -> Report:
        """The binding report, scored from what was actually played.

        ``agreed`` is a parameter and has no default. FR-7.16 requires both
        sides to accept the result *before* either reports one, and a runner
        that assumed agreement would produce a report claiming something no
        human had checked. It is the one field only a person can fill in.
        """
        return Report(
            game_id=self.game_id,
            game_uid=self.declaration.game_uid,
            role=self.role,
            team=self.declaration.us.name,
            opponent_team=self.declaration.them.name,
            repositories=repositories,
            sub_games=tuple(
                SubGameResult(
                    sub_game=outcome.number,
                    cop_score=outcome.scores()[0],
                    thief_score=outcome.scores()[1],
                    commit_hash=commit_hash,
                    steps=outcome.played.steps,
                )
                for outcome in self.outcomes
            ),
            total_tokens=total_tokens,
            agreed=agreed,
            started_at=self.declaration.started_at,
            ended_at=self.now(),
        )

    def artefacts(self, result: Report) -> ArtefactSet:
        """Step 5: the four files, as one set that must agree with itself."""
        return ArtefactSet(
            declaration=self.declaration,
            configs=tuple(self.config_for(o.number) for o in self.outcomes),
            logs=tuple(o.log for o in self.outcomes),
            result=result,
        )

    def write(self, result: Report) -> tuple[Path, ...]:
        """Write the evidence, refusing an incoherent set rather than producing it."""
        return self.artefacts(result).write(self.directory)

    @property
    def opponent_played_fairly(self) -> bool:
        """Whether every sub-game audited clean.

        A match with one forged sub-game is not a match with a bad sub-game.
        FR-7.16 requires both sides to agree the result before either reports,
        and there is nothing to agree about a series where one side's
        commitments do not open.
        """
        return all(outcome.clean for outcome in self.outcomes)

    def failures(self) -> list[str]:
        """Every audit finding across the match, for the conversation that follows."""
        return [
            f"sub-game {outcome.number}: {failure}"
            for outcome in self.outcomes
            for failure in outcome.audit.failures
        ]
