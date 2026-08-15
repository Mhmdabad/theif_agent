"""What we announce about ourselves, and the address we announce it to.

Mixed into :class:`~.orchestrator.Orchestrator`. Every method here reads
``self.role``, ``self.client`` and ``self.beat`` live, because :meth:`adopt`
re-points the client mid-series and a captured copy would keep calling the
address the opponent has already left.
"""

import secrets
from pathlib import Path
from typing import Any

from ..infra.handshake import AddressBook, Greeting, Peering, record
from ..infra.pairing_v3 import pairing_call
from .orchestrator_agreements import AgreementsMixin
from .orchestrator_book import GREETING_TIMEOUT_SEC, PROTOCOL_VERSION
from .orchestrator_core import MatchAborted

__all__ = [
    "GreetingMixin",
]


class GreetingMixin(AgreementsMixin):
    """Announcing, adopting, and opening a series."""

    def greeting(self, public_url: str, group_id: str) -> Greeting:
        """What we tell the opponent about ourselves.

        The role comes from this orchestrator rather than from an argument, so
        the address we announce and the role we play can never disagree.
        """
        return Greeting(
            role=self.role,
            group_id=group_id,
            public_url=public_url,
            protocol_version=PROTOCOL_VERSION,
        )

    def announce(self, ours: Greeting) -> dict[str, Any]:
        """Push our terms, signature and address through ``negotiate``.

        Sent in the cohort's flat reference-v3 shape, which our own gate also
        accepts -- so speaking it costs nothing against ourselves and is the
        only thing another team's gate understands.

        **The identity carries our real protocol version**, not the name of the
        dialect this call is written in. A peer is entitled to refuse us for
        speaking a contract it does not, and being refused at the handshake is
        better than being accepted and failing three phases later.

        The nonce is fresh per announcement: it is ours alone, the opponent
        re-verifies with it, and reusing one would let a replayed handshake
        carry a signature that already verified.
        """
        self.beat("announce")
        terms = self.inboxes.parameters
        if not terms:
            return self.call_opponent("negotiate", {"message": {"greeting": ours.to_dict()}})
        call = pairing_call(
            terms,
            secrets.token_hex(16),
            self.role,
            self.inboxes.sub_game,
            {
                "group_id": ours.group_id,
                "mcp_url": ours.public_url,
                "protocol_version": ours.protocol_version,
            },
        )
        return self.call_opponent("negotiate", call)

    def try_announce(self, ours: Greeting) -> bool:
        """Announce, tolerating an outbound path that no longer exists.

        Only for the re-handshake, where the address we hold may be the very
        thing that has gone stale. Everywhere else a failed call is a technical
        loss and should stay one — a helper that quietly swallows unreachable
        opponents is the fastest way to turn a lost match into a silent one.

        Returns:
            Whether the announcement actually landed.
        """
        try:
            self.announce(ours)
        except MatchAborted:
            self.beat("announce-failed")
            return False
        return True

    def open_series(
        self,
        ours: Greeting,
        directory: Path,
        game_id: str,
        timeout: float = GREETING_TIMEOUT_SEC,
    ) -> Peering:
        """Trade addresses and write both into the pre-game declaration.

        Announcing first is deliberate. Waiting for the opponent before saying
        anything is a handshake where two polite peers wait for each other
        forever — the deadlock the state machine exists to make impossible.

        Returns the addresses in force for sub-game 1. Later sub-games go
        through :meth:`rehandshake`, which is the same exchange with the
        additional rule that only the address may have moved.
        """
        self.announce(ours)
        peering = Peering(ours, self.accept_greeting(ours, timeout), sub_game=1)
        self.adopt(peering.theirs)
        record(directory, game_id, AddressBook.peered(peering))
        return peering

    def adopt(self, theirs: Greeting) -> None:
        """Point the client at the address the opponent actually announced.

        ``opponent_url`` in the private config is a **bootstrap** address: it
        is how we reach them the first time, and it is whatever we were told
        out of band. Their greeting is the authoritative statement of where
        they are, and it is the value the declaration records — so calls that
        went somewhere else would contradict the file we both signed.

        Only ever called from an accepted greeting. Following a redirect the
        transport happened to return would be a different thing entirely.
        """
        was = self.client.repoint(theirs.public_url)
        if was != theirs.public_url:
            self.beat(f"relocated:{theirs.role}:{was}->{theirs.public_url}")
