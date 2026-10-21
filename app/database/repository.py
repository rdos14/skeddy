"""Data-access helpers for users and reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

if TYPE_CHECKING:
    from app.services.scheduler import ReminderScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdditionalEvent,
    ItemState,
    MenuDraft,
    PendingBatch,
    PendingDraft,
    Reminder,
    User,
)
from app.nlp.dates import analyze_datetime, combine_pending_date
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
        self._session.add(
            ItemState(reminder_id=reminder.id, user_id=user_id, kind="reminder")
        )
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


class ItemRepository:
    """Owner-scoped state, menu and additional-event API.

    ``list_items`` deliberately treats a missing state row as a legacy row:
    only active legacy rows are pending, and no inactive legacy row becomes
    completed without an explicit user action.
    """

    VALID_KINDS = {"reminder", "task", "note"}

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _owned(self, user_id: int, reminder_id: int) -> Reminder | None:
        return await self._session.scalar(
            select(Reminder).where(
                Reminder.id == reminder_id, Reminder.user_id == user_id
            )
        )

    async def get_item_state(self, user_id: int, reminder_id: int) -> ItemState | None:
        return await self._session.scalar(
            select(ItemState).where(
                ItemState.reminder_id == reminder_id, ItemState.user_id == user_id
            )
        )

    read_item_state = get_item_state

    async def create_item_state(
        self, user_id: int, reminder_id: int, kind: str = "reminder"
    ) -> ItemState | None:
        if kind not in self.VALID_KINDS:
            raise ValueError("kind must be reminder, task or note")
        reminder = await self._owned(user_id, reminder_id)
        if reminder is None:
            return None
        state = await self._state_for(reminder)
        state.kind = kind
        await self._session.flush()
        return state

    async def list_item_state(
        self, user_id: int, *, completed: bool = False, offset: int = 0, limit: int = 10
    ) -> list[ItemMenuItem]:
        return await self.list_items(
            user_id, completed=completed, offset=offset, limit=limit
        )

    async def _state_for(self, reminder: Reminder) -> ItemState:
        state = await self.get_item_state(reminder.user_id, reminder.id)
        if state is None:
            state = ItemState(
                reminder_id=reminder.id, user_id=reminder.user_id, kind="reminder"
            )
            self._session.add(state)
            await self._session.flush()
        return state

    async def list_items(
        self,
        user_id: int,
        *,
        completed: bool = False,
        offset: int = 0,
        limit: int = 10,
    ) -> list[ItemMenuItem]:
        result = await self._session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .order_by(Reminder.created_at.desc(), Reminder.id.desc())
        )
        rows: list[ItemMenuItem] = []
        for reminder in result:
            state = await self.get_item_state(user_id, reminder.id)
            status = (
                state.status if state else ("pending" if reminder.active else "legacy")
            )
            kind = state.kind if state else "reminder"
            if completed:
                if status != "completed":
                    continue
            elif status == "completed" or status == "deleted":
                continue
            elif state is None and not reminder.active:
                continue
            rows.append(ItemMenuItem(reminder, kind=kind, status=status))
        return rows[offset : offset + limit]

    async def count_items(self, user_id: int, *, completed: bool = False) -> int:
        return len(await self.list_items(user_id, completed=completed, limit=10**9))

    async def _mutate(
        self, user_id: int, reminder_id: int
    ) -> tuple[Reminder, ItemState] | None:
        reminder = await self._owned(user_id, reminder_id)
        if reminder is None:
            return None
        return reminder, await self._state_for(reminder)

    async def complete(
        self,
        user_id: int,
        reminder_id: int,
        *,
        scheduler: ReminderScheduler | None = None,
    ) -> ItemState | None:
        pair = await self._mutate(user_id, reminder_id)
        if pair is None:
            return None
        reminder, state = pair
        if state.status == "completed":
            return state
        state.status = "completed"
        state.completed_at = datetime.now()
        reminder.active = False
        await self._session.execute(
            update(AdditionalEvent)
            .where(
                AdditionalEvent.user_id == user_id,
                AdditionalEvent.reminder_id == reminder_id,
                AdditionalEvent.active.is_(True),
            )
            .values(active=False)
        )
        if scheduler is not None:
            scheduler.cancel_all(reminder_id)
        await self._session.flush()
        return state

    async def delete(
        self,
        user_id: int,
        reminder_id: int,
        *,
        scheduler: ReminderScheduler | None = None,
    ) -> ItemState | None:
        pair = await self._mutate(user_id, reminder_id)
        if pair is None:
            return None
        reminder, state = pair
        if state.status == "deleted":
            return state
        state.status = "deleted"
        reminder.active = False
        await self._session.execute(
            update(AdditionalEvent)
            .where(
                AdditionalEvent.user_id == user_id,
                AdditionalEvent.reminder_id == reminder_id,
                AdditionalEvent.active.is_(True),
            )
            .values(active=False)
        )
        if scheduler is not None:
            scheduler.cancel_all(reminder_id)
        await self._session.flush()
        return state

    async def change_type(
        self, user_id: int, reminder_id: int, kind: str
    ) -> ItemState | None:
        if kind not in self.VALID_KINDS:
            raise ValueError("kind must be reminder, task or note")
        pair = await self._mutate(user_id, reminder_id)
        if pair is None:
            return None
        reminder, state = pair
        if state.status == "completed":
            return state
        state.kind = kind
        if kind == "note":
            reminder.active = False
            await self._session.execute(
                update(AdditionalEvent)
                .where(
                    AdditionalEvent.user_id == user_id,
                    AdditionalEvent.reminder_id == reminder_id,
                    AdditionalEvent.active.is_(True),
                )
                .values(active=False)
            )
        else:
            reminder.active = True
        await self._session.flush()
        return state

    async def add_time_events(
        self, user_id: int, reminder_id: int, due_dates: list[datetime]
    ) -> list[AdditionalEvent]:
        reminder = await self._owned(user_id, reminder_id)
        if reminder is None:
            return []
        state = await self.get_item_state(user_id, reminder_id)
        if state and state.status in {"completed", "deleted"}:
            return []
        created: list[AdditionalEvent] = []
        for due_at in due_dates:
            exists = await self._session.scalar(
                select(AdditionalEvent).where(
                    AdditionalEvent.user_id == user_id,
                    AdditionalEvent.reminder_id == reminder_id,
                    AdditionalEvent.due_at == due_at,
                )
            )
            if exists is not None:
                if exists.active:
                    created.append(exists)
                continue
            event = AdditionalEvent(
                user_id=user_id, reminder_id=reminder_id, due_at=due_at
            )
            self._session.add(event)
            await self._session.flush()
            created.append(event)
        return created

    async def extra_events(
        self, user_id: int, reminder_id: int, *, active_only: bool = True
    ) -> list[AdditionalEvent]:
        query = select(AdditionalEvent).where(
            AdditionalEvent.user_id == user_id,
            AdditionalEvent.reminder_id == reminder_id,
        )
        if active_only:
            query = query.where(AdditionalEvent.active.is_(True))
        return list(await self._session.scalars(query.order_by(AdditionalEvent.due_at)))

    async def get_menu_draft(self, user_id: int) -> MenuDraft | None:
        return await self._draft(user_id, None)

    async def delete_menu_drafts(self, user_id: int) -> None:
        await self._session.execute(
            delete(MenuDraft).where(MenuDraft.user_id == user_id)
        )

    async def begin_add_time(
        self, user_id: int, reminder_id: int, *, expires_at: datetime
    ) -> AddTimeResult:
        pair = await self._mutate(user_id, reminder_id)
        if pair is None:
            return AddTimeResult("not_found")
        _, state = pair
        if state.status == "completed":
            return AddTimeResult("reopen_required")
        if state.kind == "note":
            return AddTimeResult("note_requires_type")
        draft = await self._session.scalar(
            select(MenuDraft).where(MenuDraft.user_id == user_id)
        )
        if draft is None:
            draft = MenuDraft(
                user_id=user_id,
                reminder_id=reminder_id,
                original_text="",
                target_date=None,
                expires_at=expires_at,
            )
            self._session.add(draft)
        else:
            draft.reminder_id = reminder_id
            draft.original_text = ""
            draft.target_date = None
            draft.expires_at = expires_at
        await self._session.flush()
        return AddTimeResult("awaiting_input")

    async def _draft(self, user_id: int, reminder_id: int | None) -> MenuDraft | None:
        query = select(MenuDraft).where(MenuDraft.user_id == user_id)
        if reminder_id is not None:
            query = query.where(MenuDraft.reminder_id == reminder_id)
        draft = await self._session.scalar(query)
        if draft and draft.expires_at <= datetime.now():
            await self._session.delete(draft)
            await self._session.flush()
            return None
        return draft

    async def add_time(
        self,
        user_id: int,
        reminder_id: int,
        text: str,
        *,
        now: datetime,
        scheduler: ReminderScheduler,
        timezone: str,
    ) -> AddTimeResult:
        reminder = await self._owned(user_id, reminder_id)
        if reminder is None:
            return AddTimeResult("not_found")
        state = await self.get_item_state(user_id, reminder_id)
        kind = state.kind if state else "reminder"
        if state and state.status == "completed":
            return AddTimeResult("reopen_required")
        if state and state.status == "deleted":
            return AddTimeResult("not_found")
        if kind == "note":
            return AddTimeResult("note_requires_type")
        analysis = analyze_datetime(text, now=now)
        if analysis.status == "missing_time" and analysis.target_date:
            draft = await self._draft(user_id, reminder_id)
            if draft is None:
                draft = MenuDraft(user_id=user_id, reminder_id=reminder_id)
                self._session.add(draft)
            draft.original_text = text
            draft.target_date = analysis.target_date
            draft.expires_at = now + timedelta(hours=24)
            await self._session.flush()
            return AddTimeResult("missing_time", target_date=analysis.target_date)
        if analysis.status != "complete" or analysis.due is None:
            return AddTimeResult("invalid")
        return await self._add_due(
            user_id, reminder_id, analysis.due, scheduler=scheduler, timezone=timezone
        )

    addtime = add_time

    async def add_time_clock(
        self,
        user_id: int,
        reminder_id: int,
        text: str,
        *,
        now: datetime,
        scheduler: ReminderScheduler,
        timezone: str,
    ) -> AddTimeResult:
        state = await self.get_item_state(user_id, reminder_id)
        if state and state.status == "completed":
            return AddTimeResult("reopen_required")
        if state and state.status == "deleted":
            return AddTimeResult("not_found")
        if state and state.kind == "note":
            return AddTimeResult("note_requires_type")
        draft = await self._draft(user_id, reminder_id)
        if draft is None:
            return AddTimeResult("invalid")
        result = combine_pending_date(draft.target_date, text, now=now)
        if result.status != "complete" or result.due is None:
            if result.status == "past":
                await self._session.delete(draft)
                await self._session.flush()
            return AddTimeResult(result.status)
        await self._session.delete(draft)
        await self._session.flush()
        return await self._add_due(
            user_id, reminder_id, result.due, scheduler=scheduler, timezone=timezone
        )

    async def _add_due(
        self,
        user_id: int,
        reminder_id: int,
        due_at: datetime,
        *,
        scheduler: ReminderScheduler,
        timezone: str,
    ) -> AddTimeResult:
        existing = await self._session.scalar(
            select(AdditionalEvent).where(
                AdditionalEvent.user_id == user_id,
                AdditionalEvent.reminder_id == reminder_id,
                AdditionalEvent.due_at == due_at,
                AdditionalEvent.active.is_(True),
            )
        )
        events = await self.add_time_events(user_id, reminder_id, [due_at])
        draft = await self._draft(user_id, reminder_id)
        if draft is not None:
            await self._session.delete(draft)
            await self._session.flush()
        reminder = await self._owned(user_id, reminder_id)
        if reminder is None:
            return AddTimeResult("not_found")
        scheduler.register_extras(reminder, events, timezone)
        return AddTimeResult(
            "duplicate" if existing is not None else "added", due_at=due_at
        )


@dataclass(frozen=True, slots=True)
class AddTimeResult:
    status: str
    target_date: date | None = None
    due_at: datetime | None = None


@dataclass(slots=True)
class ItemMenuItem:
    reminder: Reminder
    kind: str
    status: str

    @property
    def id(self) -> int:
        return self.reminder.id

    @property
    def message(self) -> str:
        return self.reminder.message

    @property
    def schedule_spec(self) -> str:
        return self.reminder.schedule_spec

    @property
    def active(self) -> bool:
        return self.reminder.active


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
