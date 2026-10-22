"""Phase-2 vertical slices: owner-scoped item menus and durable extra alarms."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.database.base import Database
from app.database.models import AdditionalEvent, Reminder
from app.database.repository import (
    ItemMenuItem,
    ItemRepository,
    ReminderRepository,
    UserRepository,
)
from app.handlers.reminders import create_reminder, delete_item
from app.keyboards.inline import item_detail_keyboard, item_list_keyboard
from app.nlp.recurrence import Schedule
from app.presentation import render_item_list
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 12, 0)


def _message(user_id=101):
    return SimpleNamespace(
        chat=SimpleNamespace(id=user_id),
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        edit_text=AsyncMock(),
    )


def test_list_state_is_explicit_and_legacy_inactive_is_not_completed(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "list.db"))
        await db.create_all()
        try:
            async with db.session() as session:
                session.add_all(
                    [
                        Reminder(
                            user_id=101,
                            message="legacy pending",
                            original_text="legacy pending",
                            human_readable="2026-10-22 09:00",
                            schedule_kind="once",
                            schedule_spec=Schedule(
                                kind="once", run_date=NOW + timedelta(days=1)
                            ).to_json(),
                            active=True,
                        ),
                        Reminder(
                            user_id=101,
                            message="legacy inactive",
                            original_text="legacy inactive",
                            human_readable="2026-10-20 09:00",
                            schedule_kind="once",
                            schedule_spec=Schedule(
                                kind="once", run_date=NOW - timedelta(days=1)
                            ).to_json(),
                            active=False,
                        ),
                    ]
                )
                await session.flush()
                new = await ReminderRepository(session).create(
                    user_id=101,
                    message="explicit done",
                    original_text="explicit done",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                await ItemRepository(session).complete(101, new.id)
                pending = await ItemRepository(session).list_items(101)
                completed = await ItemRepository(session).list_items(
                    101, completed=True
                )
                assert [item.message for item in pending] == ["legacy pending"]
                assert [item.message for item in completed] == ["explicit done"]
                assert all(item.status == "completed" for item in completed)
                await session.commit()
        finally:
            await db.dispose()

    asyncio.run(run())


def test_complete_cancels_primary_and_two_extra_jobs_and_stale_fire_is_safe(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "complete.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="<QA & title>",
                    original_text="payload",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                events = await ItemRepository(session).add_time_events(
                    101,
                    reminder.id,
                    [NOW + timedelta(days=2), NOW + timedelta(days=3)],
                )
                scheduler.register(reminder, "UTC")
                scheduler.register_extras(reminder, events, "UTC")
                assert len(scheduler._scheduler.get_jobs()) == 3
                await ItemRepository(session).complete(101, reminder.id)
                scheduler.cancel_all(reminder.id)
                await session.commit()
            assert scheduler._scheduler.get_jobs() == []
            await scheduler._fire(reminder.id, 101, reminder.message)
            await scheduler._fire_extra(
                events[0].id, reminder.id, 101, reminder.message
            )
            transport.send_message.assert_not_awaited()
            async with db.session() as session:
                state = await ItemRepository(session).get_item_state(101, reminder.id)
                assert state.status == "completed"
                assert (
                    await session.scalar(
                        select(AdditionalEvent).where(AdditionalEvent.active.is_(True))
                    )
                    is None
                )
        finally:
            await db.dispose()

    asyncio.run(run())


def test_add_time_preserves_primary_and_does_not_duplicate_item(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "add-time.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                primary_due = NOW + timedelta(days=1)
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task tomorrow 09:00",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=primary_due),
                )
                result = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "23/10/2026 10:30",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                assert result.status == "added"
                stored = await session.get(Reminder, reminder.id)
                assert Schedule.from_json(stored.schedule_spec).run_date == primary_due
                assert (
                    len(await ItemRepository(session).extra_events(101, reminder.id))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(Reminder.id).where(Reminder.user_id == 101)
                    )
                    == reminder.id
                )
                await session.commit()
        finally:
            await db.dispose()

    asyncio.run(run())


def test_add_time_invalid_text_creates_no_event(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "invalid-add-time.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                result = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "not a date",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                assert result.status == "invalid"
                assert (
                    await ItemRepository(session).extra_events(101, reminder.id) == []
                )
                assert scheduler._scheduler.get_jobs() == []
        finally:
            await db.dispose()

    asyncio.run(run())


def test_task_fire_stays_pending_and_note_has_no_jobs(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "types.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            async with db.session() as session:
                task = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                await ItemRepository(session).change_type(101, task.id, "task")
                scheduler.register(task, "UTC")
                await session.commit()
                await scheduler._fire(task.id, 101, "task")
                transport.send_message.assert_awaited_once()
                state = await ItemRepository(session).get_item_state(101, task.id)
                assert state.status == "pending"
                assert state.kind == "task"

                note = await ReminderRepository(session).create(
                    user_id=101,
                    message="note",
                    original_text="note",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                await ItemRepository(session).change_type(101, note.id, "note")
                assert scheduler.register(note, "UTC") is None
                assert not any(
                    job.id == f"rem:{note.id}"
                    for job in scheduler._scheduler.get_jobs()
                )
                await session.commit()
        finally:
            await db.dispose()

    asyncio.run(run())


def test_detail_and_list_keyboards_have_required_actions_and_escape_text():
    item = SimpleNamespace(
        id=7,
        message="<QA & title>",
        schedule_spec=Schedule(
            kind="once", run_date=datetime(2026, 10, 22, 9, 0)
        ).to_json(),
        kind="task",
        status="pending",
    )
    labels = [
        button.text
        for row in item_detail_keyboard(item).inline_keyboard
        for button in row
    ]
    assert labels == [
        "✅ Complete",
        "➕ Add time",
        "🔄 Change type",
        "🗑 Delete",
        "↩️ Back to list",
    ]
    list_markup = item_list_keyboard([item], page=0, pages=1)
    labels = [button.text for row in list_markup.inline_keyboard for button in row]
    assert labels[:3] == ["1", "Show completed", "<"]
    assert "<QA & title>" not in str(list_markup)


def test_repeated_add_time_is_idempotent(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "repeat.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                first = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "23/10/2026 10:30",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                second = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "23/10/2026 10:30",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                assert first.status == "added"
                assert second.status == "duplicate"
                assert (
                    len(await ItemRepository(session).extra_events(101, reminder.id))
                    == 1
                )
        finally:
            await db.dispose()

    asyncio.run(run())


def test_add_time_missing_clock_persists_date_without_event(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "missing-clock.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                result = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "23/10/2026",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                draft = await ItemRepository(session).get_menu_draft(101, now=NOW)
                assert result.status == "missing_time"
                assert (
                    draft is not None and draft.target_date.isoformat() == "2026-10-23"
                )
                assert (
                    await ItemRepository(session).extra_events(101, reminder.id) == []
                )
                await ItemRepository(session).delete_menu_drafts(101)
                assert await ItemRepository(session).get_menu_draft(101) is None
        finally:
            await db.dispose()

    asyncio.run(run())


def test_reload_rebuilds_two_extra_jobs_from_sqlite(tmp_path):
    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "reload.db")
        db = Database(url)
        await db.create_all()
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="restart",
                    original_text="restart",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                events = await ItemRepository(session).add_time_events(
                    101, reminder.id, [NOW + timedelta(days=2), NOW + timedelta(days=3)]
                )
                await session.commit()
            first = ReminderScheduler(
                SimpleNamespace(send_message=AsyncMock()), db, "UTC"
            )
            first.register_extras(reminder, events, "UTC")
            assert {job.id for job in first._scheduler.get_jobs()} == {
                f"extra:{events[0].id}",
                f"extra:{events[1].id}",
            }
            second = ReminderScheduler(
                SimpleNamespace(send_message=AsyncMock()), db, "UTC"
            )
            await second._reload_all()
            assert {job.id for job in second._scheduler.get_jobs()} == {
                f"rem:{reminder.id}",
                f"extra:{events[0].id}",
                f"extra:{events[1].id}",
            }
        finally:
            await db.dispose()

    asyncio.run(run())


def test_stale_delete_callback_opens_confirmation_not_deletes(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "stale.db"))
        await db.create_all()
        message = _message()
        try:
            async with db.session() as session:
                callback = SimpleNamespace(
                    from_user=SimpleNamespace(id=101),
                    message=message,
                    answer=AsyncMock(),
                )
                await delete_item(
                    callback,
                    999999,
                    ItemRepository(session),
                    ReminderScheduler(
                        SimpleNamespace(send_message=AsyncMock()), db, "UTC"
                    ),
                )
                assert "not found" in callback.answer.call_args.args[0].lower()
        finally:
            await db.dispose()

    asyncio.run(run())


def test_invalid_add_time_does_not_materialize_state_for_legacy_item(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "legacy-invalid.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                reminder = Reminder(
                    user_id=101,
                    message="legacy",
                    original_text="legacy",
                    human_readable="old ISO",
                    schedule_kind="once",
                    schedule_spec=Schedule(
                        kind="once", run_date=NOW + timedelta(days=1)
                    ).to_json(),
                    active=True,
                )
                session.add(reminder)
                await session.flush()
                result = await ItemRepository(session).add_time(
                    101,
                    reminder.id,
                    "garbage",
                    now=NOW,
                    scheduler=scheduler,
                    timezone="UTC",
                )
                assert result.status == "invalid"
                assert (
                    await ItemRepository(session).get_item_state(101, reminder.id)
                    is None
                )
                assert (
                    await ItemRepository(session).extra_events(101, reminder.id) == []
                )
        finally:
            await db.dispose()

    asyncio.run(run())


def test_large_escaped_list_is_bounded_without_cutting_html_entity():
    item = SimpleNamespace(
        id=1,
        message="<&> " * 80,
        schedule_spec=Schedule(kind="once", run_date=NOW + timedelta(days=1)).to_json(),
    )
    text = render_item_list([ItemMenuItem(item, kind="task", status="pending")])
    assert len(text) <= 4096
    assert "<&>" not in text
    assert text.count("&lt;") == text.count("&gt;")


def test_recurring_primary_survives_manual_fire(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "recurring.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="cron",
                    original_text="cron",
                    human_readable="Every day",
                    schedule=Schedule(kind="cron", cron={"hour": 9, "minute": 0}),
                )
                await session.commit()
            scheduler.register(reminder, "UTC")
            await scheduler._fire(reminder.id, 101, reminder.message)
            assert scheduler._scheduler.get_job(f"rem:{reminder.id}") is not None
            assert transport.send_message.await_count == 1
        finally:
            await db.dispose()

    asyncio.run(run())


def test_addtime_payload_is_not_a_new_alarm_or_item(tmp_path, monkeypatch):
    import app.handlers.reminders as handlers

    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)

    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "handler-repeat.db"))
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            async with db.session() as session:
                await UserRepository(session).get_or_create(101, "UTC")
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                items = ItemRepository(session)
                await items.begin_add_time(
                    101, reminder.id, expires_at=NOW + timedelta(hours=24)
                )
                await session.commit()
                message = SimpleNamespace(
                    chat=SimpleNamespace(id=101),
                    from_user=SimpleNamespace(id=101),
                    text="23/10/2026 10:30",
                    message_id=7001,
                    answer=AsyncMock(),
                )
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=items,
                )
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=items,
                )
                assert len((await session.scalars(select(Reminder))).all()) == 1
                assert len(await items.extra_events(101, reminder.id)) == 1
        finally:
            await db.dispose()

    asyncio.run(run())


def test_task_oneoff_is_not_rescheduled_after_restart(tmp_path):
    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "task-restart.db")
        db = Database(url)
        await db.create_all()
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            async with db.session() as session:
                reminder = await ReminderRepository(session).create(
                    user_id=101,
                    message="task",
                    original_text="task",
                    human_readable="At 22/10/2026 09:00",
                    schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
                )
                await ItemRepository(session).change_type(101, reminder.id, "task")
                await session.commit()
            scheduler.register(reminder, "UTC")
            await scheduler._fire(reminder.id, 101, reminder.message)
            restarted = ReminderScheduler(transport, db, "UTC")
            await restarted._reload_all()
            assert restarted._scheduler.get_job(f"rem:{reminder.id}") is None
            async with db.session() as session:
                state = await ItemRepository(session).get_item_state(101, reminder.id)
                assert state is not None
                assert state.status == "pending"
        finally:
            await db.dispose()

    asyncio.run(run())
