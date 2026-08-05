"""Structured JSON as an attachment, and no way to send prose instead."""

import base64
import json
from email import message_from_bytes
from email.policy import default as default_policy
from pathlib import Path

import pytest

import thief_agent
from thief_agent.infra.report import (
    LECTURER,
    SCHEMA_VERSION,
    Message,
    Report,
    ReportError,
    Repositories,
    SubGameResult,
)

REPOS = Repositories(
    cop_repo="https://github.com/Mhmdabad/police_agent",
    thief_repo="https://github.com/Mhmdabad/theif_agent",
    opponent_cop_repo="https://github.com/other/police",
    opponent_thief_repo="https://github.com/other/thief",
)


def result(sub_game: int = 1, cop: int = 100, thief: int = 0) -> SubGameResult:
    return SubGameResult(
        sub_game=sub_game,
        cop_score=cop,
        thief_score=thief,
        commit_hash=f"{sub_game:040x}",
        steps=17,
    )


def report(**overrides: object) -> Report:
    fields: dict[str, object] = {
        "game_id": "uoh26-s82kma9e",
        "role": "thief",
        "team": "uoh26-thieves",
        "opponent_team": "uoh26-others",
        "repositories": REPOS,
        "sub_games": (result(1), result(2, cop=0, thief=80)),
        "total_tokens": 41_233,
        "agreed": True,
    }
    fields.update(overrides)
    return Report(**fields)  # type: ignore[arg-type]


class TestTheReportIsAStructure:
    def test_it_serialises_to_json(self) -> None:
        assert json.loads(report().to_json())["game_id"] == "uoh26-s82kma9e"

    def test_it_carries_a_schema_version(self) -> None:
        """A parser needs to know what it is reading before it reads it."""
        assert json.loads(report().to_json())["schema_version"] == SCHEMA_VERSION

    def test_the_bytes_are_stable_between_peers(self) -> None:
        """Sorted keys, so two sides with the same result produce the same file."""
        assert report().to_json() == report().to_json()
        assert report().to_json().endswith("}\n")

    def test_totals_are_derived_not_restated(self) -> None:
        body = json.loads(report().to_json())
        assert body["totals"]["cop"] == 100
        assert body["totals"]["thief"] == 80
        assert body["totals"]["sub_games_played"] == 2

    def test_the_filename_derives_from_the_game_id(self) -> None:
        """So files from different matches can never be mixed up."""
        assert report().filename == "result_uoh26-s82kma9e.json"


class TestTheMandatoryFieldsAreRequiredNotValidated:
    def test_all_four_repository_links_are_required(self) -> None:
        with pytest.raises(ReportError, match="four repository links"):
            Repositories(
                cop_repo="https://github.com/Mhmdabad/police_agent",
                thief_repo="",
                opponent_cop_repo="https://github.com/other/police",
                opponent_thief_repo="https://github.com/other/thief",
            )

    def test_the_four_links_reach_the_json(self) -> None:
        links = json.loads(report().to_json())["repositories"]
        assert len(links) == 4
        assert all(links.values())

    def test_every_sub_game_needs_a_commit_hash(self) -> None:
        """FR-7.28. Without it nobody can say which code played the game."""
        with pytest.raises(ReportError, match="no commit hash"):
            SubGameResult(sub_game=1, cop_score=0, thief_score=0, commit_hash="")

    def test_the_commit_hashes_reach_the_json(self) -> None:
        played = json.loads(report().to_json())["sub_games"]
        assert [entry["commit_hash"] for entry in played] == [f"{1:040x}", f"{2:040x}"]

    def test_total_tokens_reaches_the_json(self) -> None:
        assert json.loads(report().to_json())["totals"]["total_tokens"] == 41_233

    def test_a_negative_token_total_is_refused(self) -> None:
        with pytest.raises(ReportError, match="cannot be negative"):
            report(total_tokens=-1)

    def test_sub_games_are_numbered_from_one(self) -> None:
        with pytest.raises(ReportError, match="numbered from 1"):
            SubGameResult(sub_game=0, cop_score=0, thief_score=0, commit_hash="abc")

    def test_a_report_with_no_sub_games_is_refused(self) -> None:
        with pytest.raises(ReportError, match="describes no match"):
            report(sub_games=())

    def test_repeated_sub_game_numbers_are_refused(self) -> None:
        with pytest.raises(ReportError, match="numbers repeat"):
            report(sub_games=(result(1), result(1)))


class TestAgreementIsRecorded:
    def test_it_says_whether_both_teams_agreed(self) -> None:
        """FR-7.16: a contradicting report voids the match and scores 0 for both."""
        assert json.loads(report().to_json())["result_agreed_with_opponent"] is True
        assert json.loads(report(agreed=False).to_json())["result_agreed_with_opponent"] is False

    def test_a_technical_loss_is_marked_per_sub_game(self) -> None:
        void = SubGameResult(
            sub_game=1, cop_score=0, thief_score=0, commit_hash="abc", technical_loss=True
        )
        assert json.loads(report(sub_games=(void,)).to_json())["sub_games"][0]["technical_loss"]


class TestTheAttachmentIsTheReport:
    def test_the_json_is_attached_as_a_file(self) -> None:
        mail = Message(report=report(), sender="thief@example.com").build()
        attachments = list(mail.iter_attachments())
        assert len(attachments) == 1
        assert attachments[0].get_filename() == "result_uoh26-s82kma9e.json"

    def test_the_attachment_is_application_json(self) -> None:
        """Not text/plain, which is what makes a parser skip it."""
        mail = Message(report=report(), sender="thief@example.com").build()
        assert next(mail.iter_attachments()).get_content_type() == "application/json"

    def test_the_attachment_round_trips_to_the_same_structure(self) -> None:
        mail = Message(report=report(), sender="thief@example.com").build()
        payload = next(mail.iter_attachments()).get_payload(decode=True)
        assert isinstance(payload, bytes)
        assert json.loads(payload) == report().to_dict()

    def test_the_body_carries_nothing_a_parser_would_want(self) -> None:
        """A summary in the body is a second copy of the truth."""
        body = Message(report=report(), sender="thief@example.com").body()
        assert "100" not in body
        assert "41233" not in body
        assert "not machine-readable on purpose" in body

    def test_the_destination_is_the_hard_coded_lecturer_address(self) -> None:
        mail = Message(report=report(), sender="thief@example.com").build()
        assert mail["To"] == LECTURER == "rmisegal+uoh26finalgame@gmail.com"

    def test_the_subject_names_the_game_and_the_role(self) -> None:
        subject = Message(report=report(), sender="thief@example.com").subject()
        assert "uoh26-s82kma9e" in subject
        assert "thief" in subject


class TestTheGmailPayload:
    def test_it_is_url_safe_base64(self) -> None:
        raw = Message(report=report(), sender="thief@example.com").raw()["raw"]
        assert "+" not in raw and "/" not in raw

    def test_it_decodes_back_to_the_mime_message(self) -> None:
        message = Message(report=report(), sender="thief@example.com")
        decoded = message_from_bytes(
            base64.urlsafe_b64decode(message.raw()["raw"]), policy=default_policy
        )
        assert decoded["To"] == LECTURER

    def test_the_attachment_survives_the_encoding(self) -> None:
        """The end-to-end path: report → MIME → base64 → back to a dict."""
        message = Message(report=report(), sender="thief@example.com")
        decoded = message_from_bytes(
            base64.urlsafe_b64decode(message.raw()["raw"]), policy=default_policy
        )
        attached = next(decoded.iter_attachments()).get_payload(decode=True)
        assert isinstance(attached, bytes)
        assert json.loads(attached)["totals"]["total_tokens"] == 41_233

    def test_building_twice_does_not_attach_twice(self) -> None:
        message = Message(report=report(), sender="thief@example.com")
        message.build()
        decoded = message_from_bytes(
            base64.urlsafe_b64decode(message.raw()["raw"]), policy=default_policy
        )
        assert len(list(decoded.iter_attachments())) == 1

    def test_raw_builds_on_demand(self) -> None:
        assert "raw" in Message(report=report(), sender="thief@example.com").raw()


class TestThereIsNoFreeTextPath:
    """FR-7.23: prose that cannot be parsed automatically is rejected outright."""

    def test_the_module_offers_no_way_to_send_a_prose_report(self) -> None:
        """An escape hatch that exists gets used at 2am by somebody in a hurry."""
        source = (Path(thief_agent.__file__).parent / "infra" / "report.py").read_text()
        for smell in ("set_content(report", "plain_text", "as_text", "send_text"):
            assert smell not in source, f"a free-text path appeared: {smell}"

    def test_the_only_attachment_type_is_json(self) -> None:
        from thief_agent.infra.report import CONTENT_TYPE

        assert CONTENT_TYPE == ("application", "json")

    def test_the_destination_is_not_configurable_from_outside(self) -> None:
        """A configurable address is one typo from a report that never arrives."""
        source = (Path(thief_agent.__file__).parent / "infra" / "report.py").read_text()
        assert 'LECTURER = "rmisegal+uoh26finalgame@gmail.com"' in source
        assert "getenv" not in source and "environ" not in source


class TestTheResultFileOnDisk:
    """FR-7.28's binding report, written where the repository can carry it."""

    def test_the_name_derives_from_the_game_id(self) -> None:
        assert report().filename == "result_uoh26-s82kma9e.json"

    def test_it_writes_and_reads_back(self, tmp_path: Path) -> None:
        path = report().write(tmp_path)
        assert json.loads(path.read_text()) == report().to_dict()

    def test_it_creates_the_directory(self, tmp_path: Path) -> None:
        assert report().write(tmp_path / "artefacts" / "deep").exists()

    def test_the_file_and_the_attachment_are_the_same_bytes(self, tmp_path: Path) -> None:
        """One serialisation, so the committed copy cannot drift from the sent one."""
        written = report().write(tmp_path).read_bytes()
        mail = Message(report=report(), sender="thief@example.com").build()
        attached = next(mail.iter_attachments()).get_payload(decode=True)
        assert attached == written

    def test_the_bytes_are_stable_between_writes(self, tmp_path: Path) -> None:
        assert (
            report().write(tmp_path / "a").read_text() == report().write(tmp_path / "b").read_text()
        )

    def test_it_carries_the_game_uid(self, tmp_path: Path) -> None:
        body = json.loads(report(game_uid="u-0001").write(tmp_path).read_text())
        assert body["game_uid"] == "u-0001"

    def test_the_commit_hashes_and_token_total_survive_the_round_trip(self, tmp_path: Path) -> None:
        """The three things FR-7.28 names, read back off disk."""
        body = json.loads(report().write(tmp_path).read_text())
        assert [entry["commit_hash"] for entry in body["sub_games"]] == [f"{1:040x}", f"{2:040x}"]
        assert body["totals"]["total_tokens"] == 41_233
        assert len(body["repositories"]) == 4
