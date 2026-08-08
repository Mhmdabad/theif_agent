"""Re-agreeing addresses at a sub-game boundary.

Mixed into :class:`~.orchestrator.Orchestrator`. A rotation exists precisely
because the address moves, so ``self.client`` and ``self.inboxes`` are read
live here — the value this module is about is the one a captured copy would
have got wrong.
"""

import queue
from pathlib import Path
from typing import Any

from ..domain.outcome import TechnicalLoss
from ..infra.handshake import AddressBook, Greeting, HandshakeError, Peering, record
from .orchestrator_book import GREETING_TIMEOUT_SEC
from .orchestrator_core import MatchAborted
from .orchestrator_greeting import GreetingMixin

__all__ = [
    "RotationMixin",
]


class RotationMixin(GreetingMixin):
    """The re-handshake between sub-games."""

    def rehandshake(
        self,
        current: Peering,
        ours: Greeting,
        sub_game: int,
        directory: Path,
        game_id: str,
        timeout: float = GREETING_TIMEOUT_SEC,
    ) -> Peering:
        """Re-agree addresses before a later sub-game, and re-point if they moved.

        Free-tier tunnels issue a new URL on every restart, so a six-sub-game
        series can outlive the tunnel it started on. Losing the series to that
        would be absurd — and expensive, because a technical loss scores zero
        for **both** sides, so a dead tunnel destroys sub-games already won on
        the board.

        Both peers re-greet every sub-game, whether or not anything moved. A
        re-handshake that only happens when we already know something changed
        is a re-handshake that cannot discover the thing it exists to discover:
        the side whose tunnel died is precisely the side that cannot tell us.

        Nothing but the address may move. :meth:`Peering.rotate` refuses a
        greeting that also changes role, team or protocol — that is not a
        rotated tunnel, it is a different peer arriving mid-series — and
        refuses any change that does not follow a sub-game boundary. Every
        greeting waiting in the mailbox is checked, not merely the newest; see
        :meth:`accept_rotation`.

        **The first announcement is allowed to fail.** This is the part that
        makes rotation actually survivable, and it is not obvious. If *their*
        tunnel is the one that died, the address we hold is dead with it, so
        announcing before listening would abort on the very failure we are here
        to recover from. But if *our* tunnel is the one that moved, they cannot
        reach us at all and announcing is the only way they ever learn where we
        went — so it cannot simply be dropped either.

        So: announce, tolerating failure; listen; adopt whatever address their
        greeting carries; and announce again if the first attempt never landed.
        Between them the two orders cover both single failures. If **both**
        tunnels rotate at once neither side can reach the other and the
        sub-game is genuinely lost — there is no in-band channel left, and
        pretending otherwise would only replace a clean timeout with a hang.

        Swallowing that first failure is safe only because the wait that
        follows carries its own deadline: an opponent who really has gone
        produces a ``TIMEOUT`` a moment later rather than silence.

        Raises:
            MatchAborted: ``TIMEOUT`` if the opponent never re-greets,
                ``ILLEGAL_ACTION`` if the greeting is not a rotation of the one
                already agreed.
        """
        announced = self.try_announce(ours)
        later = self.accept_rotation(current, ours, sub_game, timeout)
        self.adopt(later.theirs)
        if not announced:
            self.announce(ours)
        for role, (was, now) in sorted(current.relocations(later).items()):
            self.beat(f"agreed-move:{role}:{was}->{now}")
        record(directory, game_id, AddressBook.peered(later))
        return later

    def accept_rotation(
        self, current: Peering, ours: Greeting, sub_game: int, timeout: float
    ) -> Peering:
        """The addresses for ``sub_game``, from **every** greeting queued for it.

        :meth:`latest_agreement` takes the newest greeting and discards the rest,
        which is right when the only question is *where is the opponent now* —
        an older address is superseded by definition. At a boundary that is not
        the only question. A rotation is legal only if nothing but the address
        moved, and a greeting that moved something else is precisely the one
        that must not be superseded away by whatever arrived after it.

        Duplicates are still ordinary and still accepted: a retry re-sends the
        same bytes, and refusing that would lose a series to a re-send. What is
        refused is a *contradiction* — two greetings in one window that cannot
        both be the same peer — whichever order they arrived in. That is the
        rule the config and scent gates already apply, for the same reason.

        Raises:
            MatchAborted: ``TIMEOUT`` if nothing arrives inside the window,
                ``ILLEGAL_ACTION`` if any greeting waiting there is not a
                rotation of the peering already agreed.
        """
        self.beat("accept_rotation")
        later = self.rotation(current, ours, self.next_agreement(timeout), sub_game)
        while True:
            try:
                queued = self.inboxes.agreements.get_nowait()
            except queue.Empty:
                return later
            later = self.rotation(current, ours, queued, sub_game)

    def rotation(
        self, current: Peering, ours: Greeting, message: dict[str, Any], sub_game: int
    ) -> Peering:
        """One queued greeting, read as the addresses in force for ``sub_game``.

        Both checks live in :meth:`Peering.rotate` — that nothing but the address
        moved, and that the pair can still play each other at all. Repeating
        either here would be a second validator that can disagree with the first.

        Raises:
            MatchAborted: ``ILLEGAL_ACTION`` if this is not a rotation of the
                peering already agreed.
        """
        try:
            return current.rotate(ours, Greeting.from_dict(message.get("greeting")), sub_game)
        except HandshakeError as exc:
            raise MatchAborted(TechnicalLoss.ILLEGAL_ACTION, str(exc)) from exc
