"""Choosing a provider from the environment rather than from the file.

Split from :mod:`.providers` for the line budget, and because it answers a
different question: that module is *how* each provider speaks, this one is
*which* of them this machine can, which is why the vocabulary lives here and
not there.
"""

import os
from collections.abc import Mapping

__all__ = ["API_KEY_ENV", "AUTO", "CONFIGURABLE", "DEFAULT_PROVIDER", "PROVIDERS", "resolve"]

PROVIDERS = ("template", "ollama", "claude_api", "claude_cli")
"""What a :class:`~.providers.Bluffer` can run, cheapest first."""

DEFAULT_PROVIDER = "template"
"""Zero tokens, no network, and the rulebook's recommended route."""

API_KEY_ENV = "ANTHROPIC_API_KEY"
"""What :data:`AUTO` looks for. Never read from config: a committed key is
permanently leaked, which Appendix C makes a submission gate."""

AUTO = "auto"
"""Use the cloud model when a key is present, and the template when it is not.

For the machine that has no key -- a teammate's laptop, a CI runner, a clone
made five minutes before a match. Configuring ``claude_api`` there would still
play, because every call falls back, but it would *declare* a model it never
reached and report zero tokens beside it. This resolves before the declaration
is written, so what the report says and what the agent does cannot diverge.
"""

CONFIGURABLE = (AUTO, *PROVIDERS)
"""What ``[trash_talk] provider`` accepts: the runnable set plus :data:`AUTO`.

:data:`AUTO` is deliberately not in :data:`~.providers.PROVIDERS`: it is a
choice *between* providers rather than one of them, and a ``Bluffer`` handed it
would have no backend to call.
"""


def resolve(
    trash_talk: Mapping[str, object] | None, environ: Mapping[str, str] | None = None
) -> str:
    """The provider that will actually run, with :data:`AUTO` decided.

    One resolution for both the voice and the declaration. Two would be the
    same defect as none: an agent speaking under one provider while the report
    names another is a false statement under rule 54, and the harder kind to
    notice because each half is separately correct.
    """
    table = trash_talk or {}
    provider = str(table.get("provider", DEFAULT_PROVIDER))
    if provider != AUTO:
        return provider
    source = os.environ if environ is None else environ
    return "claude_api" if source.get(API_KEY_ENV, "").strip() else DEFAULT_PROVIDER
