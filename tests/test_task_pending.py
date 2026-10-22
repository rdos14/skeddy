"""Task markers survive missing-clock prompts and unsafe dates reject."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import (
    ItemRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.handlers import reminders as handlers
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 18)


@pytest.mark.parametrize(
    "source",
    [
        "t revisar propuesta 27/10/2026",
        "revisar esta tarea 27/10/2026",
        "review task 27/10/2026",
    ],
)
def test_pending_date_retains_task_kind(tmp_path, monkeypatch, source):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "pending.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            message_id=803,
            text=source,
            answer=AsyncMock(),
        )
        try:
            async with db.session() as session:
                pending = PendingDraftRepository(session)
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending=pending,
                    items=ItemRepository(session),
                )
                await session.commit()
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                assert not scheduler._scheduler.get_jobs()
            await db.dispose()
            db = Database("sqlite+aiosqlite:///" + str(tmp_path / "pending.db"))
            message.text = "9am"
            message.message_id = 804
            async with db.session() as session:
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending=PendingDraftRepository(session),
                    items=ItemRepository(session),
                )
                await session.commit()
                rows = await ItemRepository(session).list_items(101)
                assert len(rows) == 1 and rows[0].kind == "task"
                assert rows[0].reminder.original_text == source
                assert not rows[0].message.startswith("T ")
                assert "Task added" in message.answer.call_args.args[0]
        finally:
            await db.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "source",
    [
        "t revisar 31/02/2027 9am",
        "t revisar 12/31/2026 9am",
        "t revisar 29/08/2026 9am",
        "t revisar tomorrow Friday at 9am",
        "t",
    ],
)
def test_invalid_task_timing_does_not_fall_back_to_unscheduled(
    tmp_path, monkeypatch, source
):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "invalid.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101), text=source, answer=AsyncMock()
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
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                assert not scheduler._scheduler.get_jobs()
        finally:
            await db.dispose()

    asyncio.run(run())
