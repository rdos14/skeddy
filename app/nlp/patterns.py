"""English lexicon and regexes for the reminder parser.

Everything the parser needs to recognise time, weekdays, ordinals and
recurrence keywords lives here.  Retired Uzbek forms are kept only in the
bounded rejection guard at the bottom; they are not parser grammar.
"""

from __future__ import annotations

import re

# --- Weekdays -> Python weekday number (Mon=0 .. Sun=6) --------------------
WEEKDAYS: dict[str, int] = {
    # English
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

# APScheduler cron uses three-letter lowercase day names.
CRON_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# --- Ordinals (nth weekday of month) ---------------------------------------
ORDINALS: dict[str, int] = {
    # English
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "last": -1,
}

# --- Time-unit words -> canonical unit -------------------------------------
UNITS: dict[str, str] = {
    "minute": "minutes",
    "minutes": "minutes",
    "min": "minutes",
    "hour": "hours",
    "hours": "hours",
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
}

# --- Day-period words -> default hour ---------------------------------------
DAY_PERIODS: dict[str, int] = {
    "morning": 9,
    "noon": 12,
    "afternoon": 14,
    "evening": 19,
    "night": 22,
}

# Words that mark a PM interpretation for a bare hour.
PM_HINTS = {"evening", "night", "pm", "afternoon"}
AM_HINTS = {"morning", "am"}

# --- Recurrence keyword groups ---------------------------------------------
EVERY_WORDS = ("every", "each")
DAILY_WORDS = ("every day", "daily", "everyday")
WEEKLY_WORDS = ("every week", "weekly")
MONTHLY_WORDS = ("every month", "monthly")
HOURLY_WORDS = ("every hour", "hourly")

# Filler words stripped from the extracted reminder message.
FILLER_WORDS = (
    "remind",
    "me",
    "to",
    "that",
    "please",
)

# --- Compiled regexes -------------------------------------------------------

# "at 9:30", "9am", "9 pm", "9:00"
TIME_RE = re.compile(
    r"""
    (?:\bat\s+)?                    # optional "at"
    (?P<hour>2[0-3]|[01]?\d)         # hour 0-23 (two-digit forms tried first)
    (?::(?P<minute>[0-5]\d))?        # optional :minutes
    \s*(?P<ampm>am|pm)?              # optional am/pm
    (?!\w)
    """,
    re.VERBOSE | re.IGNORECASE,
)

# "in 30 minutes", "2 hours later"
UNIT_ALTERNATION = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))

RELATIVE_RE = re.compile(
    rf"""
    (?<![\w.+-])
    (?:\bin\s+)?
    (?P<amount>\d+|one\b)\s*
    (?P<unit>{UNIT_ALTERNATION})\b
    (?:\s*(?:later)\b)?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# "every 15 minutes"
INTERVAL_RE = re.compile(
    rf"""
    \b(?:every|each)\s+
    (?P<amount>\d+)\s*
    (?P<unit>{UNIT_ALTERNATION})\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ISO or dotted dates: 2026-09-27 or 27.09.2026 or 27.09
DATE_RE = re.compile(
    r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"
    r"|\b(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})(?:\.(?P<y2>\d{4}))?\b"
)


def weekday_alternation() -> str:
    return "|".join(sorted(WEEKDAYS, key=len, reverse=True))


def ordinal_alternation() -> str:
    return "|".join(re.escape(o) for o in sorted(ORDINALS, key=len, reverse=True))


# "first monday", "last friday"
NTH_WEEKDAY_RE = re.compile(
    rf"\b(?P<ord>{ordinal_alternation()})\s+(?P<wd>{weekday_alternation()})",
    re.IGNORECASE,
)

# a bare weekday mention, e.g. "monday"
WEEKDAY_RE = re.compile(rf"\b(?P<wd>{weekday_alternation()})\b", re.IGNORECASE)

TOMORROW_WORDS = ("tomorrow",)
TODAY_WORDS = ("today",)
RECURRENCE_RE = re.compile(
    r"\b(?:every|each|daily|everyday|weekly|monthly|hourly)\b",
    re.IGNORECASE,
)

# Known temporal tokens must not survive as a silently ignored part of a title.
# This deliberately rejects unsupported forms rather than guessing a date.
NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "hundred",
    "a",
    "an",
    "half",
    "quarter",
)
QUANTITY_PATTERN = rf"(?:[+-]?\d+(?:[.,]\d+)?|{'|'.join(NUMBER_WORDS)})"
UNSUPPORTED_PREFIX_RE = re.compile(
    rf"\b(?:after|within)\s+{QUANTITY_PATTERN}\b"
    r"|\bin\s+(?:[+-]\d+(?:[.,]\d+)?|\d+[.,]\d+)\b",
    re.IGNORECASE,
)
# Spanish date words are rejection markers only, not supported grammar.
# Keep them in the residual-token check so a bare AM/PM clock cannot silently
# override an unsupported requested day. Reserved words in titles may therefore
# be conservatively rejected until Spanish interpretation is implemented.
UNSUPPORTED_SPANISH_TEMPORAL_WORDS = (
    "hoy",
    "mañana",
    "manana",
    "lunes",
    "martes",
    "miércoles",
    "miercoles",
    "jueves",
    "viernes",
    "sábado",
    "sabado",
    "domingo",
    "ayer",
    "anteayer",
    "próximo",
    "proximo",
    "próxima",
    "proxima",
    "segundo",
    "segundos",
    "minuto",
    "minutos",
    "hora",
    "horas",
    "día",
    "dia",
    "días",
    "dias",
    "semana",
    "semanas",
    "mes",
    "meses",
    "año",
    "años",
)
# Month names need a date-like preposition: "Julio" alone can be a task's person.
_SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_TEMPORAL_WORDS = set(
    (
        *UNSUPPORTED_SPANISH_TEMPORAL_WORDS,
        *TODAY_WORDS,
        *TOMORROW_WORDS,
        *WEEKDAYS,
        *EVERY_WORDS,
        *DAILY_WORDS,
        *WEEKLY_WORDS,
        *MONTHLY_WORDS,
        *HOURLY_WORDS,
    )
)
_TEMPORAL_ALTERNATION = "|".join(
    re.escape(w) for w in sorted(_TEMPORAL_WORDS, key=len, reverse=True)
)
UNCONSUMED_TEMPORAL_RE = re.compile(
    rf"\b(?:{_TEMPORAL_ALTERNATION})\b"
    rf"|\b(?:de|en|para)\s+(?:el\s+)?(?:{'|'.join(_SPANISH_MONTHS)})\b"
    rf"|\b(?:in|after|within)\s+{QUANTITY_PATTERN}\b"
    rf"|\b{QUANTITY_PATTERN}\s*(?:{UNIT_ALTERNATION}|seconds?|months?|years?)\b"
    r"|\b(?:next|this|coming|last)\s+(?:day|week|month|year|quarter|fortnight)\b",
    re.IGNORECASE,
)
DAY_CONTEXTS = (
    (re.compile(r"\btoday\b", re.IGNORECASE), 0),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), 1),
)
MONTHLY_CONTEXT_RE = re.compile(
    r"\b(?:of\s+)?every\s+month|\bmonthly\b",
    re.IGNORECASE,
)

# Retired Uzbek temporal grammar.  This is deliberately a rejection-only
# guard: it is never used to construct a Schedule.  Context and word
# boundaries keep ordinary English identifiers and ``minute`` untouched.
RETIRED_UZBEK_TEMPORAL_RE = re.compile(
    r"""
    (?<!\w)(?:
        ertaga|bugun|kecha|kechqurun|kechasi|ertalab|tong|tushda|peshin|kunduzi
        |dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba
    )(?!\w)
    |(?<!\w)har\s+(?:kuni|hafta|oy(?:ning)?|soat(?:da)?
        |dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba)\b
    |(?<!\w)har\s*\d+\s*(?:daqiqa|minut|soat|kun|hafta)(?:da|dan)?\b
    |(?<!\w)har\s*(?:soat(?:da)?|kun(?:i)?|hafta(?:lik)?)(?!\w)
    |(?<!\w)soat\s*(?:2[0-3]|[01]?\d)(?::[0-5]\d)?\s*(?:da)?(?!\w)
    |(?<!\w)\d{1,2}\.\d{1,2}\s+soat\s*(?:2[0-3]|[01]?\d)
        (?::[0-5]\d)?\s*(?:da)?(?!\w)
    |(?<!\w)\d+\s*(?:daqiqa|minut|soat|kun|hafta)(?:da|dan)?\b
    |(?<!\w)har\s+oyning\s+(?:birinchi|ikkinchi|uchinchi|to'rtinchi|turtinchi|oxirgi|songgi|so'nggi)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
