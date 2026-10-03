"""Shared fixtures for M06 tests.

**No test in this repo opens a socket.** Upstreams are the in-process fixtures
from `adapters.fixtures`, and the live clients are exercised against a patched
`urlopen` — so the suite runs on a laptop with nothing else up and no key.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest
from ai_core.db import get_session
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend_M06_Mock_Interview_Engine import adapters, llm
from backend_M06_Mock_Interview_Engine import models as _models  # noqa: F401 - registers tables
from backend_M06_Mock_Interview_Engine import router as router_module
from backend_M06_Mock_Interview_Engine.app import app


@pytest.fixture(autouse=True)
def _service_secret(monkeypatch):
    """A known platform secret, so no test reads or writes the developer's
    machine secret under their home directory (Platform_Core v0.12.0)."""
    monkeypatch.setenv("SERVICE_SECRET", "m06-test-secret")


@pytest.fixture(autouse=True)
def no_network_model():
    """`get_llm()` would read the real keys.txt beside the repos and go live.
    Every test starts with the model off; a test that wants one installs a stub."""
    llm.set_llm(llm.NullLLM(reason="tests run without a model"))
    yield
    llm.set_llm(None)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def db(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def engine_db(engine) -> Iterator[tuple[Session, Callable[[], Session]]]:
    """A session to assert with, and the factory a worker opens its own with."""
    with Session(engine) as session:
        yield session, lambda: Session(engine)


@pytest.fixture
def upstreams():
    fixture = adapters.fixture_upstreams()
    adapters.set_upstreams(fixture)
    yield fixture
    adapters.set_upstreams(None)


@pytest.fixture
def client(engine, upstreams) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[router_module.session_factory] = lambda: lambda: Session(engine)
    # Not a context manager: the lifespan would create tables in dev.db.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def candidate_id() -> uuid.UUID:
    return uuid.uuid4()


def student(candidate: uuid.UUID) -> dict[str, str]:
    """The dev resolver's headers (ai_core.identity, AI_AUTH_MODE=dev)."""
    return {"X-Role": "student", "X-Candidate-Id": str(candidate)}


def admin() -> dict[str, str]:
    return {"X-Role": "admin", "X-Candidate-Id": "ops"}


@pytest.fixture
def as_student(candidate_id):
    return student(candidate_id)
