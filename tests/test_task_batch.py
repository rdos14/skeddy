"""A numbered batch classifies every line independently."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.database.base import Database
from app.database.repository import (
    ItemRepository,
    PendingBatchRepository,
    ReminderRepository,
    UserRepository,
)
from app.nlp import analyze_batch
from app.services.batch import confirm_batch, serialize_batch
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 18)


def test_batch_preserves_per_item_types_and_unscheduled_tasks(tmp_path):
    source = (
        "1) t revisar propuesta\n"
        "2) revisar tarea 27/10/2026 9am\n"
        "3) revisar equipo 27/10/2026 10am"
    )
    analysis = analyze_batch(source, now=NOW)
    assert [item.status for item in analysis.items] == ["complete"] * 3

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "batch.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                pending = PendingBatchRepository(session)
                await pending.upsert(
                    user_id=101,
                    original_text=source,
                    items_json=serialize_batch(analysis),
                    expires_at=NOW + timedelta(hours=24),
                )
                created = await confirm_batch(
                    user_id=101,
                    pending_batches=pending,
                    users=UserRepository(session),
                    reminders=ReminderRepository(session),
                    scheduler=scheduler,
                    default_tz="UTC",
                    now=NOW,
                )
                await session.commit()
                assert len(created) == 3
                states = [
                    await ItemRepository(session).get_item_state(101, item.id)
                    for item in created
                ]
                assert [state.kind for state in states] == ["task", "task", "reminder"]
                assert created[0].message == "Revisar propuesta"
                assert not created[0].active
                assert created[0].original_text == "t revisar propuesta"
                assert len(scheduler._scheduler.get_jobs()) == 2
        finally:
            await db.dispose()

    asyncio.run(run())
