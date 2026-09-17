"""Transient per-session channels for what is not on the event log yet.

The SSE stream is two sources merged (spec §7):

* **the event log**, tailed by `seq` — durable, replayable, and the only thing
  a reconnecting client needs (`Last-Event-ID` is a seq);
* **interviewer tokens**, published here while a step is still running, so a
  student sees the interviewer start talking before the step has finished
  (the AC-6.4 gate is time to the first visible token).

Tokens are a preview. The `question.asked` event that follows carries the text
of record, and a client replaces the preview with it — which is also what
happens when the guard swaps a model line for its template mid-stream.

In-process on purpose: one API process in Phase 1. Several processes need a
shared channel (the master plan's Redis), and this class is the seam for it.
"""

from __future__ import annotations

import queue
import threading
from collections import defaultdict
from uuid import UUID


class TokenBroker:
    def __init__(self, maxsize: int = 1000):
        self._subscribers: dict[UUID, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self, session_id: UUID) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subscribers[session_id].append(q)
        return q

    def unsubscribe(self, session_id: UUID, q: queue.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(session_id, [])
            if q in subscribers:
                subscribers.remove(q)
            if not subscribers:
                self._subscribers.pop(session_id, None)

    def publish(self, session_id: UUID, message: dict) -> None:
        with self._lock:
            targets = list(self._subscribers.get(session_id, []))
        for q in targets:
            try:
                q.put_nowait(message)
            except queue.Full:
                # A client that stopped reading loses previews, never events:
                # the log is still there when it catches up.
                pass


broker = TokenBroker()

__all__ = ["TokenBroker", "broker"]
