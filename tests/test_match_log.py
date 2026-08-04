"""The file the Replay App re-verifies and the two teams audit against."""

import json
from pathlib import Path

import pytest

from thief_agent.infra.match_log import SLOTS, MatchLog, MatchLogError
from thief_agent.shared.naming import NamingError

DIGEST = "a" * 64
NONCE = "0" * 32
OPENED = {"move": "N", "intent": "lie", "hint": "heading uptown", "barrier_placed": None}


def log() -> MatchLog:
    return MatchLog(game_id="uoh26-s82kma9e", sub_game=3, role="thief")


def played(steps: int = 2) -> MatchLog:
    """A finished sub-game: every step committed, revealed and opened."""
    written = log()
    for step in range(1, steps + 1):
        written.commit(step, DIGEST)
        written.reveal(step, OPENED)
        written.disclose(step, NONCE)
    return written


class TestTheOrderIsTheEvidence:
    def test_a_full_step_records_all_three_slots(self) -> None:
        assert tuple(played(1).entries[1].to_dict()) == ("step", *SLOTS)

    def test_a_reveal_before_a_commitment_is_refused(self) -> None:
        """The exact shape of a move decided after seeing the opponent's.

        The ordering in this file is the only place it can be shown not to
        have happened.
        """
        with pytest.raises(MatchLogError, match="no commitment recorded"):
            log().reveal(1, OPENED)

    def test_a_nonce_before_a_reveal_is_refused(self) -> None:
        """It would open a commitment whose contents nobody has seen."""
        written = log()
        written.commit(1, DIGEST)
        with pytest.raises(MatchLogError, match="no reveal to open"):
            written.disclose(1, NONCE)

    def test_the_three_slots_fill_in_order_without_complaint(self) -> None:
        written = log()
        written.commit(1, DIGEST)
        written.reveal(1, OPENED)
        written.disclose(1, NONCE)
        assert written.entries[1].nonce == NONCE


class TestAppendOnly:
    @pytest.mark.parametrize("slot", SLOTS)
    def test_no_slot_can_be_written_twice(self, slot: str) -> None:
        """A log that permitted an overwrite would be as convincing as no log.

        An auditor cannot distinguish "written honestly as it happened" from
        "written honestly at the end", and the second is what a cheat produces.
        """
        written = played(1)
        actions = {
            "commit": lambda: written.commit(1, "b" * 64),
            "reveal": lambda: written.reveal(1, {**OPENED, "move": "S"}),
            "nonce": lambda: written.disclose(1, "1" * 32),
        }
        with pytest.raises(MatchLogError, match="append-only"):
            actions[slot]()

    def test_an_earlier_step_is_untouched_by_a_later_one(self) -> None:
        written = played(3)
        assert written.entries[1].reveal == OPENED
        assert sorted(written.entries) == [1, 2, 3]

    def test_a_refused_write_leaves_the_original_in_place(self) -> None:
        written = played(1)
        with pytest.raises(MatchLogError):
            written.reveal(1, {**OPENED, "move": "S"})
        assert written.entries[1].reveal == OPENED


class TestNoncesArriveLast:
    def test_a_running_match_has_unopened_steps(self) -> None:
        written = log()
        written.commit(1, DIGEST)
        written.reveal(1, OPENED)
        assert written.unopened() == [1]

    def test_an_empty_list_is_the_only_acceptable_end_state(self) -> None:
        assert played(3).unopened() == []

    def test_a_partially_opened_match_names_the_gaps(self) -> None:
        written = played(2)
        written.commit(3, DIGEST)
        written.reveal(3, OPENED)
        assert written.unopened() == [3]


class TestTheFile:
    def test_it_is_named_for_the_game_and_sub_game(self, tmp_path: Path) -> None:
        assert played().write(tmp_path).name == "log_uoh26-s82kma9e_g03.json"

    def test_it_writes_and_creates_the_directory(self, tmp_path: Path) -> None:
        path = played(2).write(tmp_path / "artefacts")
        written = json.loads(path.read_text())
        assert [row["step"] for row in written["steps"]] == [1, 2]
        assert written["role"] == "thief"

    def test_steps_are_sorted_so_identical_histories_agree(self, tmp_path: Path) -> None:
        """A diff that is noise-free is a diff two tired people can read."""
        forwards, backwards = log(), log()
        for step in (1, 2, 3):
            forwards.commit(step, DIGEST)
        for step in (3, 2, 1):
            backwards.commit(step, DIGEST)
        assert forwards.to_dict() == backwards.to_dict()

    def test_a_game_id_that_would_escape_the_directory_is_refused(self) -> None:
        with pytest.raises(NamingError):
            MatchLog(game_id="../../etc/passwd", sub_game=1, role="thief")

    def test_a_sub_game_outside_the_series_is_refused(self) -> None:
        with pytest.raises(NamingError):
            MatchLog(game_id="g1", sub_game=0, role="thief")

    def test_a_role_the_wire_does_not_name_is_refused(self) -> None:
        with pytest.raises(MatchLogError, match="role must be one of"):
            MatchLog(game_id="g1", sub_game=1, role="cop")
