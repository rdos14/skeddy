import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import PendingDraft, Reminder
from app.database.repository import (
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.handlers.reminders import create_reminder
from app.nlp.dates import combine_pending_date
from app.services.scheduler import ReminderScheduler


def test_pending_clock_combines_with_stored_date_and_rejects_past():
    complete = combine_pending_date(
        date(2026, 10, 27), "9am", now=datetime(2026, 10, 21, 16, 49)
    )
    assert complete.status == "complete"
    assert complete.due == datetime(2026, 10, 27, 9)
    past = combine_pending_date(
        date(2026, 10, 20), "9am", now=datetime(2026, 10, 21, 16, 49)
    )
    assert past.status == "past"


def test_handler_persists_pending_date_then_completes_without_reparsing_words(
    tmp_path, monkeypatch
):
    async def run():
        now = datetime(2026, 10, 21, 16, 49)
        import app.handlers.reminders as handler_module

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        monkeypatch.setattr(handler_module, "datetime", FrozenDatetime)
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "handler.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "America/Mexico_City")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            text="payload alpha next tuesday",
            answer=AsyncMock(),
        )
        try:
            async with db.session() as session:
                users = UserRepository(session)
                reminders = ReminderRepository(session)
                pending = PendingDraftRepository(session)
                await create_reminder(
                    message, users, reminders, scheduler, "America/Mexico_City", pending
                )
                await session.commit()
                assert "clock" in message.answer.call_args.args[0].lower()
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                assert (
                    await session.scalar(select(func.count()).select_from(PendingDraft))
                    == 1
                )

                message.text = "9am"
                await create_reminder(
                    message, users, reminders, scheduler, "America/Mexico_City", pending
                )
                await session.commit()
                created = (await reminders.list_active(101))[0]
                assert created.original_text == "payload alpha next tuesday"
                assert created.message == "Payload alpha"
                assert created.schedule_spec.find("2026-10-27T09:00:00") >= 0
                assert (
                    await session.scalar(select(func.count()).select_from(PendingDraft))
                    == 0
                )
                assert len(scheduler._scheduler.get_jobs()) == 1
        finally:
            await db.dispose()

    asyncio.run(run())
