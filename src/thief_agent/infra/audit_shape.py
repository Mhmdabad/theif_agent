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
    return {"sender": sender, "records": records or [], "result_claim": result_claim}
