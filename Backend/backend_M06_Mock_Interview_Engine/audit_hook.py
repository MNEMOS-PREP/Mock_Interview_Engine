"""Records which question was picked, and why, in the Platform_Audit ledger.

Optional by construction: if `mnemos_audit` is not importable, or the audit
service is down, the interview runs exactly as before (the SDK never raises into
host code and spools while the service is away). One ledger trace per
interview; each pick is one decision in it.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

try:  # the SDK lives in Platform-Audit/sdk/python; absent is fine
    from mnemos_audit import audit as _audit
    from mnemos_audit import context as _cx
except Exception:  # noqa: BLE001
    _audit = _cx = None

_lock = threading.Lock()
_configured = False
_traces: dict[str, str] = {}  # interview id -> ledger trace id


def _ready() -> bool:
    global _configured
    if _audit is None:
        return False
    with _lock:
        if not _configured:
            _audit.configure("M06", code_version="m06")
            _configured = True
    return True


def record_selection(row, state, selected) -> None:
    """One decision per pick. Never raises."""
    try:
        if not _ready():
            return
        sid = str(row.id)
        with _lock:
            tid = _traces.get(sid)
        if tid is None:
            with _audit.trace("interview", session_ref=sid, subject=str(row.candidate_id)) as tid:
                pass
            with _lock:
                _traces[sid] = tid
        item, chosen = selected.item, selected.selection or {}
        with (
            _cx.bind(trace_id=tid, span_id=_cx.new_id()),
            _audit.decision_scope("M06.select_next_question") as d,
        ):
            d.inputs(summary={
                "mode": str(getattr(state, "mode", "")),
                "asked_so_far": len(getattr(state, "transcript", []) or []),
                "degraded": sorted(selected.degraded),
            })
            if item is None:
                d.chosen(None, method="rule", rules_fired=[f"no_question:{selected.empty_reason}"])
                return
            d.chosen(
                str(getattr(item, "question_id", None) or getattr(item, "source", "")),
                method="rule",
                rules_fired=[x for x in (chosen.get("reason"), getattr(item, "source", None)) if x],
            )
            kind = getattr(item, "rubric_round_type", None) or "question"
            d.rationale(free_text=f"{kind}: {item.stem[:140]}")
            d.output("question", str(getattr(item, "question_id", None) or ""))
    except Exception:  # noqa: BLE001
        log.debug("audit hook skipped", exc_info=True)
