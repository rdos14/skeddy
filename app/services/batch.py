"""Persistence-safe preview and confirmation for numbered reminder pastes."""

from __future__ import annotations

import json
from datetime import datetime

from app.database.repository import (
    PendingBatchRepository,
    ReminderRepository,
    UserRepository,
)
from app.nlp.batch import BatchAnalysis
from app.nlp.recurrence import Schedule
from app.presentation import format_schedule
from app.services.scheduler import ReminderScheduler


def serialize_batch(batch: BatchAnalysis) -> str:
    """Store only anonymized parse results; raw input remains owner-scoped in DB."""
    return json.dumps(
        [
            {
                "number": item.number,
                "original_text": item.original_text,
                "status": item.status,
                "message": item.analysis.message,
                "due": item.analysis.due.isoformat() if item.analysis.due else None,
                "reason": item.analysis.reason,
            }
            for item in batch.items
        ],
        ensure_ascii=False,
    )


def preview_text(batch: BatchAnalysis) -> str:
    lines = []
    for item in batch.items:
        detail = item.analysis.reason or (
            item.analysis.due.strftime("%d/%m/%Y %H:%M") if item.analysis.due else ""
        )
        lines.append(f"{item.number}) {item.status}: {detail}")
    return (
        "<b>Batch preview</b>\n"
        + "\n".join(lines)
        + "\n\nConfirm with /confirm or cancel with /cancel."
    )


async def confirm_batch(
    *,
    user_id: int,
    pending_batches: PendingBatchRepository,
    users: UserRepository,
    reminders: ReminderRepository,
    scheduler: ReminderScheduler,
    default_tz: str,
    now: datetime,
):
    """Create only still-future complete items in one DB transaction."""
    batch = await pending_batches.get(user_id, now=now)
    if batch is None:
        return []
    session = getattr(reminders, "_session", None)
    created = []
    registered = []
    try:
        items = json.loads(batch.items_json)
        user = await users.get_or_create(user_id, default_tz)
        for item in items:
            if item.get("status") != "complete" or not item.get("due"):
                continue
            due = datetime.fromisoformat(item["due"])
            if due <= now:
                continue
            schedule = Schedule(kind="once", run_date=due)
            reminder = await reminders.create(
                user_id=user_id,
                message=item["message"],
                original_text=item["original_text"],
                human_readable=format_schedule(schedule),
                schedule=schedule,
            )
            created.append(reminder)
        await pending_batches.delete(user_id)
        # Register only after every row has been flushed successfully.
        for reminder in created:
            registered.append(reminder)
            scheduler.register(reminder, user.timezone)
    except Exception:
        if session is not None:
            await session.rollback()
        for reminder in registered:
            scheduler.cancel(reminder.id)
        raise
    return created
