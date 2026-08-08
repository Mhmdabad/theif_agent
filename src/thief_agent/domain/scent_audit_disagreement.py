"""Saying what is wrong with one step, in words the accused can check.

The comparison half of :mod:`.scent_audit`: given the field a step's revealed
moves must have produced, what the peer actually disclosed is either absent,
malformed, or a different field — and each of those is reported as a sentence
naming the step rather than as a bare verdict.
"""

from .scent_audit_replay import StepPlay
from .scent_audit_wire import ScentFieldError, check_field


def _disagreements(
    play: StepPlay, expected: dict[str, float], board_size: int, require_bound: bool
) -> list[str]:
    """What is wrong with one step's disclosed field, if anything."""
    if play.disclosed is None:
        if not require_bound:
            return []
        return [
            f"step {play.step}: no scent field was disclosed, so nothing they emitted can "
            "be checked; unverifiable scent is refused rather than believed"
        ]
    try:
        check_field(play.disclosed, board_size)
    except ScentFieldError as exc:
        return [f"step {play.step}: {exc}"]
    if play.disclosed != expected:
        return [
            f"step {play.step}: the disclosed scent field is not the one their own revealed "
            f"moves produce ({_where(play.disclosed)} against {_where(expected)}); a hint may "
            "lie, a trail may not"
        ]
    return []


def _where(field: dict[str, float]) -> str:
    """The peak of a field, for an accusation the other side can check."""
    if not field:
        return "an empty field"
    cell = min(field, key=lambda key: (-field[key], key))
    return f"peak {field[cell]} at {cell}"
