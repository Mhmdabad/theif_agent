"""Suite-wide fixtures.

The report's destination is read from the environment, so every test that
builds a :class:`~thief_agent.infra.report.Message` needs one to exist. Setting it
here rather than in each module means a test added later cannot forget — and
cannot accidentally assert against whatever the developer has in their own
``.env``, which would be a test that reports the machine rather than the code.
"""

import pytest

from thief_agent.infra.report import RECIPIENT_ENV

TEST_RECIPIENT = "lecturer@example.com"
"""Deliberately not the real address: no test aims mail at a real person."""


@pytest.fixture(autouse=True)
def _recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RECIPIENT_ENV, TEST_RECIPIENT)


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach a paid API, for the same reason none may send mail.

    The ``claude_api`` backend reads its key from the environment, so once the
    SDK became a real dependency the fallback tests stopped simulating a broken
    provider and started billing a live account -- on every run, on every
    developer's machine, flaky with the network and silently costing money.

    Unset, the SDK raises at construction without a request, which is what those
    tests wanted all along: a backend that fails, deterministically and free.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
