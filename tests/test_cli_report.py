"""Appendix E rule 32: the report is mailed by a command, not by a library.

The whole mail pipeline — message, gates, bucket, quota, detector, sender — was
built and tested and had **no caller**. ``python -m thief_agent`` offered
``serve``, ``check`` and ``play``, and none of them could send a report, so a
rule the book states as an obligation was satisfied only by code nobody could
run. This module covers the command that closes that gap.

What is tested here is deliberately everything *except* the send. Each case
below is one where the correct behaviour is to **not** mail: an unreadable file,
a machine still configured for drafts, a result the opponent never confirmed. A
bug in any of them would surface as mail in a real lecturer's inbox rather than
as a failing test, which is the wrong place to find out.

The send itself reaches Google and is covered by everything it is assembled
from: the gate ordering and the 429 rule in ``test_mailer``, the round trip in
``test_report_reload``, the scope refusal in ``test_authorize``.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from conftest import TEST_RECIPIENT
from test_report import report as a_report
from thief_agent.cli_report import report


def arguments(path: Path, send: bool = False, confirm_sha: str = "") -> argparse.Namespace:
    return argparse.Namespace(report=path, send=send, confirm_sha=confirm_sha)


def written(tmp_path: Path, **overrides: object) -> Path:
    """A result file exactly as a finished match would have left it."""
    return a_report(**overrides).write(tmp_path)


def private(mode: str = "draft") -> dict[str, Any]:
    return {"email": {"mode": mode, "sender": "thief@example.com"}}


class TestTheDryRunIsTheDefault:
    def test_without_send_nothing_is_mailed_and_it_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert report(arguments(written(tmp_path)), private()) == 0
        assert "Dry run" in capsys.readouterr().out

    def test_it_names_the_recipient_before_anybody_commits_to_sending(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The destination, shown while there is still time to stop."""
        report(arguments(written(tmp_path)), private())
        assert TEST_RECIPIENT in capsys.readouterr().out

    def test_it_shows_the_score_that_would_be_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = a_report()
        report(arguments(written(tmp_path)), private())
        assert f"cop {body.cop_total}, thief {body.thief_total}" in capsys.readouterr().out


class TestWhatItRefusesToSend:
    def test_a_missing_file_is_an_error_not_a_send(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert report(arguments(tmp_path / "nothing.json", send=True), private("send")) == 1
        assert "cannot read the report" in capsys.readouterr().out

    def test_a_file_that_is_not_a_report_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "result_x.json"
        path.write_text('{"game_id": "x"}\n')
        assert report(arguments(path, send=True), private("send")) == 1

    def test_draft_mode_refuses_even_with_send(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two switches, not one: the flag alone must never reach a lecturer."""
        assert report(arguments(written(tmp_path), send=True), private("draft")) == 1
        assert 'mode is "draft"' in capsys.readouterr().out

    def test_an_unagreed_result_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Rule 35: reporting a score the opponent never confirmed is the thing to avoid."""
        path = written(tmp_path, agreed=False)
        assert report(arguments(path, send=True), private("send")) == 1
        assert "never confirmed" in capsys.readouterr().out

    def test_refusing_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        """A refusal is not a rewrite: the evidence on disk is somebody else's record."""
        path = written(tmp_path, agreed=False)
        before = path.read_text()
        report(arguments(path, send=True), private("send"))
        assert path.read_text() == before


class TestTheAgreementIsVisibleToTheReader:
    def test_matching_peer_sha_marks_the_written_report_agreed(self, tmp_path: Path) -> None:
        path = written(tmp_path, agreed=False, result_claim_sha256="a" * 64)
        digest = json.loads(path.read_text())["mutual_agreement"]["sha256"]
        assert report(arguments(path, confirm_sha=digest), private()) == 0
        assert json.loads(path.read_text())["mutual_agreement"]["confirmed"] is True

    def test_different_peer_sha_is_refused_without_rewriting(self, tmp_path: Path) -> None:
        path = written(tmp_path, agreed=False)
        before = path.read_text()
        assert report(arguments(path, confirm_sha="0" * 64), private()) == 1
        assert path.read_text() == before

    def test_an_agreed_report_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report(arguments(written(tmp_path)), private())
        assert "agreed        yes" in capsys.readouterr().out

    def test_an_unagreed_report_says_so_loudly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report(arguments(written(tmp_path, agreed=False)), private())
        assert "NO — the opponent did not confirm" in capsys.readouterr().out

    def test_the_field_read_back_is_the_field_written(self, tmp_path: Path) -> None:
        """The dry run reads the file, not a memory of what was played."""
        path = written(tmp_path, agreed=False)
        assert json.loads(path.read_text())["mutual_agreement"]["confirmed"] is False


class TestTheStaticMetadataStaysInTheDeclaration:
    def test_the_result_refers_to_the_declaration_for_them(self, tmp_path: Path) -> None:
        """The reference's result omits static team metadata; ours matches it.

        The four links live in the declaration, and the result points back by
        game_id. Repeating them here would be a field the reference's document
        does not carry, in a document defined by matching it.
        """
        body = json.loads(written(tmp_path).read_text())
        assert "repositories" not in body
        assert body["links"]["declaration"] == "declaration_uoh26-s82kma9e.json"
