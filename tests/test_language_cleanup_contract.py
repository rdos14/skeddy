"""Language removal must retain typed ES/EN scheduled Task creation."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.database.base import Database
from app.database.repository import ItemRepository, ReminderRepository, UserRepository
from app.handlers import reminders as handlers
from app.nlp import parse
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 18)


@pytest.mark.parametrize(
    "source",
    [
        "t in one minute payload",
        "t mañana a las 9 revisar equipo",
        "review task every Monday at 9am",
    ],
)
def test_typed_scheduled_tasks_survive_language_cleanup(tmp_path, monkeypatch, source):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "language-task.db"))
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
                await session.commit()
                rows = await ItemRepository(session).list_items(101)
                assert len(rows) == 1 and rows[0].kind == "task"
                assert rows[0].active
                assert len(scheduler._scheduler.get_jobs()) == 1
        finally:
            await db.dispose()

    asyncio.run(run())


def test_spanish_recurrence_marker_cannot_degrade_to_english_oneoff():
    assert parse("cada Monday at 9am payload", now=NOW) is None


@pytest.mark.parametrize("text", ["kech at 9 payload", "tush at 9 payload"])
def test_retired_period_words_do_not_change_into_bare_clock(text):
    assert parse(text, now=NOW) is None
