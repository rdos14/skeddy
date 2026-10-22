"""Reminder creation plus the owner-scoped item list/detail menus."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.database.repository import (
    ItemMenuItem,
    ItemRepository,
    PendingBatchRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.keyboards.inline import (
    ItemCB,
    ReminderCB,
    delete_confirmation_keyboard,
    item_detail_keyboard,
    item_list_keyboard,
    legacy_delete_confirmation,
    type_keyboard,
)
from app.nlp import (
    analyze_batch,
    analyze_datetime,
    combine_pending_date,
    has_datetime_intent,
    is_batch_input,
    parse,
)
from app.nlp.item_intent import (
    has_explicit_time,
    has_timing_intent,
    item_kind_for,
    task_body,
)
from app.nlp.recurrence import Schedule
from app.presentation import (
    format_schedule,
    render_item_detail,
    render_item_list,
    visual_text,
)
from app.services.batch import confirm_batch, preview_text, serialize_batch
from app.services.scheduler import ReminderScheduler

router = Router(name="reminders")
PAGE_SIZE = 10
_CONSUMED_MENU_INPUTS: dict[tuple[int, int], datetime] = {}


async def _user_id(callback: CallbackQuery) -> int:
    if callback.from_user is not None:
        return callback.from_user.id
    return callback.message.chat.id


async def _list_text_and_markup(
    items: ItemRepository, user_id: int, *, page: int, completed: bool = False
):
    total = await items.count_items(user_id, completed=completed)
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = max(0, min(page, pages - 1))
    rows = await items.list_items(
        user_id, completed=completed, offset=page * PAGE_SIZE, limit=PAGE_SIZE
    )
    if not rows:
        return (
            "You have no completed items."
            if completed
            else "You have no active reminders.",
            item_list_keyboard([], page=page, pages=1, completed=completed),
        )
    return render_item_list(rows, completed=completed), item_list_keyboard(
        rows, page=page, pages=pages, completed=completed
    )


async def _owned_item(items: ItemRepository, user_id: int, item_id: int):
    reminder = await items._owned(user_id, item_id)
    if reminder is None:
        return None
    state = await items.get_item_state(user_id, item_id)
    if state is None:
        if not reminder.active:
            return None
        return ItemMenuItem(reminder, kind="reminder", status="pending")
    if state.status == "deleted":
        return None
    return ItemMenuItem(reminder, kind=state.kind, status=state.status)


async def _edit_detail(
    callback: CallbackQuery,
    items: ItemRepository,
    user_id: int,
    item_id: int,
    page: int,
    *,
    completed: bool = False,
):
    item = await _owned_item(items, user_id, item_id)
    if item is None:
        await callback.answer("Item not found or not yours.")
        return False
    extras = await items.extra_events(user_id, item_id)
    extra_times = [event.due_at.strftime("%d/%m/%Y %H:%M") for event in extras]
    await callback.message.edit_text(
        render_item_detail(item, extra_times),
        reply_markup=item_detail_keyboard(item, page=page, completed=completed),
    )
    return True


def _local_now(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)


async def _commit(items: ItemRepository) -> None:
    await items._session.commit()


async def _show_list_after(
    callback: CallbackQuery,
    items: ItemRepository,
    user_id: int,
    page: int,
    *,
    completed: bool = False,
) -> None:
    text, markup = await _list_text_and_markup(
        items, user_id, page=page, completed=completed
    )
    await callback.message.edit_text(text, reply_markup=markup)


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    pending: PendingDraftRepository | None = None,
    pending_batches: PendingBatchRepository | None = None,
    items: ItemRepository | None = None,
) -> None:
    if pending is not None:
        await pending.delete(message.chat.id)
    if pending_batches is not None:
        await pending_batches.delete(message.chat.id)
    if items is not None:
        await items.delete_menu_drafts(message.chat.id)
    await message.answer("Pending input cancelled. No reminder or alarm was created.")


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
async def cmd_list(
    message: Message,
    reminders: ReminderRepository,
    items: ItemRepository | None = None,
) -> None:
    items = items or ItemRepository(reminders._session)
    text, markup = await _list_text_and_markup(items, message.chat.id, page=0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(ItemCB.filter(F.action == "page"))
async def list_page(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    text, markup = await _list_text_and_markup(
        items,
        user_id,
        page=callback_data.page,
        completed=callback_data.value == "completed",
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(ItemCB.filter(F.action == "completed"))
async def show_completed(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    text, markup = await _list_text_and_markup(
        items, user_id, page=callback_data.page, completed=True
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(ItemCB.filter(F.action == "backactive"))
async def back_to_active(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    text, markup = await _list_text_and_markup(
        items, user_id, page=callback_data.page, completed=False
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(ItemCB.filter(F.action == "open"))
async def show_item_detail(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    found = await _edit_detail(
        callback,
        items,
        user_id,
        callback_data.item_id,
        callback_data.page,
        completed=callback_data.value == "completed",
    )
    if found:
        await callback.answer()


@router.callback_query(ItemCB.filter(F.action == "back"))
async def back_to_list(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    completed = callback_data.value == "completed"
    text, markup = await _list_text_and_markup(
        items, user_id, page=callback_data.page, completed=completed
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(ItemCB.filter(F.action == "complete"))
async def complete_item(
    callback: CallbackQuery,
    callback_data: ItemCB,
    items: ItemRepository,
    scheduler: ReminderScheduler,
):
    user_id = await _user_id(callback)
    state = await items.complete(user_id, callback_data.item_id, scheduler=scheduler)
    if state is None:
        await callback.answer("Item not found or not yours.")
        return
    if state.status == "completed":
        await callback.answer("Item is already completed.")
        await _show_list_after(
            callback,
            items,
            user_id,
            callback_data.page,
            completed=callback_data.value == "completed",
        )
        return
    await _commit(items)
    scheduler.cancel_all(callback_data.item_id)
    await callback.answer("Completed ✅")
    await _show_list_after(
        callback,
        items,
        user_id,
        callback_data.page,
        completed=callback_data.value == "completed",
    )


@router.callback_query(ItemCB.filter(F.action == "reopen"))
async def reopen_item(
    callback: CallbackQuery,
    callback_data: ItemCB,
    items: ItemRepository,
):
    user_id = await _user_id(callback)
    state = await items.reopen(user_id, callback_data.item_id)
    if state is None:
        await callback.answer("Item not found, deleted, or already open.")
        return
    await _commit(items)
    await callback.answer("Reopened. Add a new time if needed.")
    await _edit_detail(
        callback,
        items,
        user_id,
        callback_data.item_id,
        callback_data.page,
        completed=callback_data.value == "completed",
    )


@router.callback_query(ItemCB.filter(F.action == "delete"))
async def delete_item(
    callback: CallbackQuery,
    item_id: int | None = None,
    items: ItemRepository | None = None,
    scheduler: ReminderScheduler | None = None,
    callback_data: ItemCB | None = None,
):
    """Show confirmation; this callback never deletes directly."""
    if callback_data is not None:
        item_id = callback_data.item_id
        page = callback_data.page
    else:
        page = 0
    if item_id is None or items is None:
        await callback.answer("Item not found or not yours.")
        return
    user_id = await _user_id(callback)
    item = await _owned_item(items, user_id, item_id)
    if item is None:
        await callback.answer("Item not found or not yours.")
        return
    await callback.answer()
    await callback.message.edit_text(
        f"Delete <b>{visual_text(item.message)}</b>? "
        "This cannot be undone from the menu.",
        reply_markup=delete_confirmation_keyboard(
            item_id, page=page, completed=item.status == "completed"
        ),
    )


@router.callback_query(ItemCB.filter(F.action == "confirmdelete"))
async def confirm_delete_item(
    callback: CallbackQuery,
    callback_data: ItemCB,
    items: ItemRepository,
    scheduler: ReminderScheduler,
):
    user_id = await _user_id(callback)
    state = await items.delete(user_id, callback_data.item_id, scheduler=scheduler)
    if state is None:
        await callback.answer("Item not found or not yours.")
        return
    if state.status == "deleted":
        await callback.answer("Item was already deleted.")
        await _show_list_after(
            callback,
            items,
            user_id,
            callback_data.page,
            completed=callback_data.value == "completed",
        )
        return
    await _commit(items)
    scheduler.cancel_all(callback_data.item_id)
    await callback.answer("Deleted ✅")
    await _show_list_after(
        callback,
        items,
        user_id,
        callback_data.page,
        completed=callback_data.value == "completed",
    )


@router.callback_query(ItemCB.filter(F.action == "canceldelete"))
async def cancel_delete_item(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    found = await _edit_detail(
        callback,
        items,
        user_id,
        callback_data.item_id,
        callback_data.page,
        completed=callback_data.value == "completed",
    )
    await callback.answer(
        "Delete cancelled." if found else "Item not found or not yours."
    )


@router.callback_query(ItemCB.filter(F.action == "type"))
async def change_item_type(
    callback: CallbackQuery, callback_data: ItemCB, items: ItemRepository
):
    user_id = await _user_id(callback)
    if await _owned_item(items, user_id, callback_data.item_id) is None:
        await callback.answer("Item not found or not yours.")
        return
    await callback.answer()
    await callback.message.edit_text(
        "Choose the item type:",
        reply_markup=type_keyboard(
            callback_data.item_id,
            page=callback_data.page,
            completed=callback_data.value == "completed",
        ),
    )


@router.callback_query(ItemCB.filter(F.action == "settype"))
async def set_item_type(
    callback: CallbackQuery,
    callback_data: ItemCB,
    items: ItemRepository,
    scheduler: ReminderScheduler,
    users: UserRepository | None = None,
    default_tz: str = "UTC",
):
    user_id = await _user_id(callback)
    if callback_data.value not in items.VALID_KINDS:
        await callback.answer("Invalid item type.")
        return
    state = await items.change_type(user_id, callback_data.item_id, callback_data.value)
    if state is None:
        await callback.answer("Item not found or not yours.")
        return
    if callback_data.value == "note":
        await _commit(items)
        scheduler.cancel_all(callback_data.item_id)
        message = "Type changed to Note. All notifications are cancelled."
    else:
        reminder = await items._owned(user_id, callback_data.item_id)
        if reminder is not None:
            timezone = default_tz
            if users is not None:
                user = await users.get(user_id)
                if user is not None:
                    timezone = user.timezone
            await _commit(items)
            if reminder.active:
                scheduler.register(reminder, timezone)
        message = f"Type changed to {callback_data.value.title()}."
    await callback.answer(message)
    await _edit_detail(
        callback,
        items,
        user_id,
        callback_data.item_id,
        callback_data.page,
        completed=callback_data.context == "completed",
    )


@router.callback_query(ItemCB.filter(F.action == "addtime"))
async def add_time_item(
    callback: CallbackQuery,
    callback_data: ItemCB,
    items: ItemRepository,
    users: UserRepository | None = None,
    default_tz: str = "UTC",
):
    user_id = await _user_id(callback)
    timezone = default_tz
    if users is not None:
        user = await users.get(user_id)
        if user is not None:
            timezone = user.timezone
    result = await items.begin_add_time(
        user_id,
        callback_data.item_id,
        expires_at=_local_now(timezone) + timedelta(hours=24),
    )
    await callback.answer()
    prompts = {
        "awaiting_input": (
            "Send a date and time as <code>DD/MM/YYYY HH:MM</code>. "
            "You may send a date first; I will ask for the clock."
        ),
        "note_requires_type": (
            "Change the Note to Reminder or Task first; a Note has no alarms."
        ),
        "reopen_required": "Reopen this completed item before adding time.",
        "not_found": "Item not found or not yours.",
    }
    await callback.message.answer(
        prompts.get(result.status, "No alarm was added."),
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Cancel")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.callback_query(ReminderCB.filter(F.action == "delete"))
async def delete_reminder(
    callback: CallbackQuery,
    callback_data: ReminderCB,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
):
    """Compatibility handler for old keyboards, scoped to the callback owner."""
    user = getattr(callback, "from_user", None)
    user_id = user.id if user is not None else callback.message.chat.id
    reminder = await reminders.get(callback_data.reminder_id)
    if reminder is None or reminder.user_id != user_id:
        await callback.answer("Item not found or not yours.")
        return
    await callback.answer("Deleted? Confirmation required.")
    await callback.message.edit_text(
        f"Reminder deleted? Confirm to remove <b>{visual_text(reminder.message)}</b>.",
        reply_markup=legacy_delete_confirmation(reminder.id),
    )


@router.callback_query(ReminderCB.filter(F.action == "confirmdelete"))
async def confirm_delete_reminder(
    callback: CallbackQuery,
    callback_data: ReminderCB,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
):
    user_id = await _user_id(callback)
    reminder = await reminders.get(callback_data.reminder_id)
    if reminder is None or reminder.user_id != user_id:
        await callback.answer("Item not found or not yours.")
        return
    items = ItemRepository(reminders._session)
    state = await items.delete(user_id, reminder.id)
    if state is None:
        await callback.answer("Item not found or not yours.")
        return
    await reminders._session.commit()
    scheduler.cancel_all(reminder.id)
    await callback.answer("Deleted ✅")
    await callback.message.edit_text("🗑 Reminder deleted.")


@router.callback_query(ReminderCB.filter(F.action == "canceldelete"))
async def cancel_delete_reminder(
    callback: CallbackQuery,
    callback_data: ReminderCB,
    reminders: ReminderRepository,
):
    user_id = await _user_id(callback)
    reminder = await reminders.get(callback_data.reminder_id)
    if reminder is None or reminder.user_id != user_id:
        await callback.answer("Item not found or not yours.")
        return
    await callback.answer("Delete cancelled.")
    await callback.message.edit_text("Delete cancelled.")


@router.message(F.text & ~F.text.startswith("/"))
async def create_reminder(
    message: Message,
    users: UserRepository,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
    default_tz: str,
    pending: PendingDraftRepository | None = None,
    pending_batches: PendingBatchRepository | None = None,
    items: ItemRepository | None = None,
) -> None:
    if message.text.strip().casefold() == "cancel":
        if pending is not None:
            await pending.delete(message.chat.id)
        if pending_batches is not None:
            await pending_batches.delete(message.chat.id)
        if items is not None:
            await items.delete_menu_drafts(message.chat.id)
        await message.answer(
            "Pending input cancelled. No reminder or alarm was created."
        )
        return
    owner = await users.get(message.chat.id)
    now = _local_now(owner.timezone if owner is not None else default_tz)
    message_id = getattr(message, "message_id", None)
    if (
        items is not None
        and message_id is not None
        and await items.menu_input_consumed(message.chat.id, message_id)
    ):
        await message.answer(
            "This input was already processed; no new reminder was created."
        )
        return
    if message_id is not None:
        cutoff = now - timedelta(hours=24)
        for key, seen_at in list(_CONSUMED_MENU_INPUTS.items()):
            if seen_at <= cutoff:
                _CONSUMED_MENU_INPUTS.pop(key, None)
    if items is not None:
        menu_draft = await items.get_menu_draft(message.chat.id, now=now)
        if menu_draft is not None:
            menu_timezone = owner.timezone if owner is not None else default_tz
            if menu_draft.target_date is None:
                result = await items.add_time(
                    message.chat.id,
                    menu_draft.reminder_id,
                    message.text,
                    now=now,
                    scheduler=scheduler,
                    timezone=menu_timezone,
                )
            else:
                result = await items.add_time_clock(
                    message.chat.id,
                    menu_draft.reminder_id,
                    message.text,
                    now=now,
                    scheduler=scheduler,
                    timezone=menu_timezone,
                )
            if result.status == "missing_time":
                await message.answer(
                    f"I recognized {result.target_date:%d/%m/%Y}. "
                    "Send one clock such as <code>9:00 AM</code>, or /cancel."
                )
            elif result.status == "added":
                if message_id is not None:
                    await items.record_menu_input(message.chat.id, message_id)
                await _commit(items)
                reminder = await items._owned(message.chat.id, menu_draft.reminder_id)
                if reminder is not None:
                    events = await items.extra_events(
                        message.chat.id, menu_draft.reminder_id
                    )
                    scheduler.register_extras(reminder, events, menu_timezone)
                if message_id is not None:
                    _CONSUMED_MENU_INPUTS[(message.chat.id, message_id)] = now
                await message.answer(
                    f"✅ Alarm added to this item at "
                    f"{result.due_at:%d/%m/%Y %H:%M}. "
                    "The original alarm was preserved."
                )
            elif result.status == "duplicate":
                if message_id is not None:
                    await items.record_menu_input(message.chat.id, message_id)
                await _commit(items)
                reminder = await items._owned(message.chat.id, menu_draft.reminder_id)
                if reminder is not None:
                    events = await items.extra_events(
                        message.chat.id, menu_draft.reminder_id
                    )
                    scheduler.register_extras(reminder, events, menu_timezone)
                if message_id is not None:
                    _CONSUMED_MENU_INPUTS[(message.chat.id, message_id)] = now
                await message.answer(
                    "That alarm is already present; no duplicate was created."
                )
            elif result.status == "note_requires_type":
                await message.answer(
                    "Change the Note to Reminder or Task first; no alarm was created."
                )
            else:
                await message.answer(
                    "No alarm was added. Use DD/MM/YYYY HH:MM or /cancel."
                )
            return

    if (
        message_id is not None
        and (
            message.chat.id,
            message_id,
        )
        in _CONSUMED_MENU_INPUTS
    ):
        await message.answer(
            "This input was already processed; no new reminder was created."
        )
        return

    # A numbered paste is a new batch, not a clock reply for an older draft.
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
                item_kind=item_kind_for(draft.original_text),
            )
            await pending.delete(message.chat.id)
            scheduler.register(reminder, user.timezone)
            await message.answer(
                f"✅ <b>{item_kind_for(draft.original_text).title()} added!</b>\n\n"
                f"📝 {visual_text(draft.message)}\n"
                f"🕒 {format_schedule(schedule)}\n1️⃣ One-time · 🌍 {user.timezone}"
            )
            return

    requested_kind = item_kind_for(message.text)
    body = task_body(message.text)
    if requested_kind == "task" and body and not has_timing_intent(body):
        user = await users.get_or_create(message.chat.id, default_tz)
        title = body[:1].upper() + body[1:]
        await reminders.create(
            user_id=message.chat.id,
            message=title,
            original_text=message.text,
            human_readable="No active alarm",
            schedule=Schedule(kind="once"),
            item_kind="task",
        )
        await message.answer(
            f"✅ <b>Task added!</b>\n\n📝 {visual_text(title)}\n"
            "No alarm scheduled. It stays pending until Complete."
        )
        return

    date_analysis = None
    if has_datetime_intent(body):
        date_analysis = analyze_datetime(body, now=now)
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
                "What clock should I use? Send <code>9:00 AM</code>, "
                "or /cancel."
            )
            return
    if (
        requested_kind == "task"
        and date_analysis is None
        and has_timing_intent(body)
        and not has_explicit_time(body)
    ):
        await message.answer(
            "Please resend the task with an explicit clock "
            "for that date or recurrence. "
            "No task or alarm was created; I will not choose a default hour."
        )
        return
    parsed = (
        parse(body, now=now)
        if date_analysis is not None or requested_kind == "task"
        else parse(body)
    )
    if parsed is None:
        if date_analysis is not None and date_analysis.status == "past":
            await message.answer(
                "That English/Spanish date is in the past. No reminder was created."
            )
            return
        if date_analysis is not None and date_analysis.status == "invalid":
            await message.answer(
                "I couldn't safely parse that English/Spanish date or clock. "
                "No reminder was created."
            )
            return
        await message.answer(
            "🤔 I couldn't safely understand the time. No reminder was created.\n\n"
            "Try:\n• <i>in one minute test</i>\n"
            "• <i>tomorrow at 09:00 call the dentist</i>\n"
            "• <i>every monday at 10:00 send the report</i>\n\nUse /help for examples."
        )
        return

    user = await users.get_or_create(message.chat.id, default_tz)
    reminder = await reminders.create(
        user_id=message.chat.id,
        message=parsed.message,
        original_text=message.text,
        human_readable=parsed.human_readable,
        schedule=parsed.schedule,
        item_kind=requested_kind,
    )
    scheduler.register(reminder, user.timezone)
    kind_label = "🔁 Recurring" if parsed.schedule.is_recurring else "1️⃣ One-time"
    await message.answer(
        f"✅ <b>{requested_kind.title()} added!</b>\n\n"
        f"📝 {visual_text(parsed.message)}\n"
        f"🕒 {parsed.human_readable}\n{kind_label} · 🌍 {user.timezone}"
    )
