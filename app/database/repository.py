"""Data-access helpers for users and reminders."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PendingBatch, PendingDraft, Reminder, User
from app.nlp.recurrence import Schedule


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, user_id: int, default_timezone: str) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            user = User(id=user_id, timezone=default_timezone)
            self._session.add(user)
            await self._session.flush()
        return user

    async def set_timezone(self, user_id: int, timezone: str) -> None:
        user = await self._session.get(User, user_id)
        if user:
            user.timezone = timezone


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        message: str,
        original_text: str,
        human_readable: str,
        schedule: Schedule,
    ) -> Reminder:
        reminder = Reminder(
            user_id=user_id,
            message=message,
            original_text=original_text,
            human_readable=human_readable,
            schedule_kind=schedule.kind,
            schedule_spec=schedule.to_json(),
        )
        self._session.add(reminder)
        await self._session.flush()
        return reminder

    async def get(self, reminder_id: int) -> Reminder | None:
        return await self._session.get(Reminder, reminder_id)

    async def list_active(self, user_id: int) -> list[Reminder]:
        result = await self._session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user_id, Reminder.active.is_(True))
            .order_by(Reminder.created_at.desc())
        )
        return list(result)

    async def all_active(self) -> list[Reminder]:
        result = await self._session.scalars(
            select(Reminder).where(Reminder.active.is_(True))
        )
        return list(result)

    async def deactivate(self, reminder_id: int) -> None:
        reminder = await self._session.get(Reminder, reminder_id)
        if reminder:
            reminder.active = False


class PendingDraftRepository:
    """Persistence API for incomplete owner-scoped date requests."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        user_id: int,
        original_text: str,
        message: str,
        target_date: date,
        expires_at: datetime,
    ) -> PendingDraft:
        draft = await self._session.scalar(
            select(PendingDraft).where(PendingDraft.user_id == user_id)
        )
        if draft is None:
            draft = PendingDraft(user_id=user_id)
            self._session.add(draft)
        draft.original_text = original_text
        draft.message = message
        draft.target_date = target_date
        draft.expires_at = expires_at
        await self._session.flush()
        return draft

    async def get(self, user_id: int, *, now: datetime) -> PendingDraft | None:
        draft = await self._session.scalar(
            select(PendingDraft).where(PendingDraft.user_id == user_id)
        )
        if draft and draft.expires_at <= now:
            await self._session.delete(draft)
            await self._session.flush()
            return None
        return draft

    async def delete(self, user_id: int) -> None:
        await self._session.execute(
            delete(PendingDraft).where(PendingDraft.user_id == user_id)
        )


class PendingBatchRepository:
    """Persistence API for owner-bound, confirmable batch previews."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, user_id: int, original_text: str, items_json: str, expires_at: datetime
    ) -> PendingBatch:
        batch = await self._session.scalar(
            select(PendingBatch).where(PendingBatch.user_id == user_id)
        )
        if batch is None:
            batch = PendingBatch(user_id=user_id)
            self._session.add(batch)
        batch.original_text = original_text
        batch.items_json = items_json
        batch.expires_at = expires_at
        await self._session.flush()
        return batch

    async def get(self, user_id: int, *, now: datetime) -> PendingBatch | None:
        batch = await self._session.scalar(
            select(PendingBatch).where(PendingBatch.user_id == user_id)
        )
        if batch and batch.expires_at <= now:
            await self._session.delete(batch)
            await self._session.flush()
            return None
        return batch

    async def delete(self, user_id: int) -> None:
        await self._session.execute(
            delete(PendingBatch).where(PendingBatch.user_id == user_id)
        )
