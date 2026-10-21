"""Natural-language reminder parser (Uzbek + English, bounded Spanish).

Turns free-form text such as::

    "Har oyning birinchi dushanbasida ertalab soat 9 da serverni tekshir"
    "remind me every monday at 18:30 to water the plants"
    "in 30 minutes call mom"

into a :class:`ParsedReminder` carrying a clean message and a
:class:`~app.nlp.recurrence.Schedule` the scheduler can act on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.nlp import patterns as P
from app.nlp.dates import (
    analyze_datetime,
    has_datetime_intent,
    has_recurrence_intent,
    has_unsupported_clock,
)
from app.nlp.recurrence import Schedule, nth_weekday_cron
from app.nlp.spanish import has_spanish_timing, parse_spanish
from app.presentation import format_schedule


@dataclass(slots=True)
class ParsedReminder:
    message: str
    schedule: Schedule
    human_readable: str


class _Spans:
    """Tracks character ranges already consumed by temporal tokens."""

    def __init__(self, text: str) -> None:
        self._chars = list(text)
        self._consumed = [False] * len(text)

    def consume(self, start: int, end: int) -> None:
        for i in range(start, min(end, len(self._consumed))):
            self._consumed[i] = True

    def remainder(self) -> str:
        return "".join(
            ch
            for ch, used in zip(self._chars, self._consumed, strict=False)
            if not used
        )


def parse(text: str, *, now: datetime | None = None) -> ParsedReminder | None:
    now = now or datetime.now()
    original = text.strip()
    if has_unsupported_clock(original):
        return None
    # Recurrence grammar owns its weekday/time tokens.  Do not let the
    # one-off date analyzer reinterpret a recurring request as a single run.
    if has_datetime_intent(original) and not has_recurrence_intent(original):
        analysis = analyze_datetime(original, now=now)
        if not analysis.complete or analysis.due is None:
            return None
        schedule = Schedule(kind="once", run_date=analysis.due)
        return ParsedReminder(analysis.message, schedule, format_schedule(schedule))
    if has_spanish_timing(original):
        try:
            result = parse_spanish(original, now)
        except (ValueError, OverflowError):
            return None
        if result is None:
            return None
        message, due = result
        schedule = Schedule(kind="once", run_date=due)
        return ParsedReminder(message, schedule, format_schedule(schedule))
    low = original.lower()
    spans = _Spans(original)

    if P.UNSUPPORTED_PREFIX_RE.search(low):
        return None
    try:
        hour, minute, period_used = _extract_time(low, spans)
        schedule, _summary = _extract_schedule(low, spans, now, hour, minute)
    except (ValueError, OverflowError):
        return None
    if schedule is None:
        return None
    if P.UNCONSUMED_TEMPORAL_RE.search(spans.remainder()):
        return None

    message = _clean_message(spans.remainder())
    if not message:
        message = "Reminder"

    return ParsedReminder(
        message=message, schedule=schedule, human_readable=format_schedule(schedule)
    )


# --- time-of-day -----------------------------------------------------------


def _extract_time(low: str, spans: _Spans) -> tuple[int | None, int | None, bool]:
    """Return (hour, minute, period_default_used)."""
    pm_hint = any(w in low for w in P.PM_HINTS)
    am_hint = any(w in low for w in P.AM_HINTS)

    for match in P.TIME_RE.finditer(low):
        token = match.group(0).strip()
        has_marker = (
            "soat" in token
            or token.startswith("at ")
            or ":" in token
            or match.group("ampm")
            or token.endswith("da")
        )
        if not has_marker:
            continue
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        ampm = (match.group("ampm") or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif not ampm and pm_hint and not am_hint and hour < 12:
            hour += 12
        spans.consume(match.start(), match.end())
        return hour, minute, False

    # No explicit time — fall back to a day-period default word.
    for word, default_hour in P.DAY_PERIODS.items():
        idx = low.find(word)
        if idx != -1:
            spans.consume(idx, idx + len(word))
            return default_hour, 0, True

    return None, None, False


# --- schedule --------------------------------------------------------------


def _extract_schedule(
    low: str,
    spans: _Spans,
    now: datetime,
    hour: int | None,
    minute: int | None,
) -> tuple[Schedule | None, str]:
    default_hour = hour if hour is not None else 9
    default_minute = minute if minute is not None else 0

    # 1) "every N <unit>"  -> interval
    m = P.INTERVAL_RE.search(low)
    if m:
        spans.consume(m.start(), m.end())
        amount = int(m.group("amount"))
        if amount <= 0:
            return None, ""
        unit = P.UNITS[m.group("unit").lower()]
        return (
            Schedule(kind="interval", interval={unit: amount}),
            f"har {amount} {_unit_uz(unit)}da",
        )

    # 2) "Nth <weekday> of every month" -> monthly cron
    m = P.NTH_WEEKDAY_RE.search(low)
    if m and (
        any(w in low for w in P.MONTHLY_WORDS + ("oy", "month"))
        or re.search(r"\b(?:every|each|har)\b", low)
    ):
        spans.consume(m.start(), m.end())
        nth = P.ORDINALS[m.group("ord").lower()]
        for context in P.MONTHLY_CONTEXT_RE.finditer(low):
            spans.consume(context.start(), context.end())
        for context in re.finditer(r"\b(?:every|each|har)\b", low):
            spans.consume(context.start(), context.end())
        wd = P.WEEKDAYS[m.group("wd").lower()]
        cron = nth_weekday_cron(nth, P.CRON_DOW[wd], default_hour, default_minute)
        ord_uz = "oxirgi" if nth == -1 else f"{nth}-"
        return (
            Schedule(kind="cron", cron=cron),
            f"har oyning {ord_uz} {_weekday_uz(wd)}sida "
            f"{default_hour:02d}:{default_minute:02d} da",
        )

    # 3) hourly
    if any(w in low for w in P.HOURLY_WORDS):
        for w in P.HOURLY_WORDS:
            i = low.find(w)
            if i != -1:
                spans.consume(i, i + len(w))
        return (
            Schedule(kind="cron", cron={"minute": default_minute}),
            "har soatda",
        )

    # 4) daily
    if any(w in low for w in P.DAILY_WORDS):
        for w in P.DAILY_WORDS:
            i = low.find(w)
            if i != -1:
                spans.consume(i, i + len(w))
        return (
            Schedule(
                kind="cron", cron={"hour": default_hour, "minute": default_minute}
            ),
            f"har kuni {default_hour:02d}:{default_minute:02d} da",
        )

    # 5) weekly on a specific weekday ("har dushanba" / "every monday")
    has_every = any(w in low for w in P.EVERY_WORDS) or any(
        w in low for w in P.WEEKLY_WORDS
    )
    wm = P.WEEKDAY_RE.search(low)
    if wm and has_every:
        spans.consume(wm.start(), wm.end())
        wd = P.WEEKDAYS[wm.group("wd").lower()]
        for w in P.EVERY_WORDS:
            i = low.find(w)
            if i != -1:
                spans.consume(i, i + len(w))
        cron = {
            "day_of_week": P.CRON_DOW[wd],
            "hour": default_hour,
            "minute": default_minute,
        }
        return (
            Schedule(kind="cron", cron=cron),
            f"har {_weekday_uz(wd)} {default_hour:02d}:{default_minute:02d} da",
        )

    # 6) explicit date (checked before relative times so that a date like
    #    "27.09" isn't misread as "09 soat" = 9 hours)
    dm = P.DATE_RE.search(low)
    if dm:
        if hour is None:
            return None, ""
        spans.consume(dm.start(), dm.end())
        if dm.group("y"):
            y, mo, d = int(dm.group("y")), int(dm.group("m")), int(dm.group("d"))
        else:
            d, mo = int(dm.group("d2")), int(dm.group("m2"))
            y = int(dm.group("y2")) if dm.group("y2") else now.year
        run_date = now.replace(
            year=y,
            month=mo,
            day=d,
            hour=default_hour,
            minute=default_minute,
            second=0,
            microsecond=0,
        )
        if run_date <= now:
            return None, ""
        return (
            Schedule(kind="once", run_date=run_date),
            f"{run_date:%Y-%m-%d %H:%M} da",
        )

    # 7) relative one-off: "in 30 minutes", "2 soatdan keyin"
    m = P.RELATIVE_RE.search(low)
    if m:
        if hour is not None:
            return None, ""
        spans.consume(m.start(), m.end())
        raw_amount = m.group("amount").lower()
        amount = 1 if raw_amount == "one" else int(raw_amount)
        if amount <= 0:
            return None, ""
        unit = P.UNITS[m.group("unit").lower()]
        run_date = now + timedelta(**{unit: amount})
        for pattern, offset in P.DAY_CONTEXTS:
            for context in pattern.finditer(low):
                if run_date.date() != (now + timedelta(days=offset)).date():
                    return None, ""
                spans.consume(context.start(), context.end())
        return (
            Schedule(kind="once", run_date=run_date),
            f"{amount} {_unit_uz(unit)}dan keyin ({run_date:%Y-%m-%d %H:%M})",
        )

    # 8) tomorrow / today (+ time)
    if any(w in low for w in P.TOMORROW_WORDS):
        if hour is None:
            return None, ""
        for w in P.TOMORROW_WORDS:
            i = low.find(w)
            if i != -1:
                spans.consume(i, i + len(w))
        base = now + timedelta(days=1)
        run_date = base.replace(
            hour=default_hour, minute=default_minute, second=0, microsecond=0
        )
        return (
            Schedule(kind="once", run_date=run_date),
            f"ertaga {default_hour:02d}:{default_minute:02d} da",
        )

    if any(w in low for w in P.TODAY_WORDS) or hour is not None:
        explicit_today = any(
            pattern.search(low) for pattern, offset in P.DAY_CONTEXTS if offset == 0
        )
        if hour is None:
            return None, ""
        run_date = now.replace(
            hour=default_hour, minute=default_minute, second=0, microsecond=0
        )
        if run_date <= now:
            if explicit_today:
                return None, ""
            run_date += timedelta(days=1)
        for w in P.TODAY_WORDS:
            i = low.find(w)
            if i != -1:
                spans.consume(i, i + len(w))
        return (
            Schedule(kind="once", run_date=run_date),
            f"{run_date:%Y-%m-%d %H:%M} da",
        )

    return None, ""


# --- helpers ---------------------------------------------------------------


def _clean_message(raw: str) -> str:
    words = [w for w in raw.replace(",", " ").split() if w]
    kept = [w for w in words if w.lower().strip(".,!?:") not in P.FILLER_WORDS]
    message = " ".join(kept).strip(" .,-—:")
    return message[:1].upper() + message[1:] if message else ""


def _weekday_uz(wd: int) -> str:
    names = [
        "dushanba",
        "seshanba",
        "chorshanba",
        "payshanba",
        "juma",
        "shanba",
        "yakshanba",
    ]
    return names[wd]


def _unit_uz(unit: str) -> str:
    return {
        "minutes": "daqiqa",
        "hours": "soat",
        "days": "kun",
        "weeks": "hafta",
    }[unit]
