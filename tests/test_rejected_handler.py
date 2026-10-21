"""Reject unsafe input without touching real temporary SQLite or a scheduler."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import ReminderRepository, UserRepository
from app.handlers.reminders import create_reminder
from app.services.scheduler import ReminderScheduler


@pytest.mark.parametrize(
    "text",
    [
        "in two minutes today test",
        "in 1 second today test",
    ],
)
def test_rejected_request_never_creates_or_schedules_a_reminder(tmp_path, text):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "rejection.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101), text=text, answer=AsyncMock()
        )
        try:
            async with db.session() as session:
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                )
                await session.commit()
            assert "No reminder was created" in message.answer.call_args.args[0]
            async with db.session() as session:
                count = await session.scalar(select(func.count()).select_from(Reminder))
                assert count == 0
            assert scheduler._scheduler.get_jobs() == []
        finally:
            await db.dispose()

    asyncio.run(run())
