"""Presence — FR-6.13, EC-6.8, spec §6.8, and §8's "Disconnected: timer paused".

Trap 5: "Student's browser crashes at minute 30 and everything is gone. This
will happen, and it will happen to your demo." The state already survives — it
is a fold over the log. What these tests are about is the student: the clock
that should not run while they are gone, the line that tells them where they
were, and the session that must not hold their one slot for ever if they never
come back.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from backend_M06_Mock_Interview_Engine import presence, store, sweeper
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import welcome_line

from .day10 import Clock, events, make, rounds_plan, say, session

ONE_ROUND = rounds_plan(("r1", 3, 10.0))


def live(db, clock=None):
    clock = clock or Clock()
    engine = make(db, plan=ONE_ROUND, clock=clock)
    row = session(engine, minutes=30)
    return engine, row, clock


def gone(engine, row, clock, at_s: float) -> None:
    """The student's only stream detaches at `at_s` seconds in."""
    clock.at(at_s)
    presence.presence.attach(row.id)
    presence.presence.detach(row.id, clock())


def returns(engine, row, clock, at_s: float, **kw):
    clock.at(at_s)
    return presence.back(engine.db, row.id, clock(), **kw)


# ── gone, and back ────────────────────────────────────────────────────────


def test_a_refresh_is_not_a_disconnect(db):
    """A detach shorter than `LOST_AFTER_S` — a refresh, a blip — writes
    nothing: the student never left, and their clock never stopped."""
    engine, row, clock = live(db)
    gone(engine, row, clock, 60)
    state = returns(engine, row, clock, 62)
    assert not events(engine, row, "connection.lost")
    assert state.flags.reconnect_count == 0


@pytest.mark.gate
def test_a_disconnect_stops_the_clock_and_the_return_restarts_it_after_the_grace(db):
    """§8 "Disconnected — timer paused", §6.8 "a 30-second grace before the
    timer restarts". Ten minutes away cost nothing; neither do the first
    thirty seconds back."""
    engine, row, clock = live(db)
    used_at_drop = engine.state(row.id).time_used_s(clock()) + 60

    gone(engine, row, clock, 60)
    state = returns(engine, row, clock, 660)

    assert [e["grace_s"] for e in events(engine, row, "connection.resumed")] == [presence.GRACE_S]
    assert state.flags.away_since is None and state.flags.reconnect_count == 1
    clock.at(660 + presence.GRACE_S)
    assert state.time_used_s(clock()) == pytest.approx(used_at_drop, abs=1.0)
    clock.at(660 + presence.GRACE_S + 20)
    assert state.time_used_s(clock()) == pytest.approx(used_at_drop + 20, abs=1.0)


def test_a_return_that_is_an_answer_has_no_grace(db):
    """A student who answers is already going: the clock restarts at once."""
    engine, row, clock = live(db)
    gone(engine, row, clock, 60)
    clock.at(660)
    say(engine, row, "I don't know")

    (back,) = events(engine, row, "connection.resumed")
    assert back["grace_s"] == 0.0
    kinds = [e.kind for e in store.events_for(db, row.id)]
    assert kinds.index("connection.resumed") < kinds.index("answer.received")


def test_two_tabs_coming_back_count_one_reconnect(db):
    engine, row, clock = live(db)
    gone(engine, row, clock, 60)
    returns(engine, row, clock, 300)
    state = returns(engine, row, clock, 300)
    assert len(events(engine, row, "connection.resumed")) == 1
    assert state.flags.reconnect_count == 1


def test_a_tab_still_open_means_nobody_left(db):
    engine, row, clock = live(db)
    presence.presence.attach(row.id)
    presence.presence.attach(row.id)
    presence.presence.detach(row.id, clock())
    assert row.id not in presence.presence.pending()
    presence.presence.detach(row.id, clock())
    assert row.id in presence.presence.pending()
    presence.presence.take_gone(row.id)


def test_the_disconnect_is_dated_when_the_stream_went_not_when_it_was_noticed(engine_db):
    """Nobody came back, so the sweeper writes it — dated at the detach, so
    the minutes before the sweep are not charged either."""
    db, factory = engine_db
    engine, row, clock = live(db)
    gone(engine, row, clock, 120)
    clock.at(120 + 40)
    presence.sweep(factory, clock())

    lost = [e for e in store.events_for(db, row.id) if e.kind == "connection.lost"]
    assert len(lost) == 1
    state = engine.state(row.id)
    assert state.flags.away_since is not None
    assert state.time_used_s(clock()) == pytest.approx(120, abs=1.0)


def test_a_paused_session_is_never_marked_away(engine_db):
    """The pause already stopped the clock, and has its own cap."""
    db, factory = engine_db
    engine, row, clock = live(db)
    store.record(db, row, "session.paused", step="pause")
    gone(engine, row, clock, 60)
    clock.at(600)
    presence.sweep(factory, clock())
    assert not events(engine, row, "connection.lost")


# ── never back (EC-6.14) ─────────────────────────────────────────────────


@pytest.mark.gate
def test_away_longer_than_an_abandoned_pause_frees_the_slot(engine_db):
    """A stopped clock never runs out, so the live-overdue check alone would
    hold this candidate's one slot for ever — the lockout fixed before day 9,
    back through a side door. Away as long as an abandoned pause, it ends."""
    db, factory = engine_db
    engine, row, clock = live(db)
    gone(engine, row, clock, 60)
    clock.at(70)
    presence.sweep(factory, clock())
    away_since = engine.state(row.id).flags.away_since

    nearly = away_since + timedelta(seconds=sweeper.ABANDONED_PAUSE_S - 60)
    assert sweeper.close_abandoned(factory, engine.upstreams, engine.llm, now=nearly) == []
    later = away_since + timedelta(seconds=sweeper.ABANDONED_PAUSE_S + 60)
    assert sweeper.close_abandoned(factory, engine.upstreams, engine.llm, now=later) == [
        str(row.id)
    ]
    db.expire_all()
    state = engine.state(row.id)
    assert state.status is SessionStatus.ended and state.end_reason == "abandoned"


# ── where we were (§6.8) ─────────────────────────────────────────────────


@pytest.mark.gate
def test_the_welcome_says_which_question_of_which_round(db):
    """ "Welcome back — we were on question 4 of the DSA round": the number is
    the student's count — new questions in the round, not follow-ups."""
    engine, row, clock = live(db)
    say(engine, row, "I don't know")  # the warm-up; the round opens
    say(engine, row, "I don't know")  # its first question; the second opens
    state = engine.state(row.id)
    line = welcome_line(state)
    assert "question 2 of Data structures" in line


def test_the_welcome_at_the_warm_up_and_at_the_closing(db):
    engine, row, clock = live(db)
    assert "of the warm-up" in welcome_line(engine.state(row.id))
    for _ in range(6):
        state = engine.state(row.id)
        if state.transcript[-1].question_source == "closing":
            break
        say(engine, row, "I don't know")
    assert "your questions" in welcome_line(engine.state(row.id)).lower()


def test_resume_state_over_http_is_a_read(client, as_student):
    """Fetching it twice — or a prefetch — never counts a reconnect."""
    sid = client.post(
        "/v1/interviews",
        json={"minutes": 30},
        headers=as_student,
    ).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    first = client.get(f"/v1/interviews/{sid}/resume-state", headers=as_student)
    second = client.get(f"/v1/interviews/{sid}/resume-state", headers=as_student).json()
    assert first.status_code == 200
    assert first.json()["welcome"] == second["welcome"] and second["welcome"]
    assert second["open_question"]["turn_id"] == second["transcript_tail"][-1]["turn_id"]
    assert second["reconnect_count"] == 0 and second["away"] is False


# ── more than two (§6.8) ─────────────────────────────────────────────────


def test_a_connection_that_keeps_dropping_is_offered_a_way_out(db):
    """§6.8: "> 2 reconnects triggers a modality-degradation suggestion". Text
    is already the floor in Phase 1, so the way out is the pause or the end."""
    engine, row, clock = live(db)
    t = 60.0
    for count in (1, 2, 3):
        gone(engine, row, clock, t)
        state = returns(engine, row, clock, t + 60)
        t += 120
        assert state.flags.reconnect_count == count
        if count <= presence.SUGGEST_AFTER:
            assert presence.suggestion(state) is None
    assert "dropped 3 times" in presence.suggestion(state)
    assert "pause once" in presence.suggestion(state)

    paused = state.model_copy(deep=True)
    paused.flags.pause_used = True
    assert "pause" not in presence.suggestion(paused)


# ── the stream is the presence signal ────────────────────────────────────


def test_the_stream_attaching_is_the_return(engine_db):
    """The wiring: a session already marked away gets its `connection.resumed`
    from the stage re-attaching — written before the first sweep, so the same
    stream carries it — and the stream going leaves the note a later
    disconnect is dated from.

    Driven through the endpoint's own generator rather than a TestClient:
    a live session's stream never ends, and the test client waits for it.
    """
    import asyncio

    from backend_M06_Mock_Interview_Engine.router import session_events

    db, factory = engine_db
    engine, row, clock = live(db)
    store.record(db, row, "connection.lost", step="away:1")

    class Browser:
        headers: dict = {}

        async def is_disconnected(self) -> bool:
            return False

    async def attach_read_and_leave() -> list[str]:
        """Read the first sweep — everything already on the log — and leave.

        Bounded by order, not by count: `connection.lost` was written before
        the stream opened, so the first sweep carries it, and the return the
        stream itself writes must follow it in that same sweep. Waiting for
        frames past it would wait on heartbeats (15 s each) — which is how
        the first version of this test turned one mutation into nine minutes.
        """
        response = await session_events(row.id, Browser(), after=None, sessions=factory)
        frames: list[str] = []
        body = response.body_iterator
        try:
            while not any("connection.lost" in f for f in frames):
                frames.append(await asyncio.wait_for(body.__anext__(), timeout=5))
            try:
                frames.append(await asyncio.wait_for(body.__anext__(), timeout=2))
            except TimeoutError:
                pass
            assert presence.presence.attached(row.id) == 1
        finally:
            await body.aclose()
        return frames

    frames = asyncio.run(attach_read_and_leave())

    assert any("event: connection.resumed" in f for f in frames)
    db.expire_all()
    state = engine.state(row.id)
    assert state.flags.away_since is None and state.flags.reconnect_count == 1
    assert presence.presence.attached(row.id) == 0
    assert presence.presence.take_gone(row.id) is not None, "the stream left no note"


def test_the_sweeper_runs_the_presence_pass(engine_db):
    """The wiring: `sweep_once` writes a pending disconnect, so a student who
    never comes back is marked away without anybody calling `presence.sweep`."""
    from ai_core.timeutil import utcnow

    db, factory = engine_db
    engine, row, clock = live(db)
    presence.presence.attach(row.id)
    presence.presence.detach(row.id, utcnow() - timedelta(seconds=30))
    sweeper.sweep_once(factory, engine.upstreams, engine.llm)
    db.expire_all()
    assert engine.state(row.id).flags.away_since is not None


def test_a_disconnect_is_never_dated_before_the_log(engine_db):
    """A step that was already running when the stream went finishes after
    it; the disconnect is dated after that step, so the log's clock never
    runs backwards."""
    from ai_core.timeutil import as_utc, utcnow

    db, factory = engine_db
    engine, row, clock = live(db)
    last = store.events_for(db, row.id)[-1]
    presence.presence.attach(row.id)
    presence.presence.detach(row.id, utcnow() - timedelta(minutes=10))
    presence.sweep(factory, utcnow())
    (lost,) = [e for e in store.events_for(db, row.id) if e.kind == "connection.lost"]
    assert as_utc(lost.at) >= as_utc(last.at)


def test_pausing_while_away_records_the_return_first(client, as_student, engine):
    """The pause is an action, so it is presence: the return is written
    before the pause, and the student's one pause is not spent on a
    disconnect."""
    from sqlmodel import Session

    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    with Session(engine) as db:
        row = store.get_session_row(db, uuid.UUID(sid))
        store.record(db, row, "connection.lost", step="away:1")
    assert client.post(f"/v1/interviews/{sid}/pause", headers=as_student).status_code == 200
    with Session(engine) as db:
        kinds = [e.kind for e in store.events_for(db, uuid.UUID(sid))]
    assert kinds[-2:] == ["connection.resumed", "session.paused"]
