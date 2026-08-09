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
6. **Agree the result** — publish the score we arrived at, read the score they
   arrived at, and record whether the two are the same. Appendix E rule 35
   requires this *before* either side reports, and it is the one step whose
   failure is not an abort: two honest peers can disagree, and the answer to
   that is a conversation between two teams rather than a verdict from either
   agent.
7. **Record** — the four artefacts, checked for coherence before anything is
   written.

**Nothing here mails anybody.** The report is built and written to disk carrying
the agreement it actually reached; sending it is a separate, deliberate act
(FR-7.16, and ``report --send``). A match runner that mailed on completion would
be reporting before the human who has to stand behind the result has seen it.
"""

from dataclasses import dataclass
from pathlib import Path

from ..infra.artefacts import ArtefactSet
from ..infra.report import Report, Repositories, SubGameResult
from ..shared.result_claim import claim_sha256, result_claim
from .match_outcome import SubGameOutcome
from .match_play import MatchPlay
from .orchestrator_book import RESULT_TIMEOUT_SEC

__all__ = [
    "MatchRunner",
    "SubGameOutcome",
]
"""Re-exported explicitly: ``no_implicit_reexport`` rejects importers otherwise.

Every name this module exported before the split is still exported from here,
so ``from .match import MatchRunner`` keeps meaning what it did.
"""


@dataclass
class MatchRunner(MatchPlay):
    """Plays a whole match against one opponent."""

    def result(
        self, commit_hash: str, total_tokens: int, agreed: bool, repositories: Repositories
    ) -> Report:
        """The binding report, scored from what was actually played.

        ``agreed`` is a parameter and has no default. FR-7.16 and Appendix E
        rule 35 require both sides to accept the result *before* either reports
        one, and a runner that assumed agreement would produce a report claiming
        something nobody had checked. :meth:`agree_result` is what answers it;
        passing a literal here would be asserting agreement rather than
        establishing it.
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

    def agree_result(self, timeout: float = RESULT_TIMEOUT_SEC) -> bool:
        """Step 6: publish what we scored, and learn whether they scored it too.

        Appendix E rule 35. The claim is built from :attr:`outcomes`, which are
        what this runner actually played, so the thing offered to the opponent
        is the thing the report will carry rather than a summary of it.

        A series whose audit found forgery is **not** offered for agreement.
        There is nothing to agree about a match one side did not play honestly,
        and asking would invite a peer whose commitments did not open to sign
        off on the score anyway.
        """
        if not self.opponent_played_fairly:
            return False
        claim = result_claim(self.declaration.game_uid, [o.scores() for o in self.outcomes])
        return self.orchestrator.agree_result(
            claim, claim_sha256(claim), self.declaration.game_uid, timeout
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
