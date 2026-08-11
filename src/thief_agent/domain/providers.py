"""Four ways to produce a hint, behind one interface.

The rulebook lists them by cost: ``template`` (pre-written lines, **zero
tokens, the default**), ``ollama`` (a local model, zero API tokens, no rate
limit), ``claude_api`` (a small cloud model, counted against the series token
budget) and ``claude_cli`` (``claude -p``, the highest cost, subscription).

``template`` is the default in code, not merely the recommended one, and the
reason is not thrift. It cannot time out inside a thirty-second turn — and a
turn that goes unanswered is a technical loss worth **zero to both sides**,
which is a worse outcome than any hint could be good. It also replays
identically, which the audit depends on.

**Every provider falls back to the template on failure.** A network hiccup, a
missing binary, an exhausted budget: all of them return a template line rather
than raising. The verbal layer is worth few marks and the movement algorithm
is worth many, so nothing here is permitted to lose a match.

The LLM never decides a move. It writes at most fifteen words.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .bluff import Bluff
from .hints import MAX_WORDS, truncate
from .providers_backends import Backends

logger = logging.getLogger(__name__)

PROVIDERS = ("template", "ollama", "claude_api", "claude_cli")
"""Selectable providers, cheapest first. ``template`` is the default."""

DEFAULT_PROVIDER = "template"
DEFAULT_MODEL = "claude-haiku-4-5"
"""The rulebook asks for a *small* cloud model; a fifteen-word hint needs no
more, and the cheapest option leaves the series budget for more turns."""


def declared_model(trash_talk: Mapping[str, object] | None) -> str:
    """What will actually speak, for the Step-0 hardware declaration.

    **The provider decides this, not the model name.** Reading ``model`` alone
    let a declaration announce ``claude-haiku-4-5`` while ``provider`` was
    ``template`` — so every report carried a cloud model beside
    ``total_tokens: 0``, which is a contradiction a marker can see and rule 54
    calls a false statement. The model name is what we *would* use; the provider
    is whether we use anything at all.

    So ``template`` names itself, and any other provider names its model. A
    report is then self-consistent either way: template with no tokens, or a
    model with the tokens it spent.
    """
    table = trash_talk or {}
    provider = str(table.get("provider", DEFAULT_PROVIDER))
    model = str(table.get("model", "")).strip()
    return model if provider != DEFAULT_PROVIDER and model else provider


@dataclass
class Bluffer(Backends):
    """Produces hint text under a selected provider, falling back on failure."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    endpoint: str = "http://localhost:11434"
    timeout: float = 10.0
    failures: int = 0
    calls: int = field(default=0)
    last_tokens: int | None = field(default=None)
    """What the last call actually cost, when the provider says.

    ``None`` means unmeasured rather than free — a local model and the CLI
    both spend nothing from the *series* budget, and the ration substitutes its
    over-estimate. The cloud model reports real usage, and Appendix E rule 54's
    total is built from that rather than from arithmetic nobody can check.
    """

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {PROVIDERS}, got {self.provider!r}")

    def dress(self, bluff: Bluff) -> str:
        """Return hint text, rephrased by the provider or left as composed.

        The template line is computed first and returned unchanged when the
        provider is ``template`` or when anything goes wrong. There is no path
        through this method that raises.
        """
        baseline = truncate(bluff.text, MAX_WORDS)
        if self.provider == DEFAULT_PROVIDER:
            return baseline
        self.calls += 1
        self.last_tokens = None
        try:
            spoken = self._backends()[self.provider](baseline)
        except Exception as failure:  # noqa: BLE001 - no hint is worth a lost turn
            self.failures += 1
            logger.warning("%s failed (%s); falling back to template", self.provider, failure)
            return baseline
        return truncate(spoken.strip(), MAX_WORDS) or baseline

    def _backends(self) -> dict[str, Callable[[str], str]]:
        return {
            "ollama": self._ollama,
            "claude_api": self._claude_api,
            "claude_cli": self._claude_cli,
        }

    def __str__(self) -> str:
        return f"{self.provider}: {self.calls} call(s), {self.failures} fallback(s)"
