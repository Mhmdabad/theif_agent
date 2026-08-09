"""The wire version and the three handshake deadlines.

Held apart from the gates that use them so the gate modules can import a book
value without importing each other: the greeting deadline is a default on
three different methods, and they live in three different siblings.
"""

__all__ = [
    "CONFIG_TIMEOUT_SEC",
    "GREETING_TIMEOUT_SEC",
    "PROTOCOL_VERSION",
    "RESULT_TIMEOUT_SEC",
    "SCENT_TIMEOUT_SEC",
]

PROTOCOL_VERSION = "1.0"
"""Bumped when the wire contract changes. Exchanged during negotiation."""

GREETING_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's address before declaring a timeout.

The Appendix F response timeout. A handshake with no deadline is the one place
a deadlock costs nothing to reach and everything to diagnose: neither peer has
moved, so there is no board state to explain what happened."""

CONFIG_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's config digest.

The same Appendix F response timeout, for the same reason: nobody has moved
yet, so an unbounded wait here produces a hang with no board to explain it. An
opponent who never answers has not agreed to our parameters, and the only safe
reading of silence at this gate is refusal."""

RESULT_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's final-result claim.

The Appendix F response timeout once more, and here silence is *not* read as a
refusal to play — the match is already over — but as a refusal to agree, which
is a fact the report records rather than an outcome anybody scores. Waiting
longer would only delay a report that is honest either way."""

SCENT_TIMEOUT_SEC = 30.0
"""How long to wait for the opponent's scent-model offer.

The Appendix F response timeout again, and the same reading of silence. A peer
that will not lock the emission model has not agreed to one, and Appendix E rule
23 voids a match played on a model the two sides never fixed — so waiting longer
only delays a series that cannot legitimately open."""
