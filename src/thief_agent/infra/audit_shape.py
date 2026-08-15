"""Reading an audit whichever envelope it arrives in.

The cohort's ``submit_audit`` takes ``sender``, ``records`` and ``result_claim``
flat; ours takes them wrapped in ``payload``. The fields are identical, so a
peer sending them flat is not sending anything we cannot read, and refusing
would be refusing an envelope rather than a message.

**One direction only.** We still *send* wrapped, because our payload carries
``game_uid`` and ``sub_game`` beside the three, and a tool argument is not a
message field: the cohort tolerates unknown keys inside a message, but pydantic
refuses an undeclared keyword argument outright. Sending flat would mean
dropping the binding that ties an audit to a series -- which is what stops a
reveal being re-wrapped to replay an earlier sub-game. Where that binding
should ride under reference-v3 is an open protocol question, not a rename.
"""

from typing import Any

__all__ = ["either_shape"]


def either_shape(
    payload: object,
    sender: str,
    records: list[dict[str, Any]] | None,
    result_claim: str,
) -> object:
    """The wrapped payload, built from the flat fields when that is what came.

    ``sender`` is the discriminator rather than ``records``: an audit always
    names who sent it, while a sub-game that ended before a single step has no
    records to show and would otherwise read as an empty wrapped call.
    """
    if payload is not None or not sender:
        return payload
    body: dict[str, Any] = {
        "sender": sender,
        "records": records or [],
        "result_claim": result_claim,
    }
    return {**body, **_binding(records or [])}


def _binding(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The series and sub-game this audit belongs to, read from its own records.

    The flat form has nowhere to put them -- a tool argument is not a message
    field -- but every record's payload already carries both, *inside the
    commitment preimage*. So the envelope is rebuilt from the sealed copy
    rather than from an unsigned duplicate the sender could have set freely,
    which is the stronger reading of the same fact.

    Taken from the first record that has them. They are identical across a
    sub-game by construction, and the per-record check downstream compares
    every one against this envelope, so a chain that disagreed with itself is
    caught there rather than papered over here.
    """
    for record in records:
        seal = record.get("payload")
        if isinstance(seal, dict) and seal.get("game_uid"):
            return {"game_uid": str(seal["game_uid"]), "sub_game": int(seal.get("sub_game", 0))}
    return {}
