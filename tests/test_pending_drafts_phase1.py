import asyncio
from datetime import date, datetime

from app.database.base import Database
from app.database.repository import PendingBatchRepository, PendingDraftRepository


def test_pending_draft_is_owner_scoped_and_survives_reopen(tmp_path):
    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "pending.db")
        db = Database(url)
        await db.create_all()
        expires = datetime(2026, 10, 21, 17)
        async with db.session() as session:
            repo = PendingDraftRepository(session)
            await repo.upsert(
                user_id=101,
                original_text="payload alpha next tuesday",
                message="Payload alpha",
                target_date=date(2026, 10, 27),
                expires_at=expires,
            )
            await session.commit()
        await db.dispose()

        reopened = Database(url)
        await reopened.create_all()
        async with reopened.session() as session:
            draft = await PendingDraftRepository(session).get(
                101, now=datetime(2026, 10, 21, 16, 50)
            )
            assert draft is not None
            assert draft.target_date == date(2026, 10, 27)
            assert (
                await PendingDraftRepository(session).get(
                    202, now=datetime(2026, 10, 21, 16, 50)
                )
                is None
            )
            await session.commit()
        await reopened.dispose()

    asyncio.run(run())


def test_expired_draft_and_batch_are_removed(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "expiry.db"))
        await db.create_all()
        async with db.session() as session:
            drafts = PendingDraftRepository(session)
            batches = PendingBatchRepository(session)
            await drafts.upsert(
                user_id=101,
                original_text="payload alpha next tuesday",
                message="Payload alpha",
                target_date=date(2026, 10, 27),
                expires_at=datetime(2026, 10, 21, 17),
            )
            await batches.upsert(
                user_id=101,
                original_text="1) payload alpha next tuesday",
                items_json="[]",
                expires_at=datetime(2026, 10, 21, 17),
            )
            assert await drafts.get(101, now=datetime(2026, 10, 21, 17)) is None
            assert await batches.get(101, now=datetime(2026, 10, 21, 17)) is None
            await session.commit()
        await db.dispose()

    asyncio.run(run())
