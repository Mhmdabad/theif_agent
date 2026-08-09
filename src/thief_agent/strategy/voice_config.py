"""Building a :class:`~.voice.Voice` from the private ``[trash_talk]`` table.

Appendix F table 21 lists four providers and says the choice is *private to
each peer* — it is not part of the agreed configuration and is not negotiated,
so it lives in the private TOML and never in the digest both sides compare.

**The key is ``provider``, and it was read as ``model``.** The shipped config
documents ``provider = "template" | ollama | claude_api | claude_cli``, while
the only line that read this table asked for ``trash_talk.model`` — so
uncommenting the documented key selected nothing and the declaration recorded
``template`` regardless. Both names are accepted here: ``provider`` is the one
the config documents, and ``model`` is read as the model id it looks like.

An unknown provider is refused at load rather than at move one. A typo that
silently fell back to the template would be discovered as a missing capability
halfway through a series, which is exactly when nothing can be done about it.
"""

from typing import Any

from ..domain.budgeting import EVERY_N_STEPS, Ration
from ..domain.providers import DEFAULT_MODEL, DEFAULT_PROVIDER, PROVIDERS, Bluffer
from .voice import Voice

__all__ = ["build_voice"]


def build_voice(trash_talk: dict[str, Any] | None, seed: int = 0) -> Voice:
    """The voice this peer speaks with, from its private configuration.

    Absent or empty configuration yields the zero-token template voice, which
    is the rulebook's recommended route and the default in code.

    Raises:
        ValueError: naming the valid providers, if the configured one is not
            one of them.
    """
    table = trash_talk or {}
    provider = str(table.get("provider", DEFAULT_PROVIDER))
    if provider not in PROVIDERS:
        raise ValueError(f"[trash_talk] provider must be one of {PROVIDERS}, got {provider!r}")
    bluffer = Bluffer(
        provider=provider,
        model=str(table.get("model", DEFAULT_MODEL)),
        endpoint=str(table.get("endpoint", "http://localhost:11434")),
    )
    return Voice(
        ration=Ration(
            bluffer=bluffer,
            every_n_steps=int(table.get("every_n_steps", EVERY_N_STEPS)),
        ),
        seed=seed,
    )
