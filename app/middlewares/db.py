"""Middleware that opens one DB session per update and injects repositories."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database.base import Database
from app.database.repository import (
    PendingBatchRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, database: Database, default_tz: str) -> None:
        self._db = database
        self._default_tz = default_tz

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._db.session() as session:
            data["session"] = session
            data["users"] = UserRepository(session)
            data["reminders"] = ReminderRepository(session)
            data["pending"] = PendingDraftRepository(session)
            data["pending_batches"] = PendingBatchRepository(session)
            data["default_tz"] = self._default_tz
            result = await handler(event, data)
            await session.commit()
            return result
