"""The Appendix E rule 35 gate: agree the result before anybody reports one.

Mixed into :class:`~.orchestrator.Orchestrator`. The claim mailbox and the
outbound call are both reached through ``self`` at the moment they are used, so
a re-pointed client and a re-bound mailbox are both honoured here.

**Disagreement is not a technical loss, and that is the whole design.** Every
other gate in this file's neighbourhood aborts the match: a config mismatch, an
unopened commitment and a missed deadline all end a series, because a series
cannot continue through them. This one runs when the series is already over.
Two honest peers can still reach it disagreeing — one saw a capture the other
scored as survival — and the rulebook's answer to that is a conversation
between two teams, not a verdict either agent may pronounce. So the outcome
here is a **boolean written into the report**: ``result_agreed_with_opponent``,
true only when the opponent's arithmetic matched ours byte for byte.

Silence is the same answer as disagreement. An opponent who never sends a claim
has not agreed to ours, and reporting one as agreed on the strength of their
not answering is the exact false statement the field exists to prevent.
"""

import queue
import time
from typing import Any

from ..infra.inboxes import RESULT_DIGEST_KEY, RESULT_KEY, SERIES_KEY
from ..shared.config import digests_agree
from .orchestrator_book import RESULT_TIMEOUT_SEC
from .orchestrator_core import OrchestratorCore

__all__ = ["ResultMixin"]


class ResultMixin(OrchestratorCore):
    """Exchanging the final-result claim and recording whether it matched."""

    def agree_result(
        self,
        claim: dict[str, Any],
        ours: str,
        game_uid: str = "",
        timeout: float = RESULT_TIMEOUT_SEC,
    ) -> bool:
        """Offer our result, read theirs, and answer whether the two agree.

        **Speak, then listen**, as at every other gate: both peers run this at
        the same time and each blocks on a message only the other can send, so a
        version that waited before announcing would be two polite peers
        deadlocking.

        Never raises on a disagreeing or absent opponent. The match is over by
        the time this runs, so there is no series left to abort — what is left
        is a fact to record truthfully.

        Args:
            claim: the agreeable part of our result, from
                :func:`~..shared.result_claim.result_claim`.
            ours: its digest, which is what is actually compared.
            game_uid: the series being settled, carried so a result agreed for
                one series cannot be replayed to close another.

        Returns:
            Whether the opponent published the same result we did.
        """
        self.beat("negotiate_result")
        message: dict[str, object] = {
            RESULT_KEY: claim,
            RESULT_DIGEST_KEY: ours,
            SERIES_KEY: game_uid,
        }
        try:
            self.call_opponent("negotiate", {"message": message})
        except Exception:  # noqa: BLE001 - an unreachable peer has simply not agreed
            self.beat("result-unreachable")
            return False
        return self.accept_result_claim(ours, game_uid, timeout)

    def accept_result_claim(self, ours: str, game_uid: str, timeout: float) -> bool:
        """Read claims until one settles this series, or the patience runs out.

        Claims naming a **different** series are dropped as stale and the wait
        continues on the same deadline, so replaying an agreement from an
        earlier series buys nothing and does not shorten our patience either.

        The first claim about this series decides it. Unlike the config gate,
        which must see *every* queued digest agree, a second contradicting claim
        cannot rescue anything here: there is no match left to protect, and a
        peer that published two different results has told us the one thing we
        needed to know either way.
        """
        self.beat("await_result")
        deadline = time.monotonic() + timeout
        while True:
            try:
                body = self.inboxes.results.get(timeout=max(deadline - time.monotonic(), 0.0))
            except queue.Empty:
                self.beat("result-unanswered")
                return False
            about = str(body.get(SERIES_KEY, ""))
            if game_uid and about and about != game_uid:
                self.beat(f"stale-result:{about}")
                continue
            return digests_agree(ours, str(body.get(RESULT_DIGEST_KEY, "")))
