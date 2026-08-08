"""The vocabulary the strategy contract is stated in.

The failure modes a brain can signal, and the record it returns for one turn.
These are the names the runtime and the tests import; :mod:`.base` re-exports
them so ``strategy.base`` remains the single import site for the contract.
"""

from dataclasses import dataclass

from ..domain.actions import Action


class NoLegalActionError(RuntimeError):
    """Raised when a brain is asked to act with nothing legal available.

    Not the same as being enclosed: a thief with no legal move is captured,
    which is a terminal state the runtime should have detected before asking
    for an action. Reaching here means the caller skipped that check.
    """


class StrategyContextError(TypeError):
    """A configured brain cannot accept the documented belief context."""


@dataclass
class Decision:
    """One turn's output: what to do, and what to say about it."""

    action: Action
    hint: str = ""
    intent: str = "truth"
    reasoning: str = ""
