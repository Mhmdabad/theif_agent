"""Trading addresses before the first move, and writing them down.

Two peers who have never met know one thing about each other: a URL. This
module is where that URL is exchanged, checked, and recorded in the pre-game
declaration — the file that fixes everything which does not change during a
match, so that afterwards there is no argument about who was supposed to be at
which address.

**Checking is the part that earns its keep.** :mod:`.tunnel` refuses to
*advertise* an address an opponent could not route to; this module refuses to
*accept* one. The asymmetry matters: a peer can only verify its own tunnel by
trusting itself, but the address it is handed is a claim by someone with no
obligation to be careful. A loopback URL accepted here means every call we make
goes to our own machine, the deadline expires, and the match ends in a
technical loss scoring **zero for both sides** — including the side that made
the mistake.

The rule for that check is not "always demand a public address". It is
symmetric, and it has to be: during local development both agents run on one
box against ``127.0.0.1``, which is explicitly permitted while coding. So the
condition is **we may not demand more reachability than we ourselves offer**.
A peer advertising a tunnel refuses a loopback opponent, because it genuinely
cannot reach one. A peer still on loopback accepts a loopback opponent, because
that is the local test loop working as intended — and if the opponent is public
while we are not, that is fine too: they can be reached, and our own exposure is
their problem to complain about, not ours to pre-empt.

The declaration is **merged, not overwritten**. It accumulates across stages —
hardware, model and token ceiling arrive later — and a stage that rewrote the
file wholesale would silently drop whatever a previous one had recorded.
"""

from .handshake_book import ADDRESS_KEY, AddressBook, record
from .handshake_greeting import Greeting, HandshakeError, check, check_rotation
from .handshake_peering import Peering

__all__ = [
    "ADDRESS_KEY",
    "AddressBook",
    "Greeting",
    "HandshakeError",
    "Peering",
    "check",
    "check_rotation",
    "record",
]
