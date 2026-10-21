"""Bounded Spanish one-off dates, isolated from legacy English/Uzbek grammar."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.nlp import patterns as P

_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sábado": 5,
    "sabado": 5,
    "domingo": 6,
}
_WEEKDAY = re.compile(
    r"\b(?P<prefix>(?:(?:para|el|este)\s+)*)"
    r"(?:(?P<next>pr[oó]xim[oa])\s+)?"
    rf"(?P<weekday>{'|'.join(_WEEKDAYS)})\b"
    r"(?:\s+(?P<suffix>pr[oó]xim[oa]))?",
    re.I,
)
_RELATIVE = re.compile(r"\b(?:(?:para|el)\s+)*(?P<day>hoy|mañana|manana)\b", re.I)
_MONTHS: dict[str, int] = dict(
    zip(
        (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        range(1, 13),
        strict=True,
    )
)
_MONTHS["setiembre"] = 9
_CALENDAR = re.compile(
    r"\b(?:para\s+)?(?:el\s+)?(?P<day>\d{1,2})\s+de\s+"
    rf"(?P<month>{'|'.join(_MONTHS)})\b(?:\s+(?:de|del)\s+(?P<year>\d{{4}})\b)?",
    re.I,
)
_NUMERIC_DATE = re.compile(
    r"(?<![\w./-])(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}(?:\.\d{4})?)(?![\w./-])"
)
_CLOCK = re.compile(
    r"(?<![\w:.])(?P<prefix>a\s+las?\s+)?"
    r"(?P<clock>\d{1,4}(?::\d{2})?)\s*(?P<ampm>[ap]\s*\.?\s*m\.?)?(?!\w|:\d|\.\d)",
    re.I,
)
_UNSUPPORTED = re.compile(
    r"\b(?:cada|diariamente|semanalmente|mensualmente|anualmente)\b"
    r"|\b(?:todos|todas)\s+(?:los|las)\b"
    r"|\b(?:y|menos)\s+(?:media|cuarto|\d{1,2})\b"
    r"|\b(?:de|por|en)\s+la\s+(?:mañana|manana|tarde|noche|madrugada)\b",
    re.I,
)
_LEFTOVER_MERIDIEM = re.compile(r"\b[ap]\s*\.?\s*m\b", re.I)
_PREFIX = re.compile(
    r"^(?:(?:recu[eé]rdame|recordarme|recordatorio)(?:\s+(?:de|que))?"
    r"|contenido\s+del\s+recordatorio)\b[\s:,.—-]*",
    re.I,
)


def has_spanish_timing(text: str) -> bool:
    return bool(
        _RELATIVE.search(text) or _WEEKDAY.search(text) or _CALENDAR.search(text)
    )


def _clean(raw: str) -> str:
    text = " ".join(raw.split()).strip(" .,:;—-")
    while True:
        new = _PREFIX.sub("", text).strip(" .,:;—-")
        if new == text:
            break
        text = new
    return text[:1].upper() + text[1:] if text else "Reminder"


def parse_spanish(text: str, now: datetime) -> tuple[str, datetime] | None:
    if _UNSUPPORTED.search(text):
        return None
    chars = list(text)

    def consume(match):
        chars[match.start() : match.end()] = " " * (match.end() - match.start())

    clocks = [
        m
        for m in _CLOCK.finditer(text)
        if m["prefix"] or m["ampm"] or ":" in m["clock"]
    ]
    if len(clocks) != 1:
        return None
    clock = clocks[0]
    if clock.start() and text[clock.start() - 1] in "+-":
        return None
    raw_clock = clock["clock"]
    if ":" in raw_clock:
        h, minute = raw_clock.split(":")
    elif len(raw_clock) in (3, 4):
        h, minute = raw_clock[:-2], raw_clock[-2:]
    else:
        h, minute = raw_clock, "0"
    hour, minute = int(h), int(minute)
    ampm = re.sub(r"[\s.]", "", clock["ampm"] or "").lower()
    if hour > 23 or minute > 59 or (ampm and not 1 <= hour <= 12):
        return None
    if ampm:
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    consume(clock)
    days = list(_RELATIVE.finditer(text))
    weekdays = list(_WEEKDAY.finditer(text))
    calendar = list(_CALENDAR.finditer(text))
    if len(calendar) > 1 or len(days) > 1 or len(weekdays) > 1:
        return None
    if re.search(r"\bpasado\s+ma[ñn]ana\b", text, re.I):
        return None
    if calendar:
        if days:
            return None
        date = calendar[0]
        if not date["year"] and re.match(r"\s+(?:de|del)\b", text[date.end() :], re.I):
            return None
        consume(date)
        due = now.replace(
            year=int(date["year"] or now.year),
            month=_MONTHS[date["month"].lower()],
            day=int(date["day"]),
        )
        if weekdays:
            wd = weekdays[0]
            wd_number = _WEEKDAYS[wd["weekday"].lower()]
            if due.weekday() != wd_number:
                return None
            next_day = bool(wd["next"] or wd["suffix"])
            this_day = "este" in wd["prefix"].lower().split() and not next_day
            if next_day or this_day:
                delta = wd_number - now.weekday()
                if next_day:
                    delta %= 7
                    if delta == 0:
                        delta = 7
                if due.date() != (now + timedelta(days=delta)).date():
                    return None
            consume(wd)
    elif len(days) + len(weekdays) != 1:
        return None
    elif days:
        day = days[0]
        consume(day)
        offset = 0 if day["day"].lower() == "hoy" else 1
        due = now + timedelta(days=offset)
    else:
        day = weekdays[0]
        consume(day)
        target = _WEEKDAYS[day["weekday"].lower()]
        next_day = bool(day["next"] or day["suffix"])
        this_day = "este" in day["prefix"].lower().split() and not next_day
        offset = target - now.weekday()
        if not this_day:
            offset %= 7
            if next_day and offset == 0:
                offset = 7
        due = now + timedelta(days=offset)
        candidate = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if not this_day and candidate <= now:
            due += timedelta(days=7)
    due = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        return None
    remainder = "".join(chars)
    if (
        P.UNCONSUMED_TEMPORAL_RE.search(remainder)
        or _LEFTOVER_MERIDIEM.search(remainder)
        or _NUMERIC_DATE.search(remainder)
    ):
        return None
    return _clean(remainder), due
