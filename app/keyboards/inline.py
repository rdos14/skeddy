"""Inline keyboards for the safe item menu and legacy reminder callbacks."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Reminder


class ReminderCB(CallbackData, prefix="rem"):
    action: str  # confirm | discard | delete (legacy-compatible)
    reminder_id: int


class ItemCB(CallbackData, prefix="item"):
    action: str
    item_id: int
    page: int = 0
    value: str = ""
    context: str = ""


def confirm_reminder(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Confirm",
            callback_data=ReminderCB(action="confirm", reminder_id=reminder_id).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 Cancel",
            callback_data=ReminderCB(action="discard", reminder_id=reminder_id).pack(),
        ),
    )
    return builder.as_markup()


def reminder_list(reminders: list[Reminder]) -> InlineKeyboardMarkup:
    """Legacy keyboard retained for old confirmation messages."""
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


def item_list_keyboard(
    items, *, page: int, pages: int, completed: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for number, item in enumerate(items, 1):
        builder.button(
            text=str(number),
            callback_data=ItemCB(
                action="open",
                item_id=item.id,
                page=page,
                value="completed" if completed else "",
            ).pack(),
        )
    builder.adjust(5)
    builder.row(
        InlineKeyboardButton(
            text="Back to active" if completed else "Show completed",
            callback_data=ItemCB(
                action="backactive" if completed else "completed",
                item_id=0,
                page=page,
            ).pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="<",
            callback_data=ItemCB(
                action="page",
                item_id=0,
                page=max(page - 1, 0),
                value="completed" if completed else "",
            ).pack(),
        ),
        InlineKeyboardButton(
            text=f"{page + 1}/{max(pages, 1)}",
            callback_data=ItemCB(
                action="page", item_id=0, page=page,
                value="completed" if completed else "",
            ).pack(),
        ),
        InlineKeyboardButton(
            text=">",
            callback_data=ItemCB(
                action="page",
                item_id=0,
                page=min(page + 1, max(pages - 1, 0)),
                value="completed" if completed else "",
            ).pack(),
        ),
    )
    return builder.as_markup()


def item_detail_keyboard(
    item, *, page: int = 0, completed: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    context = "completed" if completed else ""
    builder.row(
        InlineKeyboardButton(
            text="↩️ Reopen" if item.status == "completed" else "✅ Complete",
            callback_data=ItemCB(
                action="reopen" if item.status == "completed" else "complete",
                item_id=item.id,
                page=page,
                value=context,
            ).pack(),
        ),
        InlineKeyboardButton(
            text="➕ Add time",
            callback_data=ItemCB(
                action="addtime", item_id=item.id, page=page, value=context
            ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Change type",
            callback_data=ItemCB(
                action="type", item_id=item.id, page=page, value=context
            ).pack(),
        ),
        InlineKeyboardButton(
            text="🗑 Delete",
            callback_data=ItemCB(
                action="delete", item_id=item.id, page=page, value=context
            ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="↩️ Back to list",
            callback_data=ItemCB(
                action="back", item_id=0, page=page, value=context
            ).pack(),
        )
    )
    return builder.as_markup()


def delete_confirmation_keyboard(
    item_id: int, *, page: int = 0, completed: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Delete",
            callback_data=ItemCB(
                action="confirmdelete", item_id=item_id, page=page
                , value="completed" if completed else ""
            ).pack(),
        ),
        InlineKeyboardButton(
            text="Cancel",
            callback_data=ItemCB(
                action="canceldelete", item_id=item_id, page=page
                , value="completed" if completed else ""
            ).pack(),
        ),
    )
    return builder.as_markup()


def type_keyboard(
    item_id: int, *, page: int = 0, completed: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for value, label in (
        ("reminder", "Reminder"),
        ("task", "Task"),
        ("note", "Note"),
    ):
        builder.button(
            text=label,
            callback_data=ItemCB(
                action="settype",
                item_id=item_id,
                page=page,
                value=value,
                context="completed" if completed else "",
            ).pack(),
        )
    builder.button(
        text="Cancel",
        callback_data=ItemCB(
            action="back",
            item_id=item_id,
            page=page,
            value="completed" if completed else "",
        ).pack(),
    )
    builder.adjust(3, 1)
    return builder.as_markup()


def legacy_delete_confirmation(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Delete",
            callback_data=ReminderCB(
                action="confirmdelete", reminder_id=reminder_id
            ).pack(),
        ),
        InlineKeyboardButton(
            text="Cancel",
            callback_data=ReminderCB(
                action="canceldelete", reminder_id=reminder_id
            ).pack(),
        ),
    )
    return builder.as_markup()
