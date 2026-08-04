"""Tests for the four bluff providers (#68).

Nothing here makes a real network call. CI has no API key — the repo is
public — and a test that needs the network is a test that fails when the
network hiccups.
"""

import pytest

from thief_agent.domain.bluff import Bluff
from thief_agent.domain.hints import MAX_WORDS, NUMERIC
from thief_agent.domain.providers import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    PROVIDERS,
    Bluffer,
)

HINT = Bluff(intent="truth", text="heading south past the docks", about=(5, 1))


class TestTheDefault:
    def test_template_is_the_default(self) -> None:
        """#68's acceptance criterion, and the rulebook's recommended route."""
        assert DEFAULT_PROVIDER == "template"
        assert Bluffer().provider == "template"

    def test_it_returns_the_composed_line_unchanged(self) -> None:
        assert Bluffer().dress(HINT) == HINT.text

    def test_it_makes_no_call_at_all(self) -> None:
        """Zero tokens, and nothing that can time out inside a 30s turn."""
        bluffer = Bluffer()
        bluffer.dress(HINT)
        assert bluffer.calls == 0

    def test_all_four_are_offered(self) -> None:
        assert PROVIDERS == ("template", "ollama", "claude_api", "claude_cli")

    def test_the_cloud_model_is_a_small_one(self) -> None:
        """The rulebook asks for a small cloud model; 15 words needs no more."""
        assert DEFAULT_MODEL == "claude-haiku-4-5"

    @pytest.mark.parametrize("bad", ["gpt", "", "TEMPLATE"])
    def test_an_unknown_provider_is_refused_at_construction(self, bad: str) -> None:
        with pytest.raises(ValueError, match="provider must be one of"):
            Bluffer(provider=bad)


class TestEveryFailureFallsBack:
    """No hint is worth a lost turn."""

    @pytest.mark.parametrize("provider", ["ollama", "claude_api", "claude_cli"])
    def test_a_broken_backend_returns_the_template_line(self, provider: str) -> None:
        bluffer = Bluffer(provider=provider, endpoint="http://localhost:1", timeout=0.2)
        assert bluffer.dress(HINT) == HINT.text
        assert bluffer.failures == 1

    def test_it_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(
            bluffer, "_ollama", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert bluffer.dress(HINT) == HINT.text

    def test_an_empty_response_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A model that returns nothing is a failure, not a silent hint."""
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(bluffer, "_ollama", lambda _: "   ")
        assert bluffer.dress(HINT) == HINT.text

    def test_the_fallback_is_counted_for_the_audit(self) -> None:
        bluffer = Bluffer(provider="claude_cli", timeout=0.2)
        bluffer.dress(HINT)
        assert "1 fallback" in str(bluffer)


class TestWhatAModelIsAllowedToDo:
    def test_it_rephrases_a_hint_we_already_composed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It never invents the claim. Asking a model where to point would put
        it in charge of a spatial decision the rulebook reserves for the
        algorithm — and which models are demonstrably bad at."""
        bluffer = Bluffer(provider="ollama")
        seen: list[str] = []

        def record(prompt: str) -> str:
            seen.append(prompt)
            return "you'll never catch me"

        monkeypatch.setattr(bluffer, "_ollama", record)
        bluffer.dress(HINT)
        assert HINT.text in seen[0]

    def test_a_long_reply_is_cut_to_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cap is ours to honour whatever the model returns."""
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(bluffer, "_ollama", lambda _: " ".join(["word"] * 60))
        assert len(bluffer.dress(HINT).split()) == MAX_WORDS

    def test_a_usable_reply_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(bluffer, "_ollama", lambda _: "good luck finding me tonight")
        assert bluffer.dress(HINT) == "good luck finding me tonight"

    def test_the_prompt_forbids_coordinates(self) -> None:
        assert "no coordinates" in Bluffer()._prompt("x").lower()

    def test_a_model_that_emits_coordinates_is_still_our_violation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recorded as a known gap: the cap is enforced, the coordinate ban is
        asked for in the prompt but not verified on the way out. A vetting
        step belongs here once the parser is wired into the send path."""
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(bluffer, "_ollama", lambda _: "I am at 3,4")
        assert NUMERIC.search(bluffer.dress(HINT))


class TestCountingForTheAudit:
    def test_calls_are_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bluffer = Bluffer(provider="ollama")
        monkeypatch.setattr(bluffer, "_ollama", lambda _: "fine")
        for _ in range(3):
            bluffer.dress(HINT)
        assert bluffer.calls == 3 and bluffer.failures == 0

    def test_the_template_provider_counts_nothing(self) -> None:
        bluffer = Bluffer()
        for _ in range(5):
            bluffer.dress(HINT)
        assert bluffer.calls == 0


class TestTheAdaptersThemselves:
    """The three backend bodies, with the transport faked.

    No real call is made — CI has no API key and the repo is public — but the
    adapters are still the code that runs in a match, so they are exercised
    rather than pragma'd out.
    """

    def test_ollama_posts_and_reads_the_response_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io
        import urllib.request
        from collections.abc import Iterator
        from contextlib import contextmanager

        @contextmanager
        def fake_open(request: object, timeout: float = 0.0) -> Iterator[io.BytesIO]:
            yield io.BytesIO(b'{"response": "faked reply"}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_open)
        assert Bluffer(provider="ollama")._ollama("hint") == "faked reply"

    def test_claude_cli_raises_when_the_binary_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing CLI must surface as a failure so dress() falls back."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        with pytest.raises(FileNotFoundError, match="not on PATH"):
            Bluffer(provider="claude_cli")._claude_cli("hint")

    def test_claude_cli_returns_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil
        import subprocess

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="cli reply", stderr=""),
        )
        assert Bluffer(provider="claude_cli")._claude_cli("hint") == "cli reply"

    def test_claude_api_sends_the_prompt_and_reads_the_text_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Faked SDK — CI has no key and the repo is public."""
        import sys
        import types

        block = types.SimpleNamespace(type="text", text="api reply")
        message = types.SimpleNamespace(content=[block])
        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda: types.SimpleNamespace(  # type: ignore[attr-defined]
            messages=types.SimpleNamespace(create=lambda **_: message)
        )
        monkeypatch.setitem(sys.modules, "anthropic", fake)
        assert Bluffer(provider="claude_api")._claude_api("hint") == "api reply"

    def test_claude_api_fails_softly_when_the_sdk_is_absent(self) -> None:
        """The key is read from the environment by the SDK, never from config:
        a committed key is permanently leaked and the submission checklist
        makes that a hard gate. With no SDK installed this raises, and dress()
        turns that into a template line."""
        assert Bluffer(provider="claude_api").dress(HINT) == HINT.text
