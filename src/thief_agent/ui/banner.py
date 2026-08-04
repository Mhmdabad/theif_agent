"""Whose turn it is, and whether the window may still accept an action.

The banner is the visible half. The half that matters is the **input lock**:
once a commitment has gone out, the move is sealed, and a window that still
accepted a click would be offering the operator a way to send a reveal that
does not open to the commitment they already made. The audit would call that
forgery, and it would be true.

So the lock is derived from the ceremony's own state rather than tracked
alongside it. A separate ``self.locked`` flag would be a second source of truth
about a question the ceremony already answers, and the two would disagree on
exactly the turn where a retry or a re-handshake made things interesting.

Colours are named rather than hex-coded here. The rulebook asks for green and
grey; which green is a question for the widget, and a model that decided it
could not be reused by a terminal fallback.
"""

from dataclasses import dataclass
from enum import Enum

from ..infra.ceremony import StepCeremony


class Tone(Enum):
    """How the banner should read at a glance."""

    GO = "green"
    """Ours to act on."""

    LOCKED = "grey"
    """Committed, or waiting on them. Either way, nothing to click."""


@dataclass(frozen=True, slots=True)
class Banner:
    """The banner's text, tone, and whether input is live."""

    text: str
    tone: Tone
    accepting_input: bool

    @property
    def locked(self) -> bool:
        return not self.accepting_input


def banner(ceremony: StepCeremony) -> Banner:
    """Read the banner off the ceremony, which is the only state that decides it.

    Four situations, in the order they occur:

    * **not yet committed** — ours to act on, input live;
    * **committed, lock incomplete** — sealed on our side, waiting on theirs;
    * **locked, not yet revealed** — both sealed, the reveal is mechanical;
    * **revealed** — the turn is done.

    Only the first accepts input. That is the whole rule: the moment our
    commitment exists, the move is fixed, and offering a way to change it would
    be offering a way to produce a reveal that does not open to it.
    """
    if ceremony.ours is None:
        return Banner(f"YOUR TURN — step {ceremony.step}", Tone.GO, accepting_input=True)
    if not ceremony.locked:
        return Banner(f"LOCKED — {ceremony.pending()}", Tone.LOCKED, accepting_input=False)
    if ceremony.revealed_ours is None:
        return Banner(f"LOCKED — revealing step {ceremony.step}", Tone.LOCKED, False)
    return Banner(f"LOCKED — step {ceremony.step} played", Tone.LOCKED, accepting_input=False)
