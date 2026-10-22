"""Bounded HTML-safe presentation for list and item menus."""

from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING

from app.nlp.recurrence import Schedule

if TYPE_CHECKING:
    from app.database.repository import ItemMenuItem

WEEKDAYS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
MAX_MESSAGE = 4096


def format_schedule(schedule: Schedule) -> str:
    """Render persisted and newly parsed schedules without re-parsing input."""
    if schedule.kind == "once" and schedule.run_date is not None:
        return f"At {schedule.run_date:%d/%m/%Y %H:%M}"
    if schedule.kind == "interval":
        units = []
        for unit, amount in schedule.interval.items():
            label = unit.removesuffix("s") if amount == 1 else unit
            units.append(f"{amount} {label}")
        return "Every " + ", ".join(units)
    if schedule.kind == "cron":
        cron = schedule.cron
        minute = int(cron.get("minute", 0))
        if "hour" not in cron:
            return f"Every hour at minute {minute:02d}"
        time = f"{int(cron['hour']):02d}:{minute:02d}"
        weekday = WEEKDAYS.get(
            str(cron.get("day_of_week")), str(cron.get("day_of_week", ""))
        )
        if "day" in cron:
            return f"Every month: {weekday}, days {cron['day']}, at {time}"
        if weekday:
            return f"Every {weekday} at {time}"
        return f"Every day at {time}"
    raise ValueError("Unsupported reminder schedule")


def visual_text(value: str, limit: int = 240) -> str:
    """Truncate raw user text before escaping so HTML entities stay intact."""
    value = value if len(value) <= limit else value[: limit - 1] + "…"
    return html.escape(value, quote=False)


def item_schedule(item: ItemMenuItem) -> str:
    next_extra = getattr(item, "next_extra_at", None)
    if next_extra is not None and not getattr(item, "active", True):
        return f"Additional alarm: {next_extra:%d/%m/%Y %H:%M}"
    if (
        getattr(item, "kind", "reminder") == "note"
        or getattr(item, "status", "pending") in {"completed", "retired"}
        or not getattr(item, "active", True)
    ):
        return "No active alarm"
    try:
        schedule = Schedule.from_json(item.schedule_spec)
        return format_schedule(schedule)
    except (ValueError, KeyError, TypeError):
        return "No active alarm"


def _bounded_lines(lines: list[str], limit: int = MAX_MESSAGE) -> str:
    result: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + (1 if result else 0)
        if size + extra > limit:
            break
        result.append(line)
        size += extra
    return "\n".join(result)


def render_item_list(items: list[ItemMenuItem], *, completed: bool = False) -> str:
    heading = "<b>Completed items:</b>" if completed else "<b>Active reminders:</b>"
    lines = [heading, "", "Choose a number to open"]
    for number, item in enumerate(items, 1):
        title = visual_text(item.message, limit=60)
        schedule = html.escape(item_schedule(item), quote=False)
        lines.append(f"<b>{number}.</b> {title} · 🕒 {schedule}")
    return _bounded_lines(lines)


def render_item_detail(item: ItemMenuItem, extra_times: list[str] | None = None) -> str:
    title = visual_text(item.message)
    schedule_text = item_schedule(item)
    lines = [
        f"<b>{title}</b>",
        f"Type: {html.escape(item.kind)}",
        f"Status: {html.escape(item.status)}",
        f"Scheduled: {html.escape(schedule_text, quote=False)}",
    ]
    if item.kind != "note":
        try:
            original_schedule = Schedule.from_json(item.schedule_spec)
            if (
                original_schedule.kind == "once"
                and original_schedule.run_date is not None
            ):
                lines.append(f"Deadline: {original_schedule.run_date:%d/%m/%Y %H:%M}")
        except (ValueError, KeyError, TypeError):
            pass
    if item.kind == "note":
        lines.append("Alarm: None (Note)")
    else:
        try:
            schedule = Schedule.from_json(item.schedule_spec)
            if schedule.kind == "once" and schedule.run_date is not None:
                if schedule.run_date <= datetime.now():
                    lines.append("Alarm: No active alarm")
        except (ValueError, KeyError, TypeError):
            lines.append("Alarm: No active alarm")
    if extra_times:
        lines.append(
            "Additional times: "
            + ", ".join(html.escape(value) for value in extra_times[:8])
            + (f" (+{len(extra_times) - 8} more)" if len(extra_times) > 8 else "")
        )
    return _bounded_lines(lines)
