"""Free-text reminder creation, listing and deletion."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.database.repository import ReminderRepository, UserRepository
from app.keyboards.inline import ReminderCB, reminder_list
from app.nlp import parse
from app.nlp.recurrence import Schedule
from app.presentation import format_schedule
from app.services.scheduler import ReminderScheduler

router = Router(name="reminders")


@router.message(Command("list"))
async def cmd_list(message: Message, reminders: ReminderRepository) -> None:
    items = await reminders.list_active(message.chat.id)
    if not items:
        await message.answer("You have no active reminders.")
        return
    lines = [
        f"• <b>{r.message}</b>\n"
        f"  🕒 {format_schedule(Schedule.from_json(r.schedule_spec))}"
        for r in items
    ]
    await message.answer(
        "<b>Active reminders:</b>\n\n" + "\n\n".join(lines),
        reply_markup=reminder_list(items),
    )


@router.callback_query(ReminderCB.filter(F.action == "delete"))
async def delete_reminder(
    callback: CallbackQuery,
    callback_data: ReminderCB,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
) -> None:
    await reminders.deactivate(callback_data.reminder_id)
    scheduler.cancel(callback_data.reminder_id)
    await callback.answer("Deleted ✅")
    await callback.message.edit_text("🗑 Reminder deleted.")


@router.message(F.text & ~F.text.startswith("/"))
async def create_reminder(
    message: Message,
    users: UserRepository,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
    default_tz: str,
) -> None:
    parsed = parse(message.text)
    if parsed is None:
        await message.answer(
            "🤔 I couldn't understand the time. Try:\n"
            "• <i>tomorrow at 09:00 call the dentist</i>\n"
            "• <i>every monday at 10:00 send the report</i>\n\n"
            "More examples: /help"
        )
        return

    user = await users.get_or_create(message.chat.id, default_tz)
    reminder = await reminders.create(
        user_id=message.chat.id,
        message=parsed.message,
        original_text=message.text,
        human_readable=parsed.human_readable,
        schedule=parsed.schedule,
    )
    # The scheduler captures message/ids as job args, so it needs no DB read
    # to fire; the middleware commits the row when this handler returns.
    scheduler.register(reminder, user.timezone)

    kind_label = (
        "🔁 Recurring"
        if parsed.schedule.is_recurring
        else "1️⃣ One-time"
    )
    await message.answer(
        f"✅ <b>Reminder added!</b>\n\n"
        f"📝 {parsed.message}\n"
        f"🕒 {parsed.human_readable}\n"
        f"{kind_label} · 🌍 {user.timezone}"
    )
