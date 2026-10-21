"""Unsupported history must not change real SQLite rows or scheduler jobs."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

import app.nlp.parser as parser_module
from app.database.base import Database
from app.database.models import Reminder, User
from app.database.repository import ReminderRepository, UserRepository
from app.handlers.reminders import create_reminder
from app.nlp.recurrence import Schedule
from app.services.scheduler import ReminderScheduler

CASES = json.loads(
    (Path(__file__).parent / "fixtures/skeddy_history_anonymized.json").read_text()
)["cases"]
UNSUPPORTED_CASES = [c for c in CASES if c["baseline_compatibility"] == "gap"]


async def _rows(db):
    async with db.session() as session:
        result = []
        for model in (User, Reminder):
            rows = await session.scalars(select(model).order_by(model.id))
            result.append(
                [
                    tuple(getattr(row, c.name) for c in model.__table__.columns)
                    for row in rows
                ]
            )
        return result


def _jobs(scheduler):
    return [
        (job.id, str(job.trigger), tuple(job.args))
        for job in scheduler._scheduler.get_jobs()
    ]


@pytest.mark.parametrize("case", UNSUPPORTED_CASES, ids=lambda c: c["id"])
@pytest.mark.parametrize("seed_existing", [False, True], ids=["empty", "existing"])
def test_history_rejection_preserves_rows_and_jobs(
    tmp_path, monkeypatch, case, seed_existing
):
    frozen = datetime.fromisoformat(case["now"])

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is None  # The parser API consumes a naive local clock.
            return frozen

    # Replace only the clock; handler, parser, repositories and scheduler are real.
    monkeypatch.setattr(parser_module, "datetime", FrozenDatetime)

    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "rejection.db")
        db = Database(url)
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, case["timezone"])
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101), text=case["input"], answer=AsyncMock()
        )
        try:
            await db.create_all()
            if seed_existing:
                async with db.session() as session:
                    user = await UserRepository(session).get_or_create(
                        202, case["timezone"]
                    )
                    reminder = await ReminderRepository(session).create(
                        user_id=user.id,
                        message="Existing reminder",
                        original_text="every 15 minutes existing reminder",
                        human_readable="Every 15 minutes",
                        schedule=Schedule(kind="interval", interval={"minutes": 15}),
                    )
                    scheduler.register(reminder, user.timezone)
                    await session.commit()
            before_rows = await _rows(db)
            before_jobs = _jobs(scheduler)
            assert len(before_rows[0]) == int(seed_existing)
            assert len(before_rows[1]) == int(seed_existing)
            assert len(before_jobs) == int(seed_existing)
            async with db.session() as session:
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    case["timezone"],
                )
                await session.commit()
            assert await _rows(db) == before_rows
            assert _jobs(scheduler) == before_jobs
            message.answer.assert_awaited_once()
            assert "No reminder was created" in message.answer.call_args.args[0]
            transport.send_message.assert_not_awaited()
        finally:
            await db.dispose()
        # Reopen a fresh database engine; check persisted values, not ORM cache.
        reopened = Database(url)
        try:
            assert await _rows(reopened) == before_rows
            async with reopened.session() as session:
                assert await session.scalar(text("PRAGMA integrity_check")) == "ok"
        finally:
            await reopened.dispose()

    asyncio.run(run())
