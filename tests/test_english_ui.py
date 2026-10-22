"""English UI acceptance; real SQLite/repositories, Telegram I/O mocked only."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.filters import CommandObject

from app.database.base import Database
from app.database.models import Reminder
from app.database.repository import ReminderRepository, UserRepository
from app.handlers.reminders import cmd_list, create_reminder, delete_reminder
from app.handlers.start import HELP, WELCOME, cmd_help, cmd_start, cmd_timezone
from app.keyboards.inline import ReminderCB, confirm_reminder, reminder_list
from app.nlp import parse
from app.nlp.recurrence import Schedule
from app.services.scheduler import ReminderScheduler


def test_english_reminder_lifecycle(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "english.db"))
        await db.create_all()
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            text="",
            answer=AsyncMock(),
            edit_text=AsyncMock(),
        )
        transport = SimpleNamespace(send_message=AsyncMock())
        scheduler = ReminderScheduler(transport, db, "America/Mexico_City")
        try:
            async with db.session() as session:
                users = UserRepository(session)
                reminders = ReminderRepository(session)
                await cmd_start(message, users, "America/Mexico_City")
                assert "Hello" in message.answer.call_args.args[0]
                await cmd_help(message)
                assert "How" in message.answer.call_args.args[0]
                await cmd_timezone(
                    message,
                    CommandObject(command="timezone"),
                    users,
                    "America/Mexico_City",
                )
                assert "Current timezone" in message.answer.call_args.args[0]
                await cmd_timezone(
                    message,
                    CommandObject(command="timezone", args="Invalid/Zone"),
                    users,
                    "America/Mexico_City",
                )
                assert "Invalid timezone" in message.answer.call_args.args[0]
                await cmd_timezone(
                    message,
                    CommandObject(command="timezone", args="UTC"),
                    users,
                    "America/Mexico_City",
                )
                assert "Timezone set" in message.answer.call_args.args[0]
                await cmd_list(message, reminders)
                assert "no active reminders" in message.answer.call_args.args[0]
                message.text = "not a time"
                await create_reminder(message, users, reminders, scheduler, "UTC")
                assert "understand" in message.answer.call_args.args[0]
                message.text = "tomorrow at 09:00 check logs"
                await create_reminder(message, users, reminders, scheduler, "UTC")
                creation = message.answer.call_args.args[0]
                assert "Reminder added" in creation and "One-time" in creation
                assert "ertaga" not in creation
                items = await reminders.list_active(101)
                assert len(items) == 1
                # Existing rows display in English without rewriting stored text.
                items[0].human_readable = "ertaga 09:00 da"
                await session.commit()
                await cmd_list(message, reminders)
                listing = message.answer.call_args.args[0]
                assert "Active reminders" in listing and "ertaga" not in listing
                assert items[0].human_readable == "ertaga 09:00 da"
                reminder_id = items[0].id
            await scheduler._fire(reminder_id, 101, "Check logs")
            assert "Reminder:" in transport.send_message.call_args.args[1]
            async with db.session() as session:
                callback = SimpleNamespace(answer=AsyncMock(), message=message)
                await delete_reminder(
                    callback,
                    ReminderCB(action="delete", reminder_id=reminder_id),
                    ReminderRepository(session),
                    scheduler,
                )
                assert "Deleted" in callback.answer.call_args.args[0]
                assert "Reminder deleted" in message.edit_text.call_args.args[0]
                await session.commit()
            labels = [
                button.text
                for row in confirm_reminder(1).inline_keyboard
                for button in row
            ]
            assert labels == ["✅ Confirm", "🗑 Cancel"]
            empty = Reminder(id=1, message="")
            assert reminder_list([empty]).inline_keyboard[0][0].text == "🗑 Reminder"
        finally:
            await db.dispose()

    asyncio.run(run())


def test_schedule_presentation_is_english_without_changing_schedule():
    now = datetime(2026, 9, 26, 12, 0)
    cases = [
        (
            "in 2 hours call mom",
            Schedule(kind="once", run_date=datetime(2026, 9, 26, 14, 0)),
        ),
        (
            "every monday at 18:30 water plants",
            Schedule(
                kind="cron", cron={"day_of_week": "mon", "hour": 18, "minute": 30}
            ),
        ),
        ("every 15 min stretch", Schedule(kind="interval", interval={"minutes": 15})),
    ]
    for text, expected in cases:
        parsed = parse(text, now=now)
        assert parsed is not None
        assert parsed.schedule.to_json() == expected.to_json()
        assert any(word in parsed.human_readable for word in ("At", "Every"))
        assert not any(
            word in parsed.human_readable for word in ("har ", "keyin", " da")
        )
    empty = parse("in 1 min", now=now)
    assert empty is not None
    assert empty.message == "Reminder"


def test_help_describes_supported_spanish_and_explicit_time_requirement():
    message = SimpleNamespace(answer=AsyncMock())
    asyncio.run(cmd_help(message))
    help_text = message.answer.call_args.args[0]
    assert "mañana a las 10am" in help_text
    assert "próximo sábado" in help_text
    assert "explicit time" in help_text
    assert "Spanish parsing are not available" not in help_text
    assert len(help_text) <= 4096


def test_help_and_welcome_use_toddy_and_do_not_advertise_retired_language():
    for text in (WELCOME, HELP):
        assert "Toddy" in text
        assert "Skeddy" not in text
        assert "Uzbek" not in text


def test_retired_uzbek_task_is_rejected_without_creating_a_row(tmp_path):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "uzbek-rejection.db"))
        await db.create_all()
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202),
            text="t ertaga payload",
            answer=AsyncMock(),
        )
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        try:
            async with db.session() as session:
                users = UserRepository(session)
                reminders = ReminderRepository(session)
                await create_reminder(message, users, reminders, scheduler, "UTC")
                assert "No reminder was created" in message.answer.call_args.args[0]
                assert await reminders.list_active(202) == []
                assert scheduler._scheduler.get_jobs() == []
        finally:
            await db.dispose()

    asyncio.run(run())
