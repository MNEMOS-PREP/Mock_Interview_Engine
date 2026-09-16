"""The five upstreams, as one object a route can depend on.

Production builds live HTTP clients from `module.json` (with `Mxx_BASE_URL`
overrides); tests install fixtures with `set_upstreams`. Either way the engine
asks `available(module)` before a hot-path call — the registry's probe is
cached, so a module that is down costs one health check every 30 seconds
rather than a timeout on every turn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..dependencies import deps
from .base import (
    CoveragePlanner,
    Evaluator,
    Memory,
    Questions,
    Resumes,
    UpstreamUnavailable,
)
from .fixtures import (
    FixtureCoveragePlanner,
    FixtureEvaluator,
    FixtureMemory,
    FixtureResumes,
    LocalQuestions,
)
from .live import LiveCoveragePlanner, LiveEvaluator, LiveMemory, LiveQuestions, LiveResumes


@dataclass
class Upstreams:
    m01: Resumes
    m02: CoveragePlanner
    m04: Memory
    m05: Questions
    m13: Evaluator
    #: M06's own playlist, for when M05 cannot be reached (§10).
    local_questions: LocalQuestions = field(default_factory=LocalQuestions)
    #: module id -> is it usable right now. Cached by the registry in production.
    is_available: Callable[[str], bool] = lambda _module: True
    #: module id -> the student-facing sentence for when it is not.
    on_missing: Callable[[str], str] = lambda module: f"{module} is unavailable."

    def available(self, module: str) -> bool:
        try:
            return bool(self.is_available(module))
        except Exception:  # noqa: BLE001 - a broken probe means "not available"
            return False


def live_upstreams() -> Upstreams:
    registry = deps()

    def url(module: str) -> str:
        dep = registry.get(module)
        return dep.base_url if dep is not None else ""

    def sentence(module: str) -> str:
        dep = registry.get(module)
        return dep.on_missing if dep is not None and dep.on_missing else f"{module} is unavailable."

    return Upstreams(
        m01=LiveResumes(url("M01")),
        m02=LiveCoveragePlanner(url("M02")),
        m04=LiveMemory(url("M04")),
        m05=LiveQuestions(url("M05")),
        m13=LiveEvaluator(url("M13")),
        is_available=registry.is_available,
        on_missing=sentence,
    )


def fixture_upstreams(**overrides) -> Upstreams:
    """Everything in-process. What the suite and a no-network demo run on."""
    values = {
        "m01": FixtureResumes(),
        "m02": FixtureCoveragePlanner(),
        "m04": FixtureMemory(),
        "m05": LocalQuestions(),
        "m13": FixtureEvaluator(),
    }
    values.update(overrides)
    return Upstreams(**values)


_current: Upstreams | None = None


def get_upstreams() -> Upstreams:
    """FastAPI dependency."""
    global _current
    if _current is None:
        _current = live_upstreams()
    return _current


def set_upstreams(upstreams: Upstreams | None) -> None:
    global _current
    _current = upstreams


__all__ = [
    "CoveragePlanner",
    "Evaluator",
    "Memory",
    "Questions",
    "Resumes",
    "UpstreamUnavailable",
    "Upstreams",
    "fixture_upstreams",
    "get_upstreams",
    "live_upstreams",
    "set_upstreams",
]
