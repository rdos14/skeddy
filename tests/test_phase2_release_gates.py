"""Final release gates: lifecycle, legacy delete and durable input replay."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import ItemRepository, ReminderRepository, UserRepository
from app.handlers import reminders as handlers
from app.keyboards.inline import ReminderCB
from app.nlp.recurrence import Schedule
from app.presentation import render_item_detail, render_item_list
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 18)


async def seed(db):
    await db.create_all()
    async with db.session() as session:
        await UserRepository(session).get_or_create(101, "UTC")
        reminder = await ReminderRepository(session).create(
            user_id=101,
            message="Payload",
            original_text="Payload",
            human_readable="test",
            schedule=Schedule(kind="once", run_date=NOW + timedelta(days=1)),
        )
        await session.commit()
        return reminder


def test_plain_reminder_retires_without_manual_completion(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "plain.db"))
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            reminder = await seed(db)
            scheduler.register(reminder, "UTC")
            await scheduler._fire(reminder.id, 101, reminder.message)
            assert transport.send_message.await_count == 1
            async with db.session() as session:
                items = ItemRepository(session)
                assert not await items.list_items(101)
                assert not await items.list_items(101, completed=True)
                assert (
                    await items.get_item_state(101, reminder.id)
                ).status == "retired"
        finally:
            await db.dispose()

    asyncio.run(run())


def test_extra_keeps_item_pending_until_last_alarm_then_retires(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "last-extra.db"))
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        try:
            reminder = await seed(db)
            async with db.session() as session:
                extras = await ItemRepository(session).add_time_events(
                    101, reminder.id, [NOW + timedelta(days=2)]
                )
                await session.commit()
            scheduler.register(reminder, "UTC")
            scheduler.register_extras(reminder, extras, "UTC")
            await scheduler._fire(reminder.id, 101, reminder.message)
            async with db.session() as session:
                assert len(await ItemRepository(session).list_items(101)) == 1
            await scheduler._fire_extra(
                extras[0].id, reminder.id, 101, reminder.message
            )
            assert transport.send_message.await_count == 2
            async with db.session() as session:
                assert not await ItemRepository(session).list_items(101)
                assert not await ItemRepository(session).list_items(101, completed=True)
        finally:
            await db.dispose()

    asyncio.run(run())


def test_legacy_delete_confirmation_disables_durable_extra_events(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "legacy-delete.db"))
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            reminder = await seed(db)
            async with db.session() as session:
                await ItemRepository(session).add_time_events(
                    101, reminder.id, [NOW + timedelta(days=2)]
                )
                await session.commit()
            callback = SimpleNamespace(
                from_user=SimpleNamespace(id=101),
                answer=AsyncMock(),
                message=SimpleNamespace(
                    chat=SimpleNamespace(id=101), edit_text=AsyncMock()
                ),
            )
            async with db.session() as session:
                await handlers.confirm_delete_reminder(
                    callback,
                    ReminderCB(action="confirmdelete", reminder_id=reminder.id),
                    ReminderRepository(session),
                    scheduler,
                )
            fresh = ReminderScheduler(
                SimpleNamespace(send_message=AsyncMock()), db, "UTC"
            )
            await fresh._reload_all()
            assert not fresh._scheduler.get_jobs()
            async with db.session() as session:
                assert not await ItemRepository(session).extra_events(101, reminder.id)
                assert (
                    await ItemRepository(session).get_item_state(101, reminder.id)
                ).status == "deleted"
        finally:
            await db.dispose()

    asyncio.run(run())


def test_consumed_menu_input_does_not_create_reminder_after_process_restart(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(handlers, "_local_now", lambda timezone: NOW)
    monkeypatch.setattr(handlers, "_CONSUMED_MENU_INPUTS", {})

    async def run():
        url = "sqlite+aiosqlite:///" + str(tmp_path / "replay.db")
        db = Database(url)
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "UTC")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            message_id=501,
            text="27/10/2026 9am",
            answer=AsyncMock(),
        )
        try:
            reminder = await seed(db)
            async with db.session() as session:
                await ItemRepository(session).begin_add_time(
                    101, reminder.id, expires_at=NOW + timedelta(hours=24)
                )
                await session.commit()
            async with db.session() as session:
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=ItemRepository(session),
                )
                await session.commit()
            await db.dispose()
            handlers._CONSUMED_MENU_INPUTS.clear()
            db = Database(url)
            async with db.session() as session:
                await handlers.create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    items=ItemRepository(session),
                )
                await session.commit()
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 1
                )
                assert (
                    len(await ItemRepository(session).extra_events(101, reminder.id))
                    == 1
                )
        finally:
            await db.dispose()

    asyncio.run(run())


def test_detail_preserves_deadline_when_primary_alarm_is_inactive():
    item = SimpleNamespace(
        message="Payload",
        kind="task",
        status="pending",
        active=False,
        schedule_spec=Schedule(kind="once", run_date=NOW + timedelta(days=1)).to_json(),
    )
    text = render_item_detail(item)
    assert "22/10/2026 18:00" in text
    assert "No active alarm" in text


def test_list_shows_additional_alarm_after_primary_is_inactive(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "visible-extra.db"))
        try:
            reminder = await seed(db)
            async with db.session() as session:
                stored = await ReminderRepository(session).get(reminder.id)
                stored.active = False
                items = ItemRepository(session)
                await items.add_time_events(101, reminder.id, [NOW + timedelta(days=2)])
                await session.commit()
                rows = await items.list_items(101)
                assert len(rows) == 1
                assert "23/10/2026 18:00" in render_item_list(rows)
        finally:
            await db.dispose()

    asyncio.run(run())
