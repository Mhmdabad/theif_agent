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
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from .bluff import Bluff
from .hints import MAX_WORDS, truncate

logger = logging.getLogger(__name__)

PROVIDERS = ("template", "ollama", "claude_api", "claude_cli")
"""Selectable providers, cheapest first. ``template`` is the default."""

DEFAULT_PROVIDER = "template"
DEFAULT_MODEL = "claude-haiku-4-5"
"""The rulebook asks for a *small* cloud model; a fifteen-word hint needs no
more, and the cheapest option leaves the series budget for more turns."""

PROMPT = (
    "You are taunting an opponent in a pursuit game. Rewrite this hint in at "
    "most {cap} words, keeping its meaning and naming no coordinates: {text}"
)
"""The model rephrases a hint we already composed. It never invents the claim.

Handing it the board and asking where to point would put a language model in
charge of a spatial decision, which the rulebook reserves for the algorithm —
and which models are demonstrably bad at.
"""


@dataclass
class Bluffer:
    """Produces hint text under a selected provider, falling back on failure."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    endpoint: str = "http://localhost:11434"
    timeout: float = 10.0
    failures: int = 0
    calls: int = field(default=0)

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

    def _prompt(self, text: str) -> str:
        return PROMPT.format(cap=MAX_WORDS, text=text)

    def _ollama(self, text: str) -> str:
        """A local model. Zero API tokens and no rate limit."""
        import json
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "prompt": self._prompt(text), "stream": False}
        ).encode()
        request = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            body = json.loads(response.read())
        return str(body.get("response", ""))

    def _claude_api(self, text: str) -> str:
        """A small cloud model. Counted against the series token budget.

        The key is read from the environment by the SDK and never from config
        — a committed key is permanently leaked, and the submission checklist
        makes that a hard gate.
        """
        import anthropic  # type: ignore[import-not-found]

        message = anthropic.Anthropic().messages.create(
            model=self.model,
            max_tokens=64,
            messages=[{"role": "user", "content": self._prompt(text)}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    def _claude_cli(self, text: str) -> str:
        """``claude -p``. The highest cost, and subscription-bound.

        Guarded by a timeout well inside the turn deadline: a CLI that hangs
        would cost the match, not the hint.
        """
        binary = shutil.which("claude")
        if binary is None:
            raise FileNotFoundError("claude CLI not on PATH")
        finished = subprocess.run(
            [binary, "-p", self._prompt(text)],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=True,
        )
        return finished.stdout

    def __str__(self) -> str:
        return f"{self.provider}: {self.calls} call(s), {self.failures} fallback(s)"
