"""Typed Tasks must not inherit legacy implicit 09:00 clocks."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import ItemRepository, ReminderRepository, UserRepository
from app.handlers import reminders as handlers
from app.services.scheduler import ReminderScheduler


@pytest.mark.parametrize(
    "source", ["t revisar tomorrow", "t revisar mañana", "task review every Monday"]
)
def test_task_date_or_recurrence_without_clock_does_not_guess(
    tmp_path, monkeypatch, source
):
    monkeypatch.setattr(
        handlers, "_local_now", lambda timezone: datetime(2026, 10, 21, 18)
    )

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "no-default.db"))
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
