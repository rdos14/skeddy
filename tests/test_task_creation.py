"""Real SQLite/scheduler acceptance for typed task creation."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.database.base import Database
from app.database.repository import ItemRepository, ReminderRepository, UserRepository
from app.handlers import reminders as handlers
from app.nlp.recurrence import Schedule
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 18)


@pytest.mark.parametrize(
    ("source", "title"),
    [
        ("t revisar propuesta", "Revisar propuesta"),
        ("revisar esta tarea", "Revisar esta tarea"),
        ("review this task", "Review this task"),
        ("t revisar horas trabajadas", "Revisar horas trabajadas"),
    ],
)
def test_unscheduled_task_is_pending_after_restart_with_no_jobs(
    tmp_path, monkeypatch, source, title
):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "task.db")
        db = Database(url)
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            message_id=801,
            text=source,
            answer=AsyncMock(),
        )
        try:
            async with db.session() as session:
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=ItemRepository(session),
                )
                await session.commit()
                items = await ItemRepository(session).list_items(101)
                assert len(items) == 1
                assert items[0].kind == "task" and items[0].status == "pending"
                assert items[0].message == title
                assert items[0].reminder.original_text == message.text
                assert not items[0].active
                assert Schedule.from_json(items[0].schedule_spec).run_date is None
            assert scheduler._scheduler.get_jobs() == []
            assert "Task added" in message.answer.call_args.args[0]
            await db.dispose()
            db = Database(url)
            reloaded = ReminderScheduler(
                SimpleNamespace(send_message=AsyncMock()), db, "UTC"
            )
            await reloaded._reload_all()
            assert reloaded._scheduler.get_jobs() == []
            async with db.session() as session:
                assert (await ItemRepository(session).list_items(101))[0].kind == "task"
        finally:
            await db.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("source", "kind", "title"),
    [
        ("t revisar propuesta 27/10/2026 9am", "task", "Revisar propuesta"),
        ("revisar esta tarea 27/10/2026 9am", "task", "Revisar esta tarea"),
        ("review TASK 27/10/2026 9am", "task", "Review TASK"),
        ("revisar propuesta 27/10/2026 9am", "reminder", "Revisar propuesta"),
    ],
)
def test_scheduled_kind_and_title_follow_original_request(
    tmp_path, monkeypatch, source, kind, title
):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "scheduled.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            message_id=802,
            text=source,
            answer=AsyncMock(),
        )
        try:
            async with db.session() as session:
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=ItemRepository(session),
                )
                await session.commit()
                rows = await ItemRepository(session).list_items(101)
                assert len(rows) == 1
                item = rows[0]
                assert item.kind == kind
                assert item.message == title
                assert item.reminder.original_text == source
                assert Schedule.from_json(item.schedule_spec).run_date == datetime(
                    2026, 10, 27, 9
                )
            assert len(scheduler._scheduler.get_jobs()) == 1
            if kind == "task":
                assert "Task added" in message.answer.call_args.args[0]
                await scheduler._fire(item.id, 101, item.message)
                assert transport.send_message.await_count == 1
                async with db.session() as session:
                    assert (await ItemRepository(session).list_items(101))[
                        0
                    ].status == "pending"
        finally:
            await db.dispose()

    asyncio.run(run())
