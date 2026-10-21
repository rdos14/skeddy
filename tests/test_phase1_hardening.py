"""Regression tests for phase-1 fail-closed parser routing."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.base import Database
from app.database.models import PendingBatch, Reminder
from app.database.repository import (
    PendingBatchRepository,
    PendingDraftRepository,
    ReminderRepository,
    UserRepository,
)
from app.handlers.reminders import create_reminder
from app.nlp import (
    analyze_batch,
    analyze_datetime,
    combine_pending_date,
    has_datetime_intent,
    has_unsupported_clock,
    parse,
)
from app.services.batch import confirm_batch, serialize_batch
from app.services.scheduler import ReminderScheduler

NOW = datetime(2026, 10, 21, 16, 49)


@pytest.mark.parametrize("day", ["tomorrow", "mañana"])
def test_numeric_date_rejects_a_second_relative_day(day):
    text = f"payload {day} 27/10/2026 at 9am"
    assert analyze_datetime(text, now=NOW).status == "invalid"
    assert parse(text, now=NOW) is None


@pytest.mark.parametrize(
    "text",
    [
        "payload Friday at 8.5am",
        "payload Friday at +9am",
        "payload Friday at 9 y media",
    ],
)
def test_partial_signed_or_unsupported_clock_is_rejected(text):
    assert analyze_datetime(text, now=NOW).status == "invalid"
    assert parse(text, now=NOW) is None


def test_recurrence_is_not_routed_to_one_off_date_analyzer():
    assert not has_datetime_intent("every first Monday at 9am")
    assert analyze_datetime("every Monday payload", now=NOW).status == "invalid"
    result = parse("every first Monday at 9am payload", now=NOW)
    assert result is not None
    assert result.schedule.kind == "cron"
    assert result.schedule.cron == {
        "day": "1-7",
        "day_of_week": "mon",
        "hour": 9,
        "minute": 0,
    }


@pytest.mark.parametrize(
    "text", ["every Monday at 8.5am payload", "every Monday at +9am payload"]
)
def test_legacy_recurrence_also_rejects_partial_clocks(text):
    assert has_unsupported_clock(text)
    assert parse(text, now=NOW) is None


def test_pending_date_accepts_only_the_new_clock():
    complete = combine_pending_date(date(2026, 10, 27), "at 9:00 AM", now=NOW)
    assert complete.status == "complete"
    assert complete.due == datetime(2026, 10, 27, 9)
    for text in ("tomorrow at 9am", "28/10/2026 at 9am", "9am extra"):
        assert (
            combine_pending_date(date(2026, 10, 27), text, now=NOW).status == "invalid"
        )


def test_datetime_message_preserves_payload_punctuation():
    result = parse("payload (QA, alpha) 27/10/2026 9am", now=NOW)
    assert result is not None
    assert result.message == "Payload (QA, alpha)"


@pytest.mark.parametrize("text", ["payload 05/06-27 at 9am", "payload 05-06/27 at 9am"])
def test_numeric_date_rejects_mixed_separators(text):
    assert analyze_datetime(text, now=NOW).status == "invalid"
    assert parse(text, now=NOW) is None


def test_handler_keeps_draft_when_reply_contains_a_new_date(tmp_path, monkeypatch):
    async def run():
        import app.handlers.reminders as handler_module

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        monkeypatch.setattr(handler_module, "datetime", FrozenDatetime)
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "pending-extra.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            text="payload next Tuesday",
            answer=AsyncMock(),
        )
        try:
            async with db.session() as session:
                pending = PendingDraftRepository(session)
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending,
                )
                message.text = "tomorrow at 9am"
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending,
                )
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                assert await pending.get(101, now=NOW) is not None
        finally:
            await db.dispose()

    asyncio.run(run())


def test_handler_routes_batch_away_from_existing_draft(tmp_path, monkeypatch):
    async def run():
        import app.handlers.reminders as handler_module

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        monkeypatch.setattr(handler_module, "datetime", FrozenDatetime)
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "pending-batch.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=101),
            text="payload next Tuesday",
            answer=AsyncMock(),
        )
        batch_text = "1) payload Saturday at 9am\n2) payload Sunday at 9am"
        try:
            async with db.session() as session:
                pending = PendingDraftRepository(session)
                batches = PendingBatchRepository(session)
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending,
                    batches,
                )
                message.text = batch_text
                await create_reminder(
                    message,
                    UserRepository(session),
                    ReminderRepository(session),
                    scheduler,
                    "UTC",
                    pending,
                    batches,
                )
                assert await pending.get(101, now=NOW) is not None
                assert await session.scalar(
                    select(PendingBatch).where(PendingBatch.user_id == 101)
                )
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
        finally:
            await db.dispose()

    asyncio.run(run())


def test_batch_db_failure_rolls_back_rows_and_keeps_jobs_empty(tmp_path, monkeypatch):
    async def run():
        db = Database("sqlite+aiosqlite:///" + str(tmp_path / "batch-rollback.db"))
        await db.create_all()
        scheduler = ReminderScheduler(
            SimpleNamespace(send_message=AsyncMock()), db, "UTC"
        )
        text = "1) payload Saturday at 9am\n2) payload Sunday at 9am"
        try:
            async with db.session() as session:
                batches = PendingBatchRepository(session)
                await batches.upsert(
                    user_id=101,
                    original_text=text,
                    items_json=serialize_batch(analyze_batch(text, now=NOW)),
                    expires_at=datetime(2026, 10, 22),
                )
                await session.commit()

            original_create = ReminderRepository.create
            calls = 0

            async def fail_second_create(self, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("simulated database failure")
                return await original_create(self, **kwargs)

            monkeypatch.setattr(ReminderRepository, "create", fail_second_create)
            async with db.session() as session:
                with pytest.raises(RuntimeError):
                    await confirm_batch(
                        user_id=101,
                        pending_batches=PendingBatchRepository(session),
                        users=UserRepository(session),
                        reminders=ReminderRepository(session),
                        scheduler=scheduler,
                        default_tz="UTC",
                        now=NOW,
                    )
                assert (
                    await session.scalar(select(func.count()).select_from(Reminder))
                    == 0
                )
                assert await session.scalar(
                    select(PendingBatch).where(PendingBatch.user_id == 101)
                )
            assert scheduler._scheduler.get_jobs() == []
        finally:
            await db.dispose()

    asyncio.run(run())
