"""The game's physics, written from the book and SPEC.md rather than from anyone's code.

Nothing in here hashes anything (``guards/purity.py`` enforces that): the byte-level
constructions come from ``sparring.kitref``, and these modules only decide what is legal and what
ends a sub-game.
"""

from sparring.rules.board import Board, Cell, Move, MOVES
from sparring.rules.outcome import Outcome, Role, score_for

__all__ = ["Board", "Cell", "Move", "MOVES", "Outcome", "Role", "score_for"]
