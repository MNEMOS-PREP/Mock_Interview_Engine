"""Upstream probing — spec §10, `module.json`.

Platform Rule 2, applied to services rather than students: **a missing
dependency narrows the SCOPE of a session, never its quality, and never
silently.** For M06 that means a session always runs to a report:

* **M02 absent** — no job-description tailoring, and the preview says so.
* **M04 absent** — cold start: no history, no consent, no pinned prefix.
* **M05 absent** — M06's own short playlist; those turns are not scored.
* **M13 absent** — evaluation requests wait in the outbox.
* **M01 absent** — no project segment; drills cannot arrive at all.

Nothing is `required: true`, because M06 is the front door: a student who
opened a session must be able to finish it whichever of these is down.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ai_core.dependencies import DependencyRegistry

MANIFEST = Path(__file__).resolve().parents[2] / "module.json"


@lru_cache(maxsize=1)
def deps() -> DependencyRegistry:
    return DependencyRegistry.from_manifest(MANIFEST)


def reload() -> None:
    deps.cache_clear()


__all__ = ["MANIFEST", "deps", "reload"]
