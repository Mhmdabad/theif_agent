"""The door itself: which bindings may enter a queue, and how a closed one answers.

Split out of :mod:`.inboxes`. :class:`~.inboxes.PeerInboxes` inherits this
class, so both methods below are real, typed methods of it.
"""

from typing import Any

from .inboxes_keys import RETRY_KEY
from .inboxes_state import InboxState


class InboxGate(InboxState):
    """:class:`~.inboxes_state.InboxState` plus the binding check every message meets."""

    def _closed(self, what: str, game_uid: str, sub_game: int) -> tuple[str, bool] | None:
        """Why a binding may not enter a queue, and whether asking again would help.

        ``None`` when the message names **exactly** the sub-game of exactly the
        series this mailbox is bound to; otherwise the reason, paired with
        whether the sender should try again.

        **Exactly, and nothing else.** The looser rule this replaces admitted
        anything that was not provably behind us, which sounds conservative and
        is the opposite: "not behind us" is also true of every packet that
        arrives before we have bound anything at all, so an unbound mailbox
        queued whatever it was sent and wrote its duplicate ledger from it. A
        forged commitment pushed in that window took the head of the queue and
        stranded the legitimate one behind it.

        **Two kinds of no, because there are two kinds of reason.** A binding we
        cannot yet judge — no series agreed, or a sub-game this series has not
        opened — is a statement about *us*, so the sender is asked to come back
        and :data:`RETRY_KEY` says so. A binding we can judge and have refused —
        another series, or a sub-game we are already past — is a statement about
        *the message*, and repeating it changes nothing.

        The deferral is what makes the strict rule safe. Demanding equality with
        no way to say "not yet" is what broke the series before: both peers
        advance this binding on their own thread, so the one that crossed a
        boundary first had its opening commitment refused at a door still set to
        the sub-game we had both just left, and ``receive_turn`` is
        fire-and-forget, so that single silent refusal cost the rest of the
        series. :meth:`bind` orders the two sides so it should not arise at all;
        this is what happens when it does anyway.
        """
        if not game_uid and not sub_game:
            # A peer running the cohort's protocol sends no binding at all.
            # Absent is not a mismatch: we key off the binding we hold, which
            # we know better than any claim on the wire could tell us.
            return None
        if not self.game_uid:
            return (
                f"{what} arrived before this mailbox was bound to a series; nothing is "
                "queued against a binding we have not agreed yet",
                True,
            )
        if game_uid != self.game_uid:
            return (
                f"{what} is bound to series {game_uid!r}, and we are playing {self.game_uid!r}",
                False,
            )
        if sub_game > self.sub_game:
            return (
                f"{what} is bound to sub-game {sub_game}, which this series has not opened "
                f"yet at sub-game {self.sub_game}",
                True,
            )
        if sub_game < self.sub_game:
            return (
                f"{what} is bound to sub-game {sub_game}, which this series is already "
                f"past at sub-game {self.sub_game}",
                False,
            )
        return None

    def _shut(self, what: str, closed: tuple[str, bool]) -> dict[str, Any]:
        """Answer a closed door, saying whether coming back would help."""
        detail, retry = closed
        if not retry:
            return self._reject(what, detail)
        self.deferred.append(f"{what}: {detail}")
        return {"ok": False, RETRY_KEY: True, "detail": detail}
