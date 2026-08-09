"""Phase 4, and the question the whole ceremony exists to make answerable.

Split from :mod:`.subgame` unchanged. Rules 17-19 meet here: every step was
sealed before it was disclosed, and a mismatch found now is a forgery verdict,
not a warning.
"""

from dataclasses import dataclass

from ..infra.ceremony import AuditResult, Verdict, audit_opponent
from .subgame_commit import SubGameCommit


@dataclass
class SubGameAudit(SubGameCommit):
    """The closing half of a sub-game: disclose every nonce, then check theirs."""

    def _disclose(self) -> None:
        """Phase 4. Every nonce, once, and only now.

        ``finish()`` is what makes the nonces releasable at all — the ceremony
        refuses to produce them while any step is still open, so a sub-game
        that ended early cannot leak a secret for a step nobody has revealed.
        """
        self.ceremony.finish()
        disclosed = self.ceremony.final_reveal(self.now())
        for step, secret in disclosed.nonces.items():
            self.log.disclose(step, secret)
        self.peer.send_final(disclosed)
        self.their_final = self.ceremony.receive_final_reveal(self.peer.await_final())

    def audit(self) -> AuditResult:
        """Re-derive every step the opponent committed to.

        The nonces arrive in phase 4 and are the only thing that can open their
        commitments, so this is the first moment the question is answerable —
        and it is the last moment anybody asks it. A match that retained all the
        material and never ran this would be one where the cryptography was
        decoration.

        Every step is checked rather than stopping at the first failure. The
        opponent is entitled to the whole list: a dispute settled on one step
        tends to be reopened on the next.
        """
        if self.their_final is None:
            return AuditResult(
                verdict=Verdict.FORGED,
                checked=0,
                failures=(
                    f"the {self.opponent} disclosed no nonces, so nothing they committed "
                    "to can be opened; their play is unverifiable rather than proven",
                ),
            )
        sealed = audit_opponent(self.ceremony, self.their_final, self.sealed_states)
        impossible = self._audit_scent()
        if not impossible:
            return sealed
        return AuditResult(
            verdict=Verdict.FORGED,
            checked=sealed.checked,
            failures=sealed.failures + impossible,
        )
