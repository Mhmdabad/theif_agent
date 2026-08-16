"""A whole match against a live opponent: handshake, agree, play, audit, record.

The last thing between a pile of working components and a game against another
team. Everything below existed and had no caller — ``open_series`` traded
addresses, ``agree_config`` compared digests, ``SubGame`` played — and nothing
ran them in order.

The order is not negotiable and each step exists because skipping it costs a
match: **handshake** (announced addresses, not configured ones), **agree the
config** (refuse any digest mismatch), **play**, **audit** (re-derive every
commitment once nonces arrive), **score** (Appendix F's fixed table), **agree
the result** (rule 35, before either side reports — the one step whose failure
is a recorded fact rather than an abort), and **record** (four artefacts).

**Nothing here mails anybody.** The report is built and written carrying the
agreement it actually reached; ``play`` is what sends it, and only after a real
match — the split keeps a rehearsal off the lecturer's inbox.
"""

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.alternation import opposite
from ..infra.artefacts import ArtefactSet
from ..infra.report import Report, Repositories
from ..infra.step_zero_signing import statement
from ..shared.result_claim import claim_and_digest
from .match_claim_rows import claim_rows, groups_for_claim
from .match_outcome import SubGameOutcome
from .match_play import MatchPlay
from .match_scored import scored
from .match_settled import settled
from .match_standing import series_block
from .orchestrator_book import RESULT_TIMEOUT_SEC

__all__ = [
    "MatchRunner",
    "SubGameOutcome",
]
"""Re-exported explicitly: ``no_implicit_reexport`` rejects importers otherwise."""


@dataclass
class MatchRunner(MatchPlay):
    """Plays a whole match against one opponent."""

    offered_digest: str = field(default="", init=False)
    """The SHA-256 the result was offered under (§9.3.3), kept from
    :meth:`agree_result` so the report records the bytes that went on the wire."""

    def result(
        self,
        commit_hash: str,
        total_tokens: int,
        agreed: bool,
        repositories: Repositories,
        counted: bool = True,
    ) -> Report:
        """The binding report, scored from what was actually played.

        ``agreed`` has no default: rule 35 wants both sides to accept the result
        before either reports, and a literal here would assert that rather than
        establish it.
        """
        return Report(
            game_id=self.game_id,
            game_uid=self.declaration.game_uid,
            role=self.role,
            team=self.declaration.us.name,
            opponent_team=self.declaration.them.name,
            repositories=repositories,
            sub_games=tuple(scored(outcome, commit_hash) for outcome in self.outcomes),
            total_tokens=total_tokens,
            agreed=agreed,
            counted=counted,
            started_at=self.declaration.started_at,
            ended_at=self.now(),
            starting_role=self.role,
            series_result=self.series_result(),
            mcp_addresses=self.declaration.endpoints.to_dict(),
            machine=statement(self.declaration.hardware, self.declaration.provenance),
            signature=self.declaration.signature,
            result_claim_sha256=self.offered_digest if agreed else "",
        )

    def series_result(self) -> dict[str, object]:
        """The group-keyed standing; :mod:`.match_standing` says why it is wire format.

        Keyed by the **wire-exchanged group ids**, not our private config's
        names: each side spells the other's display name its own way, and a
        rehearsal proved two honest peers can disagree about nothing but
        spelling. The greeting's ``group_id`` arrived in the same bytes twice.
        """
        ours, theirs = self.declaration.us.name, self.declaration.them.name
        if self.peering is not None:
            ours = self.peering.ours.group_id or ours
            theirs = self.peering.theirs.group_id or theirs
        if ours == theirs:  # a rehearsal: both repositories are one group
            ours, theirs = f"{ours}-{self.role}", f"{theirs}-{opposite(self.role)}"
        return series_block([o.scores() for o in self.outcomes], self.role, ours, theirs)

    def agree_result(self, timeout: float = RESULT_TIMEOUT_SEC) -> bool:
        """Step 6: publish what we scored, and learn whether they scored it too.

        Appendix E rule 35, built from :attr:`outcomes` — what was actually
        played, not a summary. A series whose audit found forgery is **not**
        offered for agreement: there is nothing to agree about a match one
        side did not play honestly.
        """
        if not self.opponent_played_fairly:
            return False
        # Built by the same function the result document uses, so the rows we
        # hash now and the rows we publish later cannot describe different
        # games. The commit is a placeholder: the agreed scope trims it away,
        # and it is not known until the artefacts are written.
        rows = claim_rows(self, *groups_for_claim(self))
        claim, digest = claim_and_digest(self.game_id, rows, self.series_result())
        self.offered_digest = digest
        return self.orchestrator.agree_result(claim, digest, self.declaration.game_uid, timeout)

    def artefacts(self, result: Report) -> ArtefactSet:
        """Step 5: the four files, as one set that must agree with itself."""
        return ArtefactSet(
            declaration=self.declaration,
            configs=tuple(self.config_for(o.number) for o in self.outcomes),
            logs=tuple(settled(o, result) for o in self.outcomes),
            result=result,
        )

    def write(self, result: Report) -> tuple[Path, ...]:
        """Write the evidence, refusing an incoherent set rather than producing it."""
        return self.artefacts(result).write(self.directory)

    @property
    def opponent_played_fairly(self) -> bool:
        """Whether every sub-game audited clean.

        A match with one forged sub-game is not a match with a bad sub-game:
        there is nothing to agree about a series whose commitments do not open.
        """
        return all(outcome.clean for outcome in self.outcomes)

    def failures(self) -> list[str]:
        """Every audit finding across the match, for the conversation that follows."""
        return [
            f"sub-game {outcome.number}: {failure}"
            for outcome in self.outcomes
            for failure in outcome.audit.failures
        ]
