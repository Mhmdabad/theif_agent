"""Sending the report, against a fake that counts and never mails anybody.

**No test here touches Google.** The failure mode of getting that wrong is real
mail arriving in a lecturer's inbox, so the API is a Protocol and every rule is
checked against a stand-in. CI has no credentials and these repositories are
public; a test that tried a real send would fail there and be wrong to pass.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from conftest import TEST_RECIPIENT
from thief_agent.infra.dos_detector import Detector
from thief_agent.infra.gatekeeper import Gatekeeper
from thief_agent.infra.mailer import LECTURER_NOTE, Mailer, SendError, retry_after_of
from thief_agent.infra.quota import Quota
from thief_agent.infra.report import Report, Repositories, SubGameResult
from thief_agent.infra.token_bucket import Limiter, TokenBucket

REPOS = Repositories(
    cop_repo="https://github.com/Mhmdabad/police_agent",
    thief_repo="https://github.com/Mhmdabad/theif_agent",
    opponent_cop_repo="https://github.com/other/police",
    opponent_thief_repo="https://github.com/other/thief",
)


def a_report() -> Report:
    return Report(
        game_id="uoh26-s82kma9e",
        game_uid="u-0001",
        role="police",
        team="uoh26-cops",
        opponent_team="uoh26-others",
        repositories=REPOS,
        sub_games=(SubGameResult(sub_game=1, cop_score=100, thief_score=0, commit_hash="a" * 40),),
        total_tokens=1234,
        agreed=True,
    )


class Clock:
    def __init__(self, at: float = 1000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        self.at += 0.001
        return self.at


class Resp:
    """The ``resp`` object a Google client hangs on its errors."""

    def __init__(self, headers: dict[str, object]) -> None:
        self.status = 429
        self.headers = headers


class TooMany(Exception):
    """What a Google client raises for a 429, in the shape it raises it."""

    def __init__(self, retry_after: object | None = None) -> None:
        super().__init__("Too Many Requests")
        self.resp = Resp({"Retry-After": retry_after} if retry_after is not None else {})


@dataclass
class CountingApi:
    """A stand-in Gmail. Counts, answers, and mails nobody."""

    fail_with: list[Exception] = field(default_factory=list)
    calls: list[dict[str, str]] = field(default_factory=list)

    def send(self, raw: dict[str, str]) -> dict[str, Any]:
        self.calls.append(raw)
        if self.fail_with:
            raise self.fail_with.pop(0)
        return {"id": f"msg-{len(self.calls)}", "labelIds": ["SENT"]}


def a_mailer(
    tmp_path: Path, api: CountingApi | None = None, limit: int = 10, capacity: float = 2.0
) -> tuple[Mailer, CountingApi, Gatekeeper]:
    clock = Clock()
    gate = Gatekeeper(
        detector=Detector(path=tmp_path / ".locked_cop.json", now=clock),
        quota=Quota(path=tmp_path / ".quota_cop.json", limit=limit, now=lambda: datetime.now(UTC)),
        limiter=Limiter(bucket=TokenBucket(capacity=capacity, per_minute=30.0, now=clock)),
    )
    endpoint = api or CountingApi()
    slept: list[float] = []
    mailer = Mailer(gatekeeper=gate, sender=endpoint, sleep=slept.append)
    return mailer, endpoint, gate


class TestAReportGetsSent:
    def test_exactly_one_message_reaches_the_api(self, tmp_path: Path) -> None:
        mailer, api, _ = a_mailer(tmp_path)
        mailer.send_report(a_report(), "cop@example.com")
        assert len(api.calls) == 1

    def test_the_api_answer_comes_back(self, tmp_path: Path) -> None:
        mailer, _, _ = a_mailer(tmp_path)
        assert mailer.send_report(a_report(), "cop@example.com")["labelIds"] == ["SENT"]

    def test_what_is_sent_is_the_json_attachment(self, tmp_path: Path) -> None:
        """Never free text — FR-7.23 rejects a report that cannot be parsed."""
        import base64
        from email import message_from_bytes
        from email.policy import default

        mailer, api, _ = a_mailer(tmp_path)
        mailer.send_report(a_report(), "cop@example.com")
        mime = message_from_bytes(base64.urlsafe_b64decode(api.calls[0]["raw"]), policy=default)
        attached = next(mime.iter_attachments()).get_payload(decode=True)
        assert isinstance(attached, bytes)
        assert json.loads(attached)["game_uid"] == "u-0001"

    def test_it_goes_to_the_hard_coded_lecturer(self, tmp_path: Path) -> None:
        import base64
        from email import message_from_bytes
        from email.policy import default

        mailer, api, _ = a_mailer(tmp_path)
        mailer.send_report(a_report(), "cop@example.com")
        mime = message_from_bytes(base64.urlsafe_b64decode(api.calls[0]["raw"]), policy=default)
        assert mime["To"] == TEST_RECIPIENT


class TestTheGatesAreInFrontOfIt:
    def test_a_quota_slot_is_spent(self, tmp_path: Path) -> None:
        mailer, _, gate = a_mailer(tmp_path)
        mailer.send_report(a_report(), "cop@example.com")
        assert gate.quota.used() == 1

    def test_the_attempt_reaches_the_dos_detector(self, tmp_path: Path) -> None:
        mailer, _, gate = a_mailer(tmp_path)
        mailer.send_report(a_report(), "cop@example.com")
        assert len(gate.detector.recent) == 1

    def test_an_exhausted_quota_stops_it_before_the_api(self, tmp_path: Path) -> None:
        mailer, api, _ = a_mailer(tmp_path, limit=1)
        mailer.send_report(a_report(), "cop@example.com")
        with pytest.raises(SendError, match="quota"):
            mailer.send_report(a_report(), "cop@example.com")
        assert len(api.calls) == 1, "a refused report still reached the API"

    def test_a_locked_pipeline_stops_it_before_the_api(self, tmp_path: Path) -> None:
        mailer, api, gate = a_mailer(tmp_path)
        (tmp_path / ".locked_cop.json").write_text(json.dumps({"reason": "earlier storm"}))
        with pytest.raises(SendError, match="DOS detector"):
            mailer.send_report(a_report(), "cop@example.com")
        assert api.calls == []

    def test_the_refusal_says_the_report_was_not_sent(self, tmp_path: Path) -> None:
        """A caller must not read a refusal as 'probably fine'."""
        mailer, _, _ = a_mailer(tmp_path)
        (tmp_path / ".locked_cop.json").write_text(json.dumps({"reason": "x"}))
        with pytest.raises(SendError, match="the report was not sent"):
            mailer.send_report(a_report(), "cop@example.com")

    def test_an_empty_bucket_waits_rather_than_refusing(self, tmp_path: Path) -> None:
        """A wait is not a refusal, and waiting must not cost a quota slot."""
        mailer, api, gate = a_mailer(tmp_path, capacity=2.0)
        for _ in range(3):
            mailer.send_report(a_report(), "cop@example.com")
        assert len(api.calls) == 3
        assert mailer.waits, "the third send should have waited for a token"


class TestA429IsHonouredNotRetried:
    def test_it_backs_off_and_then_succeeds(self, tmp_path: Path) -> None:
        api = CountingApi(fail_with=[TooMany()])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender = api
        mailer.send_report(a_report(), "cop@example.com")
        assert len(api.calls) == 2
        assert any("429" in note for note in mailer.waits)

    def test_it_never_retries_without_waiting(self, tmp_path: Path) -> None:
        """FR-7.22: insisting is what gets an account suspended."""
        slept: list[float] = []
        api = CountingApi(fail_with=[TooMany()])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender, mailer.sleep = api, slept.append
        mailer.send_report(a_report(), "cop@example.com")
        assert slept and all(pause > 0 for pause in slept)

    def test_the_providers_retry_after_is_honoured_when_longer(self, tmp_path: Path) -> None:
        slept: list[float] = []
        api = CountingApi(fail_with=[TooMany(retry_after="90")])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender, mailer.sleep = api, slept.append
        mailer.send_report(a_report(), "cop@example.com")
        assert 90.0 in slept

    def test_a_persistent_429_stops_rather_than_insisting(self, tmp_path: Path) -> None:
        api = CountingApi(fail_with=[TooMany() for _ in range(6)])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender = api
        with pytest.raises(SendError, match="retry budget is spent"):
            mailer.send_report(a_report(), "cop@example.com")

    def test_the_giving_up_message_explains_why(self, tmp_path: Path) -> None:
        api = CountingApi(fail_with=[TooMany() for _ in range(6)])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender = api
        with pytest.raises(SendError, match="suspended"):
            mailer.send_report(a_report(), "cop@example.com")

    def test_every_attempt_is_recorded_including_the_failures(self, tmp_path: Path) -> None:
        """A loop that fails every time is the one most likely to be running."""
        api = CountingApi(fail_with=[TooMany()])
        mailer, _, gate = a_mailer(tmp_path)
        mailer.sender = api
        mailer.send_report(a_report(), "cop@example.com")
        assert len(gate.detector.recent) == 2


class TestOtherFailuresAreNotSwallowed:
    def test_a_non_429_error_propagates(self, tmp_path: Path) -> None:
        """Only a 429 means 'wait'. Everything else is the caller's problem."""

        class Broken(Exception):
            status_code = 500

        api = CountingApi(fail_with=[Broken()])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender = api
        with pytest.raises(Broken):
            mailer.send_report(a_report(), "cop@example.com")

    def test_it_is_not_retried(self, tmp_path: Path) -> None:
        class Broken(Exception):
            status_code = 500

        api = CountingApi(fail_with=[Broken(), Broken()])
        mailer, _, _ = a_mailer(tmp_path)
        mailer.sender = api
        with pytest.raises(Broken):
            mailer.send_report(a_report(), "cop@example.com")
        assert len(api.calls) == 1


class TestReadingRetryAfter:
    def test_from_a_google_style_header(self) -> None:
        assert retry_after_of(TooMany(retry_after="42")) == 42.0

    def test_a_lowercase_header(self) -> None:
        error = TooMany()
        error.resp.headers = {"retry-after": "7"}
        assert retry_after_of(error) == 7.0

    def test_a_direct_attribute(self) -> None:
        class Simple:
            retry_after = 12

        assert retry_after_of(Simple()) == 12.0

    def test_nothing_at_all(self) -> None:
        assert retry_after_of(ValueError("network")) is None

    def test_a_header_that_is_not_a_number(self) -> None:
        """Some servers send a date. Unparseable is 'no advice', not a crash."""
        assert retry_after_of(TooMany(retry_after="Wed, 21 Oct 2026 07:28:00 GMT")) is None

    def test_a_header_of_the_wrong_type(self) -> None:
        error = TooMany()
        error.resp.headers = {"Retry-After": []}
        assert retry_after_of(error) is None


class TestNothingHereMailsAnybody:
    def test_the_module_names_no_credentials(self) -> None:
        source = (
            Path(__file__).resolve().parent.parent / "src/thief_agent/infra/mailer.py"
        ).read_text()
        assert "credentials.json" not in source
        assert "token_cop.json" not in source

    def test_the_note_says_a_real_send_is_a_human_decision(self) -> None:
        assert "not" in LECTURER_NOTE.lower()
