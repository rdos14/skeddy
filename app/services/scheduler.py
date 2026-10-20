"""Schedules reminders with APScheduler and delivers notifications.

Reminders are persisted, so on startup every active reminder is reloaded
and re-registered — nothing is lost across restarts.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import ReminderRepository, UserRepository
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
            reminders = await ReminderRepository(session).all_active()
            users = UserRepository(session)
            for reminder in reminders:
                user = await users.get_or_create(
                    reminder.user_id, self._default_tz
                )
                self._register(reminder, user.timezone)
        logger.info("Reloaded %d active reminders", len(reminders))

    def register(self, reminder: Reminder, timezone: str) -> None:
        """Public entry point used by handlers for freshly created reminders."""
        self._register(reminder, timezone)

    def _register(self, reminder: Reminder, timezone: str) -> None:
        schedule = Schedule.from_json(reminder.schedule_spec)
        try:
            trigger = schedule.to_trigger(timezone)
        except Exception:  # noqa: BLE001
            logger.exception("Bad trigger for reminder %s", reminder.id)
            return
        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            id=f"rem:{reminder.id}",
            args=[reminder.id, reminder.user_id, reminder.message],
            replace_existing=True,
            misfire_grace_time=300,
        )

    def cancel(self, reminder_id: int) -> None:
        job = self._scheduler.get_job(f"rem:{reminder_id}")
        if job:
            job.remove()

    async def _fire(self, reminder_id: int, user_id: int, message: str) -> None:
        try:
            await self._bot.send_message(
                user_id, f"🔔 <b>Reminder:</b> {message}"
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to deliver reminder %s", reminder_id)

        # One-off reminders are retired after firing.
        async with self._db.session() as session:
            repo = ReminderRepository(session)
            reminder = await repo.get(reminder_id)
            if reminder and reminder.schedule_kind == "once":
                await repo.deactivate(reminder_id)
                await session.commit()
                self.cancel(reminder_id)
