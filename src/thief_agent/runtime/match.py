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
from ..domain.lock import ScentAgreement
from ..domain.outcome import TechnicalLoss
from ..domain.scoring import Outcome, scores_for
from ..infra.artefacts import ArtefactSet
from ..infra.ceremony import AuditResult
from ..infra.config_file import LockedConfig, lock
from ..infra.declaration import MatchDeclaration
from ..infra.handshake import Peering
from ..infra.match_log import MatchLog
from ..infra.report import Report, Repositories, SubGameResult
from ..shared.config import config_sha256, series_length
from ..strategy.base import BrainBase
from .orchestrator import (
    CONFIG_TIMEOUT_SEC,
    GREETING_TIMEOUT_SEC,
    MatchAborted,
    Orchestrator,
)
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
    max_steps: int
    directory: Path
    now: Callable[[], str] = field(default=lambda: "")
    peering: Peering | None = None
    """The addresses in force, from the opening handshake and re-agreed at each boundary.

    Supplied by the driver rather than negotiated here: trading addresses is
    :meth:`Orchestrator.open_series`, and a runner that opened its own series
    would be a second place the declaration gets written. What the runner owns
    is the *series*, which is why the boundaries between its sub-games are its
    responsibility and this field advances across them.

    ``None`` means no addresses were ever agreed, and :meth:`play_series`
    refuses on it rather than skipping the boundary. Skipping it silently is
    exactly the defect this field exists to close.
    """

    outcomes: list[SubGameOutcome] = field(default_factory=list, init=False)

    scent_lock: ScentAgreement | None = field(default=None, init=False)
    """The pre-series scent model both sides hashed, once :meth:`agree` has run.

    ``None`` until a peer has matched our lock exactly, and not settable from
    outside the runner's construction: a series that never negotiated one has
    nothing to derive its scent rules from, and :meth:`play_sub_game` refuses to
    open on that rather than picking a default. The default is what P1-15 was.
    """

    @property
    def game_id(self) -> str:
        return self.declaration.game_id

    @property
    def sub_games(self) -> int:
        """How long this series is, from the parameters both sides signed.

        Derived rather than accepted, because it used to be accepted: the count
        travelled in from ``--sub-games``, which defaulted to ``1``, and a
        series of one is not a short match — Appendix F table 18 row 1 fixes it
        at six and deviating disqualifies the team. A runner that cannot be
        *told* how long its series is cannot be told wrong.
        """
        return series_length(self.parameters)

    @property
    def role(self) -> str:
        return self.orchestrator.role

    def agree(self, timeout: float = CONFIG_TIMEOUT_SEC) -> str:
        """Step 2: refuse to start unless both sides hold the same parameters.

        Before any move, because a mismatch discovered mid-match is a match
        already spoiled — the steps played under the wrong physics cannot be
        un-played, and both sides have logs nobody can reconcile.

        **Two agreements, in this order.** Appendix E rule 11 fixes the
        parameters and rule 23 fixes the scent-emission model, and they are not
        the same document: the config digest covers ``game.json``, while the
        emission kernel, its falloff, its rounding and the dialect the field
        travels in live in the code and would pass a config comparison
        untouched. The parameters go first because two peers who cannot agree
        what board they are on have nothing to say about pheromones on it.

        Both are bound to this runner's ``game_uid``, so the series the
        declaration names and the series we negotiated are provably the same
        one. Without it an agreement reached for an earlier series could be
        replayed to open this one, and the declaration would record a
        negotiation that never happened.

        Returns:
            The config digest. The scent agreement is kept on
            :attr:`scent_lock`, because it is not a digest but a set of terms
            the sub-games have to be played under.
        """
        digest = self.orchestrator.agree_config(
            self.parameters, game_uid=self.declaration.game_uid, timeout=timeout
        )
        self.scent_lock = self.orchestrator.agree_scent_model(
            game_uid=self.declaration.game_uid, timeout=timeout
        )
        return digest

    def locked_scent(self) -> ScentAgreement:
        """The agreed model, or a refusal to open a sub-game without one.

        The alternative — falling back to a default — is precisely the silent
        downgrade this gate exists to prevent. A peer that never locked a model
        is a peer whose field we cannot check, and the rulebook's price for a
        series played on an unfixed model is the match.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` when no lock was agreed.
        """
        if self.scent_lock is None:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "no scent-emission model was locked with the opponent; Appendix E "
                "rule 23 fixes it cryptographically before the game starts, and a "
                "sub-game opened without one is played on a field neither side can "
                "check — call agree() before playing",
            )
        return self.scent_lock

    def config_for(self, number: int) -> LockedConfig:
        return lock(
            game_id=self.game_id,
            game_uid=self.declaration.game_uid,
            sub_game=number,
            parameters=self.parameters,
            agreed_between=(self.declaration.us.name, self.declaration.them.name),
        )

    def peered(self) -> Peering:
        """The addresses in force, or a refusal to play a series that agreed none.

        The alternative — playing on whatever the private config bootstrapped
        us with — is a series whose declaration names addresses nobody traded,
        and one that could not re-handshake because it has nothing to compare a
        fresh greeting against.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` when no handshake opened the series.
        """
        if self.peering is None:
            raise MatchAborted(
                TechnicalLoss.ILLEGAL_ACTION,
                "no addresses were agreed with the opponent; a series opens by "
                "trading greetings through open_series, and one that skipped it "
                "has nothing to re-handshake against between its sub-games",
            )
        return self.peering

    def rehandshake(self, number: int, timeout: float = GREETING_TIMEOUT_SEC) -> Peering:
        """Re-agree the addresses at the boundary before sub-game ``number``.

        The addresses we announce are the ones already agreed: our own tunnel
        rotating is a discovery the driver makes, not something a series loop
        can invent. What this recovers from is *their* tunnel rotating, which is
        the case the loop can neither predict nor be told about — and it is the
        common one, because a free-tier tunnel issues a new URL on every restart.

        The result replaces :attr:`peering` only once it is agreed, so a refused
        boundary leaves the series pointing where it was rather than half-moved.
        """
        current = self.peered()
        self.peering = self.orchestrator.rehandshake(
            current, current.ours, number, self.directory, self.game_id, timeout
        )
        return self.peering

    def play_series(self, timeout: float = 30.0) -> list[SubGameOutcome]:
        """Step 3 for the whole series: every numbered sub-game, in order.

        The length is resolved *before* the first sub-game, so a configuration
        that deviates costs nothing — no board is played under it, and the
        opponent never sees a series that stops short of the book.

        **Every pair of sub-games is separated by a re-handshake**, which is the
        thing this loop had none of. ``rehandshake`` was written, documented and
        never called: six sub-games ran back to back, so a tunnel that rotated
        partway through killed the series — and a technical loss scores zero for
        *both* sides, so it destroyed the sub-games already won on the board too.

        Five boundaries, at 1→2 through 5→6. Not before the first, which the
        opening handshake already covered, and not after the last, where an
        announcement is a message nobody is waiting for.

        The peering is resolved alongside the length and for the same reason: a
        series that cannot re-handshake is one that will lose a board it has
        already won, and the cheapest moment to say so is before there is a
        board to lose. The length goes first of the two because a deviating
        configuration is a fault of our own that needs no opponent to diagnose.
        """
        length = self.sub_games
        self.peered()
        played: list[SubGameOutcome] = []
        for number in range(1, length + 1):
            if number > 1:
                self.rehandshake(number, timeout)
            played.append(self.play_sub_game(number, timeout))
        return played

    def play_sub_game(self, number: int, timeout: float = 30.0) -> SubGameOutcome:
        """Steps 3 and 4 for one sub-game.

        The scent rules are read from the agreement before anything else, so a
        series that never locked a model costs a refusal rather than a board.
        """
        locked = self.locked_scent()
        self.orchestrator.inboxes.accepted_turns.clear()
        self.orchestrator.inboxes.accepted_reveals.clear()
        hint_max_words = int(self.parameters.get("hint_max_words", 15))
        self.orchestrator.inboxes.hint_max_words = hint_max_words
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
                hint_max_words=hint_max_words,
            ),
            log=log,
            state=self.start,
            axes=self.axes,
            max_steps=self.max_steps,
            hint_max_words=hint_max_words,
            now=self.now,
            require_bound_scent=locked.require_bound_scent,
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
