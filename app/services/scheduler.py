"""Schedules primary and additional item alarms with defensive DB checks."""

from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database.base import Database
from app.database.models import AdditionalEvent, Reminder
from app.database.repository import ItemRepository, ReminderRepository, UserRepository
from app.nlp.recurrence import Schedule

logger = logging.getLogger(__name__)


def is_valid_timezone(timezone: str) -> bool:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


class ReminderScheduler:
    def __init__(self, bot: Bot, database: Database, default_tz: str) -> None:
        self._bot = bot
        self._db = database
        self._default_tz = default_tz
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self) -> None:
        self._scheduler.start()
        await self._reload_all()
        logger.info("Reminder scheduler started")

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    async def _reload_all(self) -> None:
        async with self._db.session() as session:
            reminders = await ReminderRepository(session).all()
            users = UserRepository(session)
            active_count = 0
            extra_count = 0
            for reminder in reminders:
                state = await ItemRepository(session).get_item_state(
                    reminder.user_id, reminder.id
                )
                if state and state.status in {"completed", "deleted"}:
                    continue
                if state and state.kind == "note":
                    continue
                user = await users.get_or_create(reminder.user_id, self._default_tz)
                if self.register(reminder, user.timezone):
                    active_count += 1
                events = await ItemRepository(session).extra_events(
                    reminder.user_id, reminder.id
                )
                self.register_extras(reminder, events, user.timezone)
                extra_count += len(events)
        logger.info(
            "Reloaded %d primary and %d additional alarms", active_count, extra_count
        )

    def register(self, reminder: Reminder, timezone: str):
        """Register a primary alarm; inactive/note rows are never scheduled."""
        if not reminder.active:
            return None
        return self._register(reminder, timezone)

    def _register(self, reminder: Reminder, timezone: str):
        schedule = Schedule.from_json(reminder.schedule_spec)
        try:
            trigger = schedule.to_trigger(timezone)
        except Exception:  # noqa: BLE001
            logger.exception("Bad trigger for reminder %s", reminder.id)
            return None
        return self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            id=f"rem:{reminder.id}",
            args=[reminder.id, reminder.user_id, reminder.message],
            replace_existing=True,
            misfire_grace_time=300,
        )

    def register_extras(
        self, reminder: Reminder, events: list[AdditionalEvent], timezone: str
    ) -> None:
        """Register durable extra events under the separate ``extra:`` namespace."""
        for event in events:
            if not event.active:
                continue
            try:
                self._scheduler.add_job(
                    self._fire_extra,
                    trigger="date",
                    run_date=event.due_at,
                    timezone=timezone,
                    id=f"extra:{event.id}",
                    args=[event.id, reminder.id, reminder.user_id, reminder.message],
                    replace_existing=True,
                    misfire_grace_time=300,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Bad extra trigger for event %s", event.id)

    register_extra_events = register_extras

    def cancel(self, reminder_id: int) -> None:
        job = self._scheduler.get_job(f"rem:{reminder_id}")
        if job:
            job.remove()

    def cancel_all(self, reminder_id: int) -> None:
        self.cancel(reminder_id)
        for job in self._scheduler.get_jobs():
            if job.id.startswith("extra:") and job.args[1] == reminder_id:
                job.remove()

    async def _current(self, user_id: int, reminder_id: int):
        async with self._db.session() as session:
            reminder = await ItemRepository(session)._owned(user_id, reminder_id)
            if reminder is None:
                return None
            state = await ItemRepository(session).get_item_state(user_id, reminder_id)
            return reminder, state

    async def _fire(self, reminder_id: int, user_id: int, message: str) -> None:
        current = await self._current(user_id, reminder_id)
        if current is None:
            self.cancel(reminder_id)
            return
        reminder, state = current
        if (
            not reminder.active
            or (state and state.status in {"completed", "deleted"})
            or (state and state.kind == "note")
        ):
            self.cancel(reminder_id)
            return
        try:
            await self._bot.send_message(
                user_id, f"🔔 <b>Reminder:</b> {html.escape(reminder.message)}"
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to deliver reminder %s", reminder_id)
        finally:
            # Recurring jobs own their next fire.  Only a one-off is consumed
            # by this callback, and even that is retired below after the DB
            # state has been checked.
            schedule = Schedule.from_json(reminder.schedule_spec)
            if schedule.kind == "once":
                self.cancel(reminder_id)

        async with self._db.session() as session:
            repo = ReminderRepository(session)
            current = await repo.get(reminder_id)
            current_state = await ItemRepository(session).get_item_state(
                user_id, reminder_id
            )
            if current and current.schedule_kind == "once":
                # ``active`` is the primary alarm flag, not the item status.
                # A delivered task remains pending but must not be scheduled
                # again after restart.
                if current_state is None or current_state.kind != "note":
                    await repo.deactivate(reminder_id)
                    await session.flush()
                    await ItemRepository(session).retire_if_idle(user_id, reminder_id)
                    await session.commit()

    async def _fire_extra(
        self, event_id: int, reminder_id: int, user_id: int, message: str
    ) -> None:
        async with self._db.session() as session:
            event = await session.get(AdditionalEvent, event_id)
            reminder = await ItemRepository(session)._owned(user_id, reminder_id)
            state = await ItemRepository(session).get_item_state(user_id, reminder_id)
            if (
                event is None
                or reminder is None
                or event.reminder_id != reminder_id
                or event.user_id != user_id
                or not event.active
                or (state and state.status in {"completed", "deleted"})
                or (state and state.kind == "note")
            ):
                self._remove_extra_job(event_id)
                return
            try:
                await self._bot.send_message(
                    user_id, f"🔔 <b>Reminder:</b> {html.escape(reminder.message)}"
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to deliver extra event %s", event_id)
            event.active = False
            event.fired_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            self._remove_extra_job(event_id)

            await ItemRepository(session).retire_if_idle(user_id, reminder_id)
            await session.commit()

    def _remove_extra_job(self, event_id: int) -> None:
        job = self._scheduler.get_job(f"extra:{event_id}")
        if job:
            job.remove()
