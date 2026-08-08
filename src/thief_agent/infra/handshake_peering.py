"""The two addresses in force, and the sub-game boundary they may move at."""

from dataclasses import dataclass

from .handshake_greeting import Greeting, HandshakeError, check, check_rotation


@dataclass(frozen=True, slots=True)
class Peering:
    """The two addresses in force, and the sub-game they were agreed for.

    The sub-game number is what makes a rotation checkable. An address change
    **between** sub-games is a tunnel restart; the same change **during** one
    is indistinguishable from an opponent redirecting our traffic after seeing
    what we committed to. Carrying the number means the difference is a
    comparison rather than a matter of trust.
    """

    ours: Greeting
    theirs: Greeting
    sub_game: int

    def rotate(self, ours: Greeting, theirs: Greeting, sub_game: int) -> "Peering":
        """Adopt fresh addresses for a later sub-game.

        Raises:
            HandshakeError: if either peer changed into someone else, or if the
                sub-game did not advance.
        """
        if sub_game <= self.sub_game:
            raise HandshakeError(
                f"addresses may only change between sub-games; sub-game {sub_game} "
                f"does not follow {self.sub_game}. Mid-game it is indistinguishable "
                "from redirecting our traffic after seeing our commit"
            )
        check_rotation(self.ours, ours)
        check_rotation(self.theirs, theirs)
        check(ours, theirs)
        return Peering(ours, theirs, sub_game)

    def relocations(self, later: "Peering") -> dict[str, tuple[str, str]]:
        """Which addresses actually moved, as ``role -> (was, now)``.

        A re-handshake usually changes nothing — the tunnel outlived the
        sub-game. Reporting only the addresses that really moved is what tells
        a routine re-greeting apart from one that re-pointed live traffic, and
        it is the line a transport log wants to carry.
        """
        return {
            was.role: (was.public_url, now.public_url)
            for was, now in ((self.ours, later.ours), (self.theirs, later.theirs))
            if was.public_url != now.public_url
        }
