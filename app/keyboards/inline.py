"""Inline keyboards and callback factories."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Reminder


class ReminderCB(CallbackData, prefix="rem"):
    action: str  # confirm | discard | delete
    reminder_id: int


def confirm_reminder(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Confirm",
            callback_data=ReminderCB(
                action="confirm", reminder_id=reminder_id
            ).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 Cancel",
            callback_data=ReminderCB(
                action="discard", reminder_id=reminder_id
            ).pack(),
        ),
    )
    return builder.as_markup()


def reminder_list(reminders: list[Reminder]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for reminder in reminders:
        label = reminder.message[:30] or "Reminder"
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {label}",
                callback_data=ReminderCB(
                    action="delete", reminder_id=reminder.id
                ).pack(),
            )
        )
    return builder.as_markup()
