import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import PendingBatch, Reminder
from app.database.repository import (
    PendingBatchRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.handlers.reminders import create_reminder
from app.nlp import analyze_batch
from app.services.batch import confirm_batch, serialize_batch
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 16, 49)
TEXT = (
    "1) payload alpha (📋 August 29th, 2026 at 9:00 AM)\n"
    "2) payload beta (📋 last Sunday at 1:54 PM)\n"
    "3) payload gamma (📋 yesterday at 10:00 AM)\n"
    "4) payload delta (📋 7 hours ago)\n"
    "5) payload epsilon (📋 4 hours ago)\n"
    "6) payload zeta (📋 Saturday at 9:00 AM)"
)


def test_batch_handler_creates_preview_not_concatenated_reminder(tmp_path, monkeypatch):
    async def run():
        import app.handlers.reminders as handler_module

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        monkeypatch.setattr(handler_module, "datetime", FrozenDatetime)
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "batch.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101), text=TEXT, answer=AsyncMock()
        )
        try:
            async with db.session() as session:
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    PendingDraftRepository(session),
                    PendingBatchRepository(session),
                )
                await session.commit()
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                row = await session.scalar(
                    select(PendingBatch).where(PendingBatch.user_id == 101)
                )
                assert row is not None
                preview = json.loads(row.items_json)
                assert [item["status"] for item in preview] == [
                    "past",
                    "past",
                    "past",
                    "past",
                    "past",
                    "complete",
                ]
                assert "Confirm" in message.answer.call_args.args[0]
        finally:
            await db.dispose()

    asyncio.run(run())


def test_confirm_batch_atomically_creates_only_future_items(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "confirm.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        preview = analyze_batch(TEXT, now=NOW)
        payload = serialize_batch(preview)
        try:
            async with db.session() as session:
                batches = PendingBatchRepository(session)
                await batches.upsert(
                    user_id=101,
                    original_text=TEXT,
                    items_json=payload,
                    expires_at=datetime(2026, 10, 22),
                )
                created = await confirm_batch(
                    user_id=101,
                    pending_batches=batches,
                    users=UserRepository(session),
                    reminders=ReminderRepository(session),
                    scheduler=scheduler,
                    default_tz="UTC",
                    now=NOW,
                )
                await session.commit()
                assert len(created) == 1
                assert created[0].message == "Payload zeta"
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 1
                )
                assert await batches.get(101, now=NOW) is None
                assert len(scheduler._scheduler.get_jobs()) == 1
        finally:
            await db.dispose()

    asyncio.run(run())
