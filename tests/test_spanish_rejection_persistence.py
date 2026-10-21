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
UNSUPPORTED_CASES = [
    c
    for c in CASES
    if c["baseline_compatibility"] == "gap" or c["oracle_kind"] in {"policy", "no_time"}
]
SPANISH_CASE_IDS = {
    "history_06",
    "history_07",
    "history_08",
    "history_10",
    "history_14",
    "history_15",
    "history_17",
    "history_18",
    "history_19",
    "history_22",
    "history_24",
    "history_25",
    "history_26",
    "derived_01",
}
SPANISH_CASES = [c for c in CASES if c["id"] in SPANISH_CASE_IDS]


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


@pytest.mark.parametrize("case", SPANISH_CASES, ids=lambda c: c["id"])
def test_supported_spanish_creates_persists_and_restores_exact_schedule(
    tmp_path, monkeypatch, case
):
    frozen = datetime.fromisoformat(case["now"])

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is None
            return frozen

    monkeypatch.setattr(parser_module, "datetime", FrozenDatetime)

    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "accepted.db")
        db = Database(url)
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, case["timezone"])
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101), text=case["input"], answer=AsyncMock()
        )
        try:
            await db.create_all()
            async with db.session() as session:
                await UserRepository(session).get_or_create(202, case["timezone"])
                await ReminderRepository(session).create(
                    user_id=202,
                    message="Existing reminder",
                    original_text="every 15 minutes existing reminder",
                    human_readable="Every 15 minutes",
                    schedule=Schedule(kind="interval", interval={"minutes": 15}),
                )
                await session.commit()
            before = await _rows(db)
            async with db.session() as session:
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    case["timezone"],
                )
                await session.commit()
            assert "Reminder added" in message.answer.call_args.args[0]
            async with db.session() as session:
                created = (await ReminderRepository(session).list_active(101))[0]
                rid = created.id
                assert created.original_text == case["input"]
                assert created.schedule_kind == "once"
                assert Schedule.from_json(
                    created.schedule_spec
                ).run_date == datetime.fromisoformat(case["expected_due"])
                assert case["payload"] in created.message.casefold()
                assert not any(
                    x.casefold() in created.message.casefold()
                    for x in case["forbidden_title_fragments"]
                )
            after = await _rows(db)
            assert len(after[0]) == 2 and len(after[1]) == 2
            assert before[0][0] in after[0] and before[1][0] in after[1]
            assert len(scheduler._scheduler.get_jobs()) == 1
            transport.send_message.assert_not_awaited()
        finally:
            await db.dispose()
        reopened = Database(url)
        try:
            assert await _rows(reopened) == after
            restored = ReminderScheduler(transport, reopened, case["timezone"])
            await restored._reload_all()
            job = restored._scheduler.get_job(f"rem:{rid}")
            assert job is not None and job.args[0] == rid and job.args[1] == 101
            assert job.trigger.run_date.replace(tzinfo=None) == datetime.fromisoformat(
                case["expected_due"]
            )
            assert len(restored._scheduler.get_jobs()) == 2
            async with reopened.session() as session:
                assert await session.scalar(text("PRAGMA integrity_check")) == "ok"
        finally:
            await reopened.dispose()

    asyncio.run(run())
