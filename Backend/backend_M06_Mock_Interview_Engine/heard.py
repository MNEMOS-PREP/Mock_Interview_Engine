"""What the student actually heard of an interviewer line — M11's FR-11.9.

When the student starts speaking over the interviewer, the voice stops and
the room says where (`@ai/core`'s `bargeIn`: the part being heard and how far
through it). The line of record stays whole — it is what the interviewer
said — and the turn carries the cut, so two readers can tell the difference:

- the student, whose transcript shows the words they never heard, dimmed;
- the interviewer model, which reads the line as heard, marked as cut off, so
  a follow-up does not assume a question the student never finished hearing.
"""

from __future__ import annotations

from typing import Any

#: How the interviewer model is told the student came in.
CUT_MARK = " [cut off: the student started speaking here]"


def heard_text(turn: Any) -> str | None:
    """The line as far as it was heard, or None when it was not cut."""
    if getattr(turn, "heard", None) is None:
        return None
    parts = [p.text for p in getattr(turn, "parts", None) or []] or [turn.text]
    index = min(max(0, int(getattr(turn, "heard_part", None) or 0)), len(parts) - 1)
    text = parts[index]
    upto = round(len(text) * float(turn.heard))
    # Snap back to a word boundary: a word half-said is not heard.
    if 0 < upto < len(text) and not text[upto].isspace():
        space = text.rfind(" ", 0, upto)
        upto = space if space > 0 else 0
    heard = [*parts[:index], text[:upto].rstrip()]
    return " ".join(p for p in heard if p).strip()


def for_interviewer(turn: Any) -> str:
    """The line as the interviewer model should read it."""
    heard = heard_text(turn)
    return turn.text if heard is None else heard + CUT_MARK


__all__ = ["CUT_MARK", "for_interviewer", "heard_text"]
