"""The banner is the visible half. The input lock is the half that matters."""

from thief_agent.infra.ceremony import Acknowledgement, Commitment, Reveal, StepCeremony
from thief_agent.ui.banner import Tone, banner

WHEN = "2026-08-04T09:00:00+00:00"
OURS, THEIRS = "a" * 64, "b" * 64
NONCE = "0" * 32


def ceremony(role: str = "thief") -> StepCeremony:
    return StepCeremony(step=4, role=role)


def committed() -> StepCeremony:
    step = ceremony()
    step.commit(Commitment(step=4, sender="thief", commit=OURS, timestamp=WHEN), NONCE)
    return step


def locked() -> StepCeremony:
    step = committed()
    step.receive(Commitment(step=4, sender="police", commit=THEIRS, timestamp=WHEN))
    step.acknowledge(WHEN)
    step.receive_ack(Acknowledgement(step=4, sender="police", acknowledges=OURS, timestamp=WHEN))
    return step


def played() -> StepCeremony:
    step = locked()
    step.reveal(
        Reveal(step=4, sender="thief", move="N", intent="truth", hint="north", timestamp=WHEN)
    )
    return step


class TestInputIsLiveOnlyBeforeWeCommit:
    def test_an_untouched_turn_accepts_input(self) -> None:
        shown = banner(ceremony())
        assert shown.accepting_input
        assert shown.tone is Tone.GO
        assert "YOUR TURN" in shown.text

    def test_committing_locks_the_window_immediately(self) -> None:
        """The move is sealed the moment the commitment exists.

        A window that still accepted a click would offer a way to send a
        reveal that does not open to the commitment already made — which the
        audit calls forgery, correctly.
        """
        shown = banner(committed())
        assert shown.locked
        assert not shown.accepting_input
        assert shown.tone is Tone.LOCKED

    def test_it_stays_locked_once_both_sides_are_locked(self) -> None:
        assert banner(locked()).locked

    def test_it_stays_locked_after_the_reveal(self) -> None:
        assert banner(played()).locked

    def test_input_is_never_re_enabled_within_a_step(self) -> None:
        """Once shut, shut. There is no later state that reopens it."""
        stages = (ceremony(), committed(), locked(), played())
        assert [banner(step).accepting_input for step in stages] == [True, False, False, False]


class TestTheLockIsDerivedNotTracked:
    def test_it_reads_the_ceremony_rather_than_a_flag(self) -> None:
        """A separate flag would be a second source of truth.

        The two would disagree on exactly the turn where a retry or a
        re-handshake made things interesting.
        """
        step = ceremony()
        assert banner(step).accepting_input
        step.commit(Commitment(step=4, sender="thief", commit=OURS, timestamp=WHEN), NONCE)
        assert not banner(step).accepting_input  # same object, no flag was set

    def test_a_fresh_step_is_open_again(self) -> None:
        """The lock is per step, because a commitment is."""
        assert banner(StepCeremony(step=5, role="thief")).accepting_input


class TestWhatTheBannerSays:
    def test_it_names_the_step(self) -> None:
        assert "step 4" in banner(ceremony()).text

    def test_waiting_says_what_it_is_waiting_for(self) -> None:
        """A ceremony stalled at three of four parts is a question, not a mystery."""
        assert "their commitment" in banner(committed()).text

    def test_a_locked_pair_says_it_is_revealing(self) -> None:
        assert "revealing" in banner(locked()).text

    def test_a_played_step_says_so(self) -> None:
        assert "played" in banner(played()).text

    def test_the_tones_are_the_two_the_rulebook_names(self) -> None:
        assert {tone.value for tone in Tone} == {"green", "grey"}

    def test_the_banner_is_frozen(self) -> None:
        shown = banner(ceremony())
        try:
            shown.text = "anything"  # type: ignore[misc]
        except AttributeError:
            return
        raise AssertionError("a banner should not be editable after it is built")
