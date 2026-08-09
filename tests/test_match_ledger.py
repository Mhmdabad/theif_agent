"""Appendix E rules 37 and 38: the declared games-played count, and its record.

Rule 37 makes every match open with the exact number of games already played;
rule 38 makes a wrong number a breach rather than a slip. The declaration
carried the hardware, the commit, the model and the token ceiling, and **no
count at all** — so the rule had nothing behind it and nothing could be false
because nothing was said.

Two properties matter here and they pull in opposite directions. The count must
be *inside* the signed content, so it cannot be revised after a match goes
badly. And it must be *derivable by a reader*: the ledger lives beside the
artefacts, one entry per committed declaration, so a count that disagrees with
the files around it is visible to the other team rather than only to us.

Rehearsals are the case worth being careful about. Rule 52 allows warm-ups, so a
loopback practice match must not raise the number — an inflated count is a false
declaration reached by carelessness, which rule 38 does not distinguish from one
reached on purpose.
"""

import json
from pathlib import Path

import pytest

from test_localhost_match import build_declaration  # noqa: E402
from thief_agent.infra.declaration_parties import DeclarationError
from thief_agent.infra.match_ledger import LEDGER_FILE, MatchLedger
from thief_agent.runtime.driver_declaration import _record_game
from thief_agent.shared.config import canonical_bytes


def ledger(tmp_path: Path) -> MatchLedger:
    return MatchLedger(tmp_path)


class TestCountingWhatWasPlayed:
    def test_a_fresh_clone_has_played_nothing(self, tmp_path: Path) -> None:
        """Zero is the truth before the first league game, not a placeholder."""
        assert ledger(tmp_path).played() == 0

    def test_each_recorded_game_raises_the_count(self, tmp_path: Path) -> None:
        book = ledger(tmp_path)
        book.record("uoh26-g1", "SMNGRP05", "2026-08-09T10:00:00+00:00")
        book.record("uoh26-g2", "SMNGRP07", "2026-08-09T12:00:00+00:00")
        assert book.played() == 2

    def test_replaying_one_game_does_not_count_it_twice(self, tmp_path: Path) -> None:
        """A series that crashed and was re-run is one game, and the artefacts show one."""
        book = ledger(tmp_path)
        book.record("uoh26-g1", "SMNGRP05", "2026-08-09T10:00:00+00:00")
        book.record("uoh26-g1", "SMNGRP05", "2026-08-09T11:00:00+00:00")
        assert book.played() == 1

    def test_the_distinct_opponents_are_kept_in_order_first_met(self, tmp_path: Path) -> None:
        """Rule 31 counts games against *different* teams, so the list matters too."""
        book = ledger(tmp_path)
        for number, team in enumerate(("SMNGRP05", "SMNGRP07", "SMNGRP05"), start=1):
            book.record(f"uoh26-g{number}", team, "2026-08-09T10:00:00+00:00")
        assert book.opponents() == ("SMNGRP05", "SMNGRP07")


class TestTheLedgerIsReadableEvidence:
    def test_it_sits_beside_the_artefacts_it_can_be_checked_against(self, tmp_path: Path) -> None:
        ledger(tmp_path).record("uoh26-g1", "SMNGRP05", "2026-08-09T10:00:00+00:00")
        assert (tmp_path / LEDGER_FILE).exists()

    def test_the_file_is_sorted_json_a_reader_can_diff(self, tmp_path: Path) -> None:
        ledger(tmp_path).record("uoh26-g1", "SMNGRP05", "2026-08-09T10:00:00+00:00")
        body = json.loads((tmp_path / LEDGER_FILE).read_text())
        assert body == [
            {
                "ended_at": "2026-08-09T10:00:00+00:00",
                "game_id": "uoh26-g1",
                "opponent": "SMNGRP05",
            }
        ]


class TestAnUnreadableLedgerUnderstatesRatherThanCrashes:
    def test_a_corrupt_file_counts_as_no_games(self, tmp_path: Path) -> None:
        """The alternative is an agent that cannot open a match at all.

        Declaring zero is both the honest reading of an unreadable record and
        the count that understates rather than inflates — and understating is
        the direction that cannot become a rule 38 breach.
        """
        (tmp_path / LEDGER_FILE).write_text("{not json")
        assert ledger(tmp_path).played() == 0

    def test_a_json_document_of_the_wrong_shape_counts_as_no_games(self, tmp_path: Path) -> None:
        (tmp_path / LEDGER_FILE).write_text('{"games": 12}')
        assert ledger(tmp_path).played() == 0


class TestTheCountIsSigned:
    def test_it_is_inside_the_content_the_signature_covers(self) -> None:
        """A number nobody signed is one that can be revised after a bad match."""
        assert "games_already_played" in build_declaration("thief", "g1", "u-0001").content()

    def test_changing_the_count_changes_the_signed_bytes(self) -> None:
        from dataclasses import replace

        one = build_declaration("thief", "g1", "u-0001")
        two = replace(one, games_already_played=one.games_already_played + 1)
        assert canonical_bytes(one.content()) != canonical_bytes(two.content())

    def test_a_negative_count_is_refused_at_construction(self) -> None:
        from dataclasses import replace

        with pytest.raises(DeclarationError, match="games_already_played"):
            replace(build_declaration("thief", "g1", "u-0001"), games_already_played=-1)


class TestARehearsalIsNotAGame:
    def test_a_rehearsal_leaves_the_count_alone(self, tmp_path: Path) -> None:
        """Rule 52 allows warm-ups; counting one would be a false declaration."""
        declaration = build_declaration("thief", "uoh26-g1", "u-0001")
        _record_game(tmp_path, declaration, declaration.them, rehearsal=True)
        assert ledger(tmp_path).played() == 0

    def test_a_real_match_is_recorded_against_the_opponent_it_was_played_against(
        self, tmp_path: Path
    ) -> None:
        declaration = build_declaration("thief", "uoh26-g1", "u-0001")
        _record_game(tmp_path, declaration, declaration.them, rehearsal=False)
        assert ledger(tmp_path).opponents() == (declaration.them.name,)
