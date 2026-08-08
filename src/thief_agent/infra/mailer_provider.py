"""The Gmail client library, and every shape its answers arrive in.

:mod:`.mailer` holds the order in which a report is sent; this module holds the
one call that order ends in. The separation is the point: :class:`Sender` is a
Protocol, :func:`gmail_sender` is the only code in this project that imports a
Google library, and every rule about ordering is therefore testable against a
counting fake — the only responsible way to test a component whose failure mode
is *sending real mail to a lecturer*.

:func:`retry_after_of` belongs on this side of the seam for the same reason.
Reading ``Retry-After`` means knowing what an error object from a particular
client library looks like, and that knowledge is exactly what a dependency
change invalidates. Keeping it beside the call it describes means the shapes a
429 can arrive in are read in one place rather than guessed at in several.
"""

from typing import Any, Protocol


class Sender(Protocol):
    """The one Gmail call this project makes.

    ``users().messages().send(userId="me", body=...)`` reduced to its shape, so
    the rules above can be exercised without credentials, a network, or the
    possibility of mailing anybody.
    """

    def send(self, raw: dict[str, str]) -> dict[str, Any]: ...


def gmail_sender(credential: dict[str, Any]) -> Sender:  # pragma: no cover - needs Google
    """The real thing. The only function here that imports a Google library.

    Uncovered deliberately: the alternative is a test that authenticates against
    a live account, and the failure mode of getting that wrong is mail arriving
    in a lecturer's inbox. Everything it is wrapped in is covered instead.
    """
    from google.oauth2.credentials import Credentials  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    # The Google library is untyped; ignored on this line rather than relaxing
    # the rule for a module that also holds the send ordering.
    account = Credentials.from_authorized_user_info(credential)  # type: ignore[no-untyped-call]
    service = build("gmail", "v1", credentials=account)

    class _Gmail:
        def send(self, raw: dict[str, str]) -> dict[str, Any]:
            answer = service.users().messages().send(userId="me", body=raw).execute()
            return dict(answer)

    return _Gmail()


def retry_after_of(error: object) -> float | None:
    """The provider's own ``Retry-After``, when it sent one.

    Read from several shapes for the reason :func:`~.gatekeeper.status_code_of`
    is: a rule that only worked with one client library would stop working
    silently after a dependency change, and the first symptom would be a
    suspended account.
    """
    headers = getattr(getattr(error, "resp", None), "headers", None)
    if isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if isinstance(raw, (int, float, str)):
            try:
                return float(raw)
            except ValueError:
                return None
    direct = getattr(error, "retry_after", None)
    return float(direct) if isinstance(direct, (int, float)) else None
