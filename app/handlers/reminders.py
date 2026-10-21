"""Free-text reminder creation, listing and deletion."""

from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.database.repository import (
    PendingBatchRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.keyboards.inline import ReminderCB, reminder_list
from app.nlp import (
    analyze_batch,
    analyze_datetime,
    combine_pending_date,
    has_datetime_intent,
    is_batch_input,
    parse,
)
from app.nlp.recurrence import Schedule
from app.presentation import format_schedule
from app.services.batch import confirm_batch, preview_text, serialize_batch
from app.services.scheduler import ReminderScheduler

router = Router(name="reminders")


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    pending: PendingDraftRepository | None = None,
    pending_batches: PendingBatchRepository | None = None,
) -> None:
    if pending is not None:
        await pending.delete(message.chat.id)
    if pending_batches is not None:
        await pending_batches.delete(message.chat.id)
    await message.answer("Pending date cancelled. No reminder was created.")


@router.message(Command("confirm"))
async def cmd_confirm(
    message: Message,
    users: UserRepository,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
    default_tz: str,
    pending_batches: PendingBatchRepository | None = None,
) -> None:
    if pending_batches is None:
        await message.answer("There is no batch preview to confirm.")
        return
    created = await confirm_batch(
        user_id=message.chat.id,
        pending_batches=pending_batches,
        users=users,
        reminders=reminders,
        scheduler=scheduler,
        default_tz=default_tz,
        now=datetime.now(),
    )
    await message.answer(f"✅ Confirmed {len(created)} future reminder(s).")


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
    pending: PendingDraftRepository | None = None,
    pending_batches: PendingBatchRepository | None = None,
) -> None:
    now = datetime.now()
    if pending is not None:
        draft = await pending.get(message.chat.id, now=now)
        if draft is not None:
            completed = combine_pending_date(draft.target_date, message.text, now=now)
            if completed.status != "complete" or completed.due is None:
                if completed.status == "past":
                    await pending.delete(message.chat.id)
                    reply = (
                        "That saved date is now in the past; no reminder was created."
                    )
                else:
                    reply = (
                        "Please send one clock such as <code>9:00 AM</code>, "
                        "or /cancel."
                    )
                await message.answer(reply)
                return
            user = await users.get_or_create(message.chat.id, default_tz)
            schedule = Schedule(kind="once", run_date=completed.due)
            reminder = await reminders.create(
                user_id=message.chat.id,
                message=draft.message,
                original_text=draft.original_text,
                human_readable=format_schedule(schedule),
                schedule=schedule,
            )
            await pending.delete(message.chat.id)
            scheduler.register(reminder, user.timezone)
            await message.answer(
                f"✅ <b>Reminder added!</b>\n\n📝 {draft.message}\n"
                f"🕒 {format_schedule(schedule)}\n1️⃣ One-time · 🌍 {user.timezone}"
            )
            return

    if pending_batches is not None and is_batch_input(message.text):
        batch = analyze_batch(message.text, now=now)
        await pending_batches.upsert(
            user_id=message.chat.id,
            original_text=message.text,
            items_json=serialize_batch(batch),
            expires_at=now + timedelta(hours=24),
        )
        await message.answer(preview_text(batch))
        return

    date_analysis = analyze_datetime(message.text, now=now)
    if date_analysis.status == "missing_time" and date_analysis.target_date:
        if pending is not None:
            await pending.upsert(
                user_id=message.chat.id,
                original_text=message.text,
                message=date_analysis.message,
                target_date=date_analysis.target_date,
                expires_at=now + timedelta(hours=24),
            )
        await message.answer(
            f"I recognized {date_analysis.target_date:%d/%m/%Y}. "
            "What clock should I use? Send <code>9:00 AM</code>, or /cancel."
        )
        return
    parsed = parse(message.text)
    if parsed is None:
        if has_datetime_intent(message.text) and date_analysis.status == "past":
            await message.answer(
                "That English/Spanish date is in the past. No reminder was created."
            )
            return
        if has_datetime_intent(message.text) and date_analysis.status == "invalid":
            await message.answer(
                "I couldn't safely parse that English/Spanish date or clock. "
                "No reminder was created."
            )
            return
        await message.answer(
            "🤔 I couldn't safely understand the time. No reminder was created.\n\n"
            "Try:\n"
            "• <i>in one minute test</i>\n"
            "• <i>tomorrow at 09:00 call the dentist</i>\n"
            "• <i>every monday at 10:00 send the report</i>\n\n"
            "Use a supported English/Spanish date with an explicit clock.\n"
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

    kind_label = "🔁 Recurring" if parsed.schedule.is_recurring else "1️⃣ One-time"
    await message.answer(
        f"✅ <b>Reminder added!</b>\n\n"
        f"📝 {parsed.message}\n"
        f"🕒 {parsed.human_readable}\n"
        f"{kind_label} · 🌍 {user.timezone}"
    )
