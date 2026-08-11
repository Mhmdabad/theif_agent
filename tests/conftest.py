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
