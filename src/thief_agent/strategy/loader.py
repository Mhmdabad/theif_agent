"""Selecting the brains from the private configuration.

The rulebook's contract: point ``[strategy] thief_class`` and ``police_class``
at classes in ``package.module:Class`` form, or leave a key absent to run the
shipped heuristic for that role. Role alternation means one process plays both
roles across a series — natural role on odd sub-games, the opposite on even —
so **both** brains are loaded before the first packet: a missing brain
discovered at the sub-game-two boundary is a forfeited match discovered late.
"""

from importlib import import_module
from typing import Any

from ..domain.axes import AxisConvention
from .base import BrainBase
from .voice_config import build_voice

_PACKAGE = __name__.split(".")[0]

DEFAULT_BRAINS: dict[str, str] = {
    "thief": f"{_PACKAGE}.strategy.thief_brain:ThiefBrain",
    "police": f"{_PACKAGE}.strategy.police_brain:PoliceBrain",
}
"""Used when a ``[strategy]`` key is absent, per the rulebook's default."""


class StrategyError(ValueError):
    """Raised when a configured brain cannot be loaded or is not a brain."""


def load_brain(
    strategy: dict[str, Any] | None,
    role: str = "thief",
    axes: AxisConvention | None = None,
    seed: int = 0,
    trash_talk: dict[str, Any] | None = None,
) -> BrainBase:
    """Build the configured brain for ``role``, or the shipped default.

    ``trash_talk`` is the private, non-negotiated provider table (Appendix F
    table 21). Omitted, the brain speaks with the zero-token template voice.

    Raises:
        StrategyError: if the reference is malformed, cannot be imported, or
            does not subclass :class:`BrainBase`. Failing at load is the point:
            a missing brain discovered at move one is a forfeited match.
    """
    if role not in DEFAULT_BRAINS:
        raise StrategyError(f"role must be one of {sorted(DEFAULT_BRAINS)}, got {role!r}")
    spec = (strategy or {}).get(f"{role}_class") or DEFAULT_BRAINS[role]
    if not isinstance(spec, str) or spec.count(":") != 1:
        raise StrategyError(f"{role}_class must be 'package.module:Class', got {spec!r}")
    module_name, _, class_name = spec.partition(":")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise StrategyError(f"cannot import {module_name!r}: {exc}") from exc
    brain_class = getattr(module, class_name, None)
    if brain_class is None:
        raise StrategyError(f"{module_name!r} has no {class_name!r}")
    if not (isinstance(brain_class, type) and issubclass(brain_class, BrainBase)):
        raise StrategyError(f"{spec} does not subclass BrainBase")
    built = brain_class(
        axes=axes or AxisConvention(), seed=seed, voice=build_voice(trash_talk, seed)
    )
    if not isinstance(built, BrainBase):  # pragma: no cover - defensive
        raise StrategyError(f"{spec} did not construct a BrainBase")
    return built


def load_brains(
    strategy: dict[str, Any] | None,
    axes: AxisConvention | None = None,
    seed: int = 0,
    trash_talk: dict[str, Any] | None = None,
) -> dict[str, BrainBase]:
    """Both roles' brains, keyed by role, each with its own voice.

    Two separate voices rather than one shared: a voice owns a seeded stream
    and a spent-token count, and the report's rule 54 total is the **sum** over
    both, read by whoever assembles it.
    """
    return {
        role: load_brain(strategy, role, axes, seed, trash_talk) for role in sorted(DEFAULT_BRAINS)
    }


__all__ = ["DEFAULT_BRAINS", "BrainBase", "StrategyError", "load_brain", "load_brains"]
