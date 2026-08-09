"""Selecting a brain from the private configuration.

The rulebook's contract: point ``[strategy] thief_class`` at a class in
``package.module:Class`` form, or leave the section absent to run the shipped
heuristic. Nothing else in the system needs to know which brain is loaded, which
is the point — swapping the decision engine must touch one config key.
"""

from importlib import import_module
from typing import Any

from ..domain.axes import AxisConvention
from .base import BrainBase
from .thief_brain import ThiefBrain
from .voice_config import build_voice

DEFAULT_BRAIN = "thief_agent.strategy.thief_brain:ThiefBrain"
"""Used when ``[strategy]`` is absent, per the rulebook's default."""


class StrategyError(ValueError):
    """Raised when the configured brain cannot be loaded or is not a brain."""


def load_brain(
    strategy: dict[str, Any] | None,
    axes: AxisConvention | None = None,
    seed: int = 0,
    trash_talk: dict[str, Any] | None = None,
) -> BrainBase:
    """Build the configured brain, or the shipped default.

    ``trash_talk`` is the private, non-negotiated provider table (Appendix F
    table 21). Omitted, the brain speaks with the zero-token template voice.

    Raises:
        StrategyError: if the reference is malformed, cannot be imported, or
            does not subclass :class:`BrainBase`. Failing at load is the point:
            a missing brain discovered at move one is a forfeited match.
    """
    spec = (strategy or {}).get("thief_class") or DEFAULT_BRAIN
    if not isinstance(spec, str) or spec.count(":") != 1:
        raise StrategyError(f"thief_class must be 'package.module:Class', got {spec!r}")
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


__all__ = ["DEFAULT_BRAIN", "BrainBase", "ThiefBrain", "StrategyError", "load_brain"]
