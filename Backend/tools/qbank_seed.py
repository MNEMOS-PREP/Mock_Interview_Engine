"""Seed a student's question bank, and bring it up to date — an operator's tool.

    .venv\\Scripts\\python tools\\qbank_seed.py --candidate <id> --from-all
    .venv\\Scripts\\python tools\\qbank_seed.py --candidate <id> --write --budget 40
    .venv\\Scripts\\python tools\\qbank_seed.py --candidate <id> --remove

`--from-all` adds to the student's bank every question any interview in this
database addressed — the demo student's bank then holds everything the
platform has been asked so far (the user, 2026-11-18). A seeded question is
marked as such (`QBankSeed`): the page never says the student was asked it.
A question about one student's own resume is never copied to another.

`--write` then does what `refresh` does behind an interview, against the live
modules: asks M05 for item answer keys and tracks, M04 for concept names, has
the follow-ups answered (paced for the free tier; `--budget` caps the calls),
and draws `q_bank_discovered.pdf`. Run from Backend/, with M04 and M05 up.

`--remove` takes the seeded questions back out. The student's own stay.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.db import engine  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from backend_M06_Mock_Interview_Engine import (
    models,  # noqa: E402,F401 - registers tables
    qbank,  # noqa: E402
)
from backend_M06_Mock_Interview_Engine.models import InterviewSession, QBankSeed  # noqa: E402
from backend_M06_Mock_Interview_Engine.qbank import collect  # noqa: E402


def seed_from_all(db: Session, candidate: uuid.UUID) -> int:
    own = {q.key for q in collect.asked_of(db, candidate)}
    have = {
        row.question_key
        for row in db.exec(select(QBankSeed).where(QBankSeed.candidate_id == candidate)).all()
    }
    others = [
        c for c in db.exec(select(InterviewSession.candidate_id).distinct()).all() if c != candidate
    ]
    found = collect.merge(q for c in others for q in collect.asked_of(db, c))
    added = 0
    for question in found:
        if question.resume or question.key in own or question.key in have:
            continue
        payload = question.payload()
        payload.update(times=0, asked=False)
        db.add(
            QBankSeed(
                candidate_id=candidate,
                question_key=question.key,
                payload=payload,
                note="seeded from every interview in this database (tools/qbank_seed.py)",
            )
        )
        added += 1
    db.commit()
    return added


def remove(db: Session, candidate: uuid.UUID) -> int:
    rows = db.exec(select(QBankSeed).where(QBankSeed.candidate_id == candidate)).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate", required=True, type=uuid.UUID)
    parser.add_argument("--from-all", action="store_true", help="seed every question asked here")
    parser.add_argument("--write", action="store_true", help="look up, write answers, draw")
    parser.add_argument("--budget", type=int, default=None, help="at most this many model calls")
    parser.add_argument("--remove", action="store_true", help="take the seeded questions out")
    args = parser.parse_args()

    # The service makes missing tables at startup; so does this, so it can
    # run before the service has been restarted on a new version.
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        if args.remove:
            print(f"removed {remove(db, args.candidate)} seeded questions")
        if args.from_all:
            print(f"seeded {seed_from_all(db, args.candidate)} questions")

    if args.write:
        from backend_M06_Mock_Interview_Engine.adapters import get_upstreams
        from backend_M06_Mock_Interview_Engine.llm import get_llm

        qbank.refresh(
            args.candidate,
            factory=lambda: Session(engine),
            upstreams=get_upstreams(),
            llm=get_llm(),
            budget=args.budget,
        )

    with Session(engine) as db:
        built = qbank.current(db, args.candidate)
    book = built.book
    print(
        f"{book.questions} questions · {book.follow_ups} follow-ups · "
        f"{len(book.subjects)} subjects · {book.pending} still to write"
    )
    for subject in book.subjects:
        print(f"  {subject.title}: {len(subject.entries)}")
    print(f"file: {qbank._paths(args.candidate)[0].resolve()}")


if __name__ == "__main__":
    main()
