"""Send each closed answer to M17 (Communication Coach), best effort.

From the M17 team's patch (Communication_Coach/patches/M06_send_turns_to_M17.patch),
applied 2026-11-22 (good_and_bads #16): until then the coach was mounted at
/coach and heard no interview at all, so "how you said it" had nothing behind it.

ON by default, at M17's PORTS.txt address; ``M06_M17_BASE_URL`` moves it, and
``M06_M17_BASE_URL=off`` turns it off. It runs on a background thread and
swallows every error: M17 being down or slow must never touch an interview. It
is deliberately not an ``ai_core.outbox`` channel (that needs a table and a retry
policy); a dropped send only means that one answer is not coached, never a wrong one.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

log = logging.getLogger("uvicorn.error")

#: PORTS.txt: M17's API.
DEFAULT_BASE = "http://127.0.0.1:8117"


def base_url() -> str | None:
    """Where M17 is, or None when it is turned off."""
    raw = os.getenv("M06_M17_BASE_URL", DEFAULT_BASE).strip()
    if not raw or raw.lower() in {"off", "0", "false", "none"}:
        return None
    return raw.rstrip("/")


def payload(
    *,
    turn_id: str,
    candidate_id: str,
    text: str,
    spoken: bool,
    duration_ms: int | None = None,
    silence_ms: int | None = None,
    cut_off: bool = False,
    question: str | None = None,
) -> dict:
    """M17's `POST /v1/coach/turns` body (its TurnIn)."""
    return {
        "source_module": "M06",
        "turn_id": turn_id,
        "candidate_id": candidate_id,
        "text": text,
        "modality": "spoken" if spoken else "typed",
        "duration_ms": duration_ms,
        "silence_ms": silence_ms,
        "cut_off": cut_off,
        "question": question,
        "recogniser": "m11" if spoken else None,
    }


def send_turn(**fields) -> None:  # noqa: ANN003 - the keywords of `payload`
    base = base_url()
    if base is None or not (fields.get("text") or "").strip():
        return
    body = payload(**fields)

    def post() -> None:
        try:
            from ai_core import service

            req = urllib.request.Request(
                f"{base}/v1/coach/turns",
                data=json.dumps(body).encode(),
                method="POST",
                headers={"Content-Type": "application/json", **service.headers()},
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as exc:  # noqa: BLE001 - never touch the interview
            log.info("M06: M17 not told about %s: %s", body["turn_id"], exc)

    threading.Thread(target=post, daemon=True).start()
