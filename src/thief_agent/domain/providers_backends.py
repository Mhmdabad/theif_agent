"""The three paid or hosted ways to rephrase a hint, and what each one costs.

Split out of :mod:`.providers`, which owns the fallback rule these implement
under. Mixed into :class:`~.providers.Bluffer`; every attribute is read off
``self`` at the moment of the call, so a provider swapped mid-series — which
:meth:`~.budgeting.Ration.stop` does when the budget runs out — takes effect
on the next turn rather than on a copy taken at construction.

**Each backend reports what it actually spent.** The token ledger the final
report carries (Appendix E rule 54) is only as honest as this number, and an
estimate is not a measurement: the cloud model returns its own usage, so that
is what is charged. The two that report nothing — a local model costs no API
tokens, and the CLI bills a subscription rather than the series budget — say
so by leaving :attr:`~.providers.Bluffer.last_tokens` unset, and the ration
falls back to its deliberate over-estimate.

None of these raises to the caller: :meth:`~.providers.Bluffer.dress` catches
everything and answers with the composed template line. That is not defensive
habit — a hint is worth few marks, and a turn that goes unanswered inside the
thirty-second deadline is a technical loss worth **zero to both sides**.
"""

import shutil
import subprocess

from .hints import MAX_WORDS

PROMPT = (
    "You are taunting an opponent in a pursuit game. Rewrite this hint in at "
    "most {cap} words, keeping its meaning and naming no coordinates: {text}"
)
"""The model rephrases a hint we already composed. It never invents the claim.

Handing it the board and asking where to point would put a language model in
charge of a spatial decision, which the rulebook reserves for the algorithm —
and which models are demonstrably bad at.
"""


class Backends:
    """The non-template providers. Values are read off the live Bluffer."""

    model: str
    endpoint: str
    timeout: float
    last_tokens: int | None

    def _prompt(self, text: str) -> str:
        return PROMPT.format(cap=MAX_WORDS, text=text)

    def _ollama(self, text: str) -> str:
        """A local model. Zero API tokens, so nothing is charged to the series."""
        import json  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

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
        """A small cloud model, charged against the series token budget.

        The key is read from the environment by the SDK and never from config:
        a committed key is permanently leaked, and Appendix C makes that a hard
        submission gate.

        ``max_tokens`` is deliberately tiny. The reply is capped at fifteen
        words by Appendix F either way, so a larger ceiling would buy nothing
        and spend a budget six sub-games have to share.

        The usage the API reports is recorded rather than estimated — it is
        what rule 54's total is built from, and the one number here that a
        reader of the final report is entitled to trust.
        """
        import anthropic  # type: ignore[import-not-found]  # noqa: PLC0415

        message = anthropic.Anthropic().messages.create(
            model=self.model,
            max_tokens=64,
            messages=[{"role": "user", "content": self._prompt(text)}],
        )
        usage = getattr(message, "usage", None)
        if usage is not None:
            self.last_tokens = int(usage.input_tokens) + int(usage.output_tokens)
        return "".join(block.text for block in message.content if block.type == "text")

    def _claude_cli(self, text: str) -> str:
        """``claude -p``. Subscription-billed, so nothing is charged here.

        Guarded by a timeout well inside the turn deadline: a CLI that hangs
        would cost the match, not merely the hint.
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
