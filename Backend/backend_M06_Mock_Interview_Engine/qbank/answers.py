"""The answers nobody wrote: what the question bank asks a model for.

A bank item has a reference answer — M05's, written to be said out loud
("For a Book class I would declare…") — and the bank prints it as it is: a
model never rewrites an answer a person reviewed. What has no answer is
everything else the student met:

* the FOLLOW-UPS an interviewer asked, phrased live around the student's own
  words ("Your description suggests overwriting; can you explain…"), and
  asked a dozen ways across interviews ("why is it O(1)?", "why does
  constant-time lookup hold?") — words alone cannot tell those apart;
* a question whose item carries no answer: the backup set, an opening line,
  or a line of the student's own resume, whose project nobody but they know.

So one call per question: merge the follow-ups that ask the same thing, make
each read on its own (the topic named, no "that", no names, nothing the
student said), and answer each the way a strong candidate would say it. And
the checks a model cannot be trusted with are code's: every follow-up
written must stand for at least one that was asked — a model asked to
"answer the follow-ups" will happily add its own — nothing is markdown, and
nothing is longer than a breath or two.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .collect import Asked

#: Part of every stored answer's key (`brief_hash`): moving it rewrites them.
PROMPT_VERSION = "qbank-1"
#: The follow-ups a question keeps in the bank, after merging.
MAX_FOLLOW_UPS = 5
#: How many of the follow-ups asked the writer is shown. A question asked in
#: twenty interviews has had more, and the first ones are the core.
MAX_ASKED = 14

SYSTEM = """You write revision notes for a student in India preparing for campus placement interviews. You are given ONE interview question the student was asked, with its answer key when there is one, and the follow-up questions interviewers actually asked about it.

Return JSON with:
1. "answer": ONLY when the input says NO REFERENCE ANSWER — the answer a strong candidate would say out loud, in the first person, 3 to 6 sentences, correct and specific, covering the key points. When a reference answer is given, return an empty string.
   For a question about a line of the student's own resume or project, you do not know their project: say how to answer it, what to say in which order, with [square brackets] where their own facts go (e.g. "[the dataset size]"). Never invent their numbers.
2. "follow_ups": the follow-ups worth revising, AT MOST 5, in the order they were asked.
   - Merge follow-ups that ask the same thing in different words into one, and list every one it stands for in "asked" (their numbers).
   - Leave out a follow-up that only asks to repeat or "elaborate on" what the main answer already says.
   - "question": the follow-up so it reads on its own: name the topic instead of "that", "those conditions" or "your description"; no interviewer names; never mention what the student said.
   - "answer": what to say, first person, 2 to 4 sentences, specific and correct.

Plain spoken English. No markdown, no bullet characters, no headings. Do not mention the student, the interviewer or yourself."""

_FOLLOW = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asked", "question", "answer"],
    "properties": {
        "asked": {"type": "array", "items": {"type": "integer"}},
        "question": {"type": "string"},
        "answer": {"type": "string"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "follow_ups"],
    "properties": {
        "answer": {"type": "string"},
        "follow_ups": {"type": "array", "items": _FOLLOW},
    },
}

MAX_ANSWER, MIN_ANSWER = 1400, 60
MAX_FOLLOW_ANSWER, MIN_FOLLOW_ANSWER = 900, 30
MAX_QUESTION = 300
#: A frame for a question only the student can answer leaves their facts
#: blank: at least this many `[placeholders]`.
MIN_PLACEHOLDERS = 3
_PLACEHOLDER = re.compile(r"\[[^\]]{2,80}\]")
#: A heading or a bullet: a list where a spoken answer belongs. Emphasis and
#: code marks are stripped instead (`_clean`) — `HashMap` is still an answer.
_MARKDOWN = re.compile(r"^\s*(#{1,6}\s|[-*•]\s)")
_MARKS = re.compile(r"\*\*|__|`")
_SELF = re.compile(r"\b(as an ai|language model|i cannot|i can't help)\b", re.I)
_KIND = {
    "m05_bank": "a question from the reviewed question bank",
    "m05_fallback": "a question from the question bank",
    "m05_draft": "a practice question from the question bank",
    "local_fallback": "a question from the backup set",
    "template": "an opening question",
    "m01_probe": "a question about a line of the student's own resume",
}


@dataclass
class Written:
    """What came back and passed: the answer (only when the item had none),
    and the follow-ups, each standing for the asked ones it lists."""

    answer: str = ""
    follow_ups: list[dict[str, Any]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {"answer": self.answer, "follow_ups": self.follow_ups}


def needs_writing(question: Asked) -> bool:
    """A question with something unwritten: follow-ups, or no answer at all."""
    return bool(question.follow_ups) or not question.reference_answer


def brief(question: Asked) -> str:
    """Everything the writer is told about one question."""
    lines = [f"QUESTION: {question.stem}"]
    kind = _KIND.get(question.source, "an interview question")
    if question.about_you:
        kind += (
            " — only the student knows the facts. Write a FRAME for answering it: what to"
            " say, in which order, with EVERY fact about the student — their project,"
            " technology, role, team, numbers, results — as a [placeholder] in square"
            " brackets. State none of those as fact."
        )
    if question.resume and question.label:
        kind += f' — the line: "{question.label}"'
    lines.append(f"KIND: {kind}")
    if question.reference_answer:
        lines.append(f"REFERENCE ANSWER: {question.reference_answer}")
    else:
        lines.append("NO REFERENCE ANSWER — write the answer.")
    points = question.key_points or question.expects
    if points:
        lines.append("KEY POINTS a strong answer covers:")
        lines.extend(f"  - {point}" for point in points)
    asked = question.follow_ups[:MAX_ASKED]
    if asked:
        lines.append("FOLLOW-UPS ASKED:")
        lines.extend(f"  {n}. {text}" for n, text in enumerate(asked, start=1))
    else:
        lines.append("FOLLOW-UPS ASKED: none — return an empty list.")
    return "\n".join(lines)


def brief_hash(question: Asked) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}\n{brief(question)}".encode()).hexdigest()[:32]


def _clean(text: Any, limit: int) -> str:
    raw = str(text or "")
    if _MARKDOWN.search(raw):
        return raw.strip()  # left as it came, for the check to refuse
    text = " ".join(_MARKS.sub("", raw).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    end = max(cut.rfind(". "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 2 else cut + "…"


def check(raw: Any, question: Asked) -> tuple[Written | None, list[str]]:
    """What can be printed, and what was wrong. A follow-up that fails is
    dropped; a missing answer that was needed refuses the whole result."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        return None, ["not an object"]
    written = Written()
    if not question.reference_answer:
        answer = _clean(raw.get("answer"), MAX_ANSWER)
        if len(answer) < MIN_ANSWER:
            return None, ["no answer for a question that has none"]
        if _MARKDOWN.search(answer) or _SELF.search(answer):
            return None, ["the answer is markdown or talks about itself"]
        if question.about_you and len(_PLACEHOLDER.findall(answer)) < MIN_PLACEHOLDERS:
            # Measured: a frame for "walk me through your resume" came back
            # with AWS, two interns and a product launch stated as fact.
            return None, ["a frame for the student's own story states their facts"]
        written.answer = answer
    asked = len(question.follow_ups[:MAX_ASKED])
    used: set[int] = set()
    for item in raw.get("follow_ups") or []:
        if len(written.follow_ups) >= MAX_FOLLOW_UPS:
            problems.append("more follow-ups than the bank keeps")
            break
        if not isinstance(item, dict):
            continue
        numbers = sorted(
            {int(n) for n in item.get("asked") or [] if isinstance(n, int) and 1 <= n <= asked}
            - used
        )
        text = _clean(item.get("question"), MAX_QUESTION)
        answer = _clean(item.get("answer"), MAX_FOLLOW_ANSWER)
        if not numbers:
            problems.append(f"a follow-up that stands for none asked: {text[:60]!r}")
            continue
        if len(text) < 10 or not text.endswith("?"):
            problems.append(f"not a question: {text[:60]!r}")
            continue
        if len(answer) < MIN_FOLLOW_ANSWER:
            problems.append(f"no answer to {text[:60]!r}")
            continue
        if any(_MARKDOWN.search(t) or _SELF.search(t) for t in (text, answer)):
            problems.append(f"markdown or self-talk in {text[:60]!r}")
            continue
        used.update(numbers)
        written.follow_ups.append({"asked": numbers, "question": text, "answer": answer})
    return written, problems


def write_one(
    llm: Any, question: Asked, jobs: tuple[str, ...]
) -> tuple[Written | None, str, list[str], list]:
    """The writing tier, else the generation tier. (written, model, problems, calls)."""
    calls: list = []
    problems: list[str] = []
    user = brief(question)
    for job in jobs:
        result = llm.structured(job=job, system=SYSTEM, user=user, schema=SCHEMA)
        result.prompt_version = PROMPT_VERSION
        calls.append(result)
        if not result.ok:
            problems.append(f"{result.model or job}: {result.reason}")
            continue
        written, found = check(result.data, question)
        problems.extend(f"{result.model}: {p}" for p in found)
        if written is not None:
            return written, result.model, problems, calls
    return None, "", problems, calls


__all__ = [
    "MAX_FOLLOW_UPS",
    "PROMPT_VERSION",
    "SCHEMA",
    "SYSTEM",
    "Written",
    "brief",
    "brief_hash",
    "check",
    "needs_writing",
    "write_one",
]
