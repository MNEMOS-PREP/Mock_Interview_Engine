"""What of an event a student's browser may see (spec §2.2, FR-6.15).

The event log is the trace, and the trace holds things a live session must not
show: the strategist's verdict band (a provisional score — "any live score"
is deliberately absent, §2.2) and the item behind the open question, whose
key points are what a good answer contains. Both would reach the student
through the SSE stream or the trace route if nothing stood in the way, and
neither would ever look like a bug — which is why this is a whitelist per
event kind rather than a list of things to strip.

After the session ends the report shows what a strong answer covered; that is
teaching. During it, it is the answer key.
"""

from __future__ import annotations

from typing import Any

from .models import SessionEvent

_KEEP: dict[str, tuple[str, ...]] = {
    "session.created": ("kind", "mode", "requested_minutes"),
    "plan.set": ("plan",),
    "session.started": (),
    "session.paused": (),
    "session.resumed": (),
    "session.reconnected": (),
    "session.ended": ("reason", "closing_text", "closing_turn_id", "closing_turn_index"),
    "session.aborted": ("reason",),
    "question.asked": (
        "turn_id",
        "turn_index",
        "segment_index",
        "text",
        "probe_move",
        "probe_depth",
        "question_source",
        "new_question",
    ),
    "answer.received": ("turn_id", "turn_index", "text", "question_turn_id"),
    "hint.given": ("level",),
    "segment.transition": ("from", "to", "from_title", "to_title", "line"),
    "upstream.degraded": ("module", "sentence"),
}


def public_event(event: SessionEvent) -> dict[str, Any] | None:
    """The browser-safe form, or None for an event the browser never sees."""
    if event.kind == "probe.decided":
        # The move is heard anyway ("let's leave that there"); nothing else.
        move = (event.payload.get("move") or {}).get("kind")
        data: dict[str, Any] = {"move": move}
    elif event.kind == "consent.resolved":
        data = {"recorded": bool(event.payload.get("consent_id"))}
    elif event.kind in _KEEP:
        data = {k: event.payload[k] for k in _KEEP[event.kind] if k in event.payload}
    else:
        return None
    return {"seq": event.seq, "kind": event.kind, "at": event.at.isoformat(), "data": data}


__all__ = ["public_event"]
