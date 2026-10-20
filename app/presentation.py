"""English display text; never change the underlying reminder schedule."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.nlp.recurrence import Schedule

WEEKDAYS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def format_schedule(schedule: Schedule) -> str:
    """Render persisted and newly parsed schedules without re-parsing user input."""
    if schedule.kind == "once" and schedule.run_date is not None:
        return f"At {schedule.run_date:%Y-%m-%d %H:%M}"
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
