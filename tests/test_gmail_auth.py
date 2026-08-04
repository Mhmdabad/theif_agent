"""Least privilege, asked for narrowly and refused when granted widely."""

from pathlib import Path

import pytest

import thief_agent
from thief_agent.infra.gmail_auth import SCOPES, SEND_SCOPE, ScopeError, check_granted

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"

PACKAGE = Path(thief_agent.__file__).parent
SCOPE_MARKER = "googleapis.com/auth/"


class TestWhatWeAskFor:
    def test_the_send_scope_is_the_only_one(self) -> None:
        assert SCOPES == (SEND_SCOPE,)

    def test_it_is_the_exact_string_the_rulebook_names(self) -> None:
        """A near-miss is not a scope; Google rejects the whole request."""
        assert SEND_SCOPE == "https://www.googleapis.com/auth/gmail.send"

    def test_the_scope_list_cannot_be_appended_to(self) -> None:
        assert isinstance(SCOPES, tuple)

    def test_only_the_send_scope_appears_anywhere_in_the_source(self) -> None:
        """The enforcement, not a restatement of the constant.

        Scope creep does not arrive as a decision. It arrives as one more
        string added beside working code, in whichever module happened to need
        something. Reading the tree is the only check that notices that.
        """
        found: list[str] = []
        for source in sorted(PACKAGE.rglob("*.py")):
            for line in source.read_text().splitlines():
                if SCOPE_MARKER in line:
                    found.append(f"{source.relative_to(PACKAGE)}: {line.strip()}")
        assert len(found) == 1, f"a scope string appears outside gmail_auth.py: {found}"
        assert found[0].startswith("infra/gmail_auth.py")
        assert SEND_SCOPE in found[0]

    @pytest.mark.parametrize("wider", [READ_SCOPE, MODIFY_SCOPE, "https://mail.google.com/"])
    def test_no_wider_scope_url_is_referenced_anywhere(self, wider: str) -> None:
        """FR-7.25: never grant read or modify access.

        Matched on the full scope URL rather than on the words. Prose in this
        package names the wider scopes in order to explain why they are refused,
        and a check that failed on the explanation would only teach people to
        stop writing them down.
        """
        for source in sorted(PACKAGE.rglob("*.py")):
            assert wider not in source.read_text(), source


class TestWhatWeWereGranted:
    def test_exactly_the_send_scope_is_accepted(self) -> None:
        assert check_granted([SEND_SCOPE]) == (SEND_SCOPE,)

    def test_a_space_separated_string_is_accepted(self) -> None:
        """Token files store scopes both ways; both are the same grant."""
        assert check_granted(SEND_SCOPE) == (SEND_SCOPE,)

    def test_a_wider_grant_is_refused(self) -> None:
        """Asking narrowly does not guarantee receiving narrowly."""
        with pytest.raises(ScopeError, match="gmail.readonly"):
            check_granted([SEND_SCOPE, READ_SCOPE])

    def test_the_refusal_says_how_to_fix_it(self) -> None:
        """Revoke and re-authorize. There is no in-process remedy."""
        with pytest.raises(ScopeError, match="revoke it at"):
            check_granted([SEND_SCOPE, MODIFY_SCOPE])

    def test_extra_scope_is_refused_rather_than_trimmed(self) -> None:
        """Trimming would describe the token as narrow while it stayed wide.

        The file on disk is what an attacker gets, and it does not read our
        variables.
        """
        with pytest.raises(ScopeError):
            check_granted([SEND_SCOPE, READ_SCOPE])

    def test_a_grant_of_the_wrong_scope_entirely_is_refused(self) -> None:
        """Reported as excess rather than as absence: excess is the danger."""
        with pytest.raises(ScopeError, match="will not hold"):
            check_granted([READ_SCOPE])

    def test_an_empty_grant_is_refused(self) -> None:
        """The only way to hold nothing extra and still be unable to send."""
        with pytest.raises(ScopeError, match="cannot send mail"):
            check_granted([])


class TestItRefusesBadInputRatherThanCrashingOnIt:
    """The values come from parsed JSON, so any shape can arrive."""

    @pytest.mark.parametrize("value", [None, 7, {"scope": SEND_SCOPE}, [SEND_SCOPE, 7]])
    def test_a_value_that_is_not_a_scope_list_raises_scope_error(self, value: object) -> None:
        with pytest.raises(ScopeError, match="expected a list of scope strings"):
            check_granted(value)

    def test_a_missing_scope_field_is_a_scope_error_not_a_type_error(self) -> None:
        """A module whose job is refusing bad input should not crash on it."""
        with pytest.raises(ScopeError):
            check_granted(None)
