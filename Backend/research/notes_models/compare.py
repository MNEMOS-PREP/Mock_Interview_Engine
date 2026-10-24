"""Which model should write the notes? — M06, 2026-10-24.

The notes writer (`notes_writer.py`) explains each answer after the session:
verbose, structured, format-sensitive text a student reads. This sends the
same briefs to each candidate — the live sessions' real answers (yesterday's
runs: a focus interview, a revisit, a resume interview) plus four written to
cover what those lack (a clean correct answer, a surface-level one, a plainly
wrong one, a blank) — and scores each output with the product's own checks
(`notes_writer.check`): valid JSON for the schema, every quote the student's
own words, no praise for a wrong answer, a correction for every wrong one.
Latency and tokens are recorded; the text is kept for reading.

Candidates: the generation tier today (Groq `openai/gpt-oss-120b`) and NVIDIA
NIM models listed by the account. One key per provider; Groq is paced under
its 8K tokens a minute. Run from M06's Backend with its venv:
    .venv\\Scripts\\python.exe research\\notes_models\\compare.py
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from ai_core.db import engine  # noqa: E402
from sqlmodel import Session  # noqa: E402

from backend_M06_Mock_Interview_Engine import notes_writer, report, store  # noqa: E402
from backend_M06_Mock_Interview_Engine.keys import keys_from_env, load_keys  # noqa: E402
from backend_M06_Mock_Interview_Engine.report import (  # noqa: E402
    Exchange,
    Finding,
    KeyPointCheck,
)

AGENT = "AI-Interviewer/1.0 (+https://github.com/MNEMOS-PREP)"
CANDIDATES = [
    ("groq", "openai/gpt-oss-120b"),
    # Responsive on the account (2026-10-24 probe); most other listed NIM
    # models answered 404 "Function not found" or hung past 45 s — see
    # RESULTS.md.
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("nvidia", "minimaxai/minimax-m3.1-flash"),
    ("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b"),
]
URL = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}
LIVE = {
    "C": ("5542aa39-d305-4eca-9bc8-47c7ff80ba8c", [1, 2, 3, 4]),
    "E": ("8fbe6ced-c0ec-4b46-bbfb-ef86ab7559fb", [2, 3, 4, 5]),
}
GROQ_PACE_S = 12.0
TIMEOUT_S = 120


def live_cases() -> list[tuple[str, report.QuestionReport]]:
    out = []
    with Session(engine) as db:
        for name, (sid, picks) in LIVE.items():
            session_id = uuid.UUID(sid)
            state = store.load_state(db, session_id)
            built = report.build(state, store.events_for(db, session_id), datetime.now(UTC))
            for n in picks:
                q = built.questions[n - 1]
                if q.status and q.status != "not_reached":
                    out.append((f"live {name}.Q{n} ({q.status})", q))
    return out


def written_cases(lookup: report.QuestionReport) -> list[tuple[str, report.QuestionReport]]:
    """Four answers to the bank's lookup question, one per shape the live
    runs did not produce cleanly."""

    def case(answer: str, status: str, label: str, detail: str, covered, **extra):
        q = lookup.model_copy(deep=True)
        q.exchanges = [
            Exchange(role="interviewer", text=q.question),
            Exchange(role="candidate", text=answer),
        ]
        q.status, q.status_label, q.status_detail, q.status_qualifier = status, label, detail, None
        q.key_points = [
            KeyPointCheck(statement=p.statement, covered=c)
            for p, c in zip(lookup.key_points, covered, strict=False)
        ]
        q.went_well, q.went_wrong, q.misconception, q.corrected = [], [], None, None
        for name, value in extra.items():
            setattr(q, name, value)
        return q

    n = len(lookup.key_points)
    return [
        (
            "written correct",
            case(
                "The key goes through a hash function that maps it to a bucket index, so you jump "
                "straight to that slot instead of scanning, which is constant work. It only stays "
                "O(1) on average if the hash spreads keys evenly and the table is resized to keep "
                "the load factor bounded; if all keys land in one bucket, lookup becomes linear.",
                "correct",
                "Correct",
                "What you said held up to the follow-ups.",
                [True] * n,
                went_well=["hash to a bucket index", "even spread and bounded load factor"],
            ),
        ),
        (
            "written surface",
            case(
                "It uses hashing with buckets and a good hash function, and collisions are handled "
                "by chaining, so lookup is O(1) on average.",
                "vague",
                "Too vague",
                "You named the right terms without explaining how it works.",
                [False] * n,
            ),
        ),
        (
            "written wrong",
            case(
                "Lookup is O(1) because the keys are kept sorted, so you binary search straight "
                "to the one you want.",
                "incorrect",
                "Incorrect",
                "A misunderstanding that stood: thinks a hash map keeps keys sorted.",
                [False] * n,
                misconception="thinks a hash map keeps keys sorted",
                went_wrong=[
                    Finding(
                        said="the keys are kept sorted, so you can binary search",
                        why="A hash map does not sort keys; a hash function picks the bucket.",
                    )
                ],
            ),
        ),
        (
            "written blank",
            case(
                "I'm not sure, I don't know this one.",
                "unanswered",
                "Not answered",
                "You said you did not know this one.",
                [False] * n,
            ),
        ),
    ]


def strip(content: str) -> str:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.S)
    if fenced:
        return fenced.group(1)
    start, end = content.find("{"), content.rfind("}")
    return content[start : end + 1] if start >= 0 and end > start else content


def ask(provider: str, key: str, model: str, user: str) -> dict:
    """One call; tries strict json_schema, then json_object, then plain."""
    base = {
        "model": model,
        "messages": [
            {"role": "system", "content": notes_writer.SYSTEM},
            {"role": "user", "content": user + "\n\nReturn only the JSON object."},
        ],
        "temperature": 0.2,
        "max_tokens": 3000,
    }
    if provider == "groq":
        base["reasoning_effort"] = "low"
    modes = [
        (
            "json_schema",
            {
                "type": "json_schema",
                "json_schema": {"name": "writeup", "strict": True, "schema": notes_writer.SCHEMA},
            },
        ),
        ("json_object", {"type": "json_object"}),
        ("plain", None),
    ]
    last = ""
    for mode, response_format in modes:
        body = dict(base)
        if response_format:
            body["response_format"] = response_format
        request = urllib.request.Request(
            URL[provider],
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": AGENT,
                "Accept": "application/json",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:160]}"
            if exc.code == 429:
                time.sleep(float(exc.headers.get("retry-after") or 20) + 1)
                return ask(provider, key, model, user)
            if exc.code in (400, 422):
                continue  # this mode is refused; the next may not be
            return {"error": last, "latency_ms": int((time.perf_counter() - started) * 1000)}
        except Exception as exc:  # noqa: BLE001
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        latency = int((time.perf_counter() - started) * 1000)
        message = payload["choices"][0]["message"]
        content = message.get("content") or ""
        usage = payload.get("usage") or {}
        return {
            "mode": mode,
            "content": content,
            "latency_ms": latency,
            "tokens_in": usage.get("prompt_tokens"),
            "tokens_out": usage.get("completion_tokens"),
        }
    return {"error": last or "every mode refused"}


def run_model(provider: str, model: str, key: str, cases, out: list, lock) -> None:
    for name, q in cases:
        got = ask(provider, key, model, notes_writer.brief(q))
        row = {
            "model": model,
            "case": name,
            "status": q.status,
            **{k: v for k, v in got.items() if k != "content"},
        }
        if "content" in got:
            try:
                raw = json.loads(strip(got["content"]))
                writeup, problems = notes_writer.check(raw, q)
                row.update(
                    parsed=True,
                    shown=writeup is not None,
                    problems=problems,
                    writeup=writeup.model_dump() if writeup else raw,
                )
            except json.JSONDecodeError as exc:
                row.update(
                    parsed=False,
                    shown=False,
                    problems=[f"unparseable: {exc}"],
                    raw=got["content"][:600],
                )
        with lock:
            out.append(row)
            # Kept as it comes, so a slow model never costs the others' rows.
            (HERE / "results.json").write_text(
                json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            print(
                f"{model[:34]:34} {name[:26]:26} {row.get('mode', '-'):11} "
                f"shown={row.get('shown')} {row.get('latency_ms')}ms {row.get('error', '')[:60]}",
                flush=True,
            )
        if provider == "groq":
            time.sleep(GROQ_PACE_S)


def main() -> None:
    load_keys()
    keys = {
        "groq": keys_from_env("GROQ_API_KEYS", "GROQ_API_KEY")[:1],  # one key: no pooling
        "nvidia": keys_from_env("NVIDIA_API_KEYS", "NVIDIA_API_KEY")[:1],
    }
    cases = live_cases()
    lookup = next(q for _, q in cases if "average-case lookup" in q.question)
    cases += written_cases(lookup)
    only = os.getenv("ONLY")
    rows: list[dict] = []
    lock = threading.Lock()
    threads = [
        threading.Thread(target=run_model, args=(p, m, keys[p][0], cases, rows, lock))
        for p, m in CANDIDATES
        if keys[p] and (not only or only in m)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    (HERE / "results.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
