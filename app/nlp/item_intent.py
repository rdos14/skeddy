"""Explicit user-selected item type markers, separate from date parsing."""

import re

_TASK_PREFIX = re.compile(r"^\s*t(?:\s+|$)", re.IGNORECASE)
_TASK_WORD = re.compile(r"\b(?:tarea|task)\b", re.IGNORECASE)


def item_kind_for(text: str) -> str:
    return "task" if _TASK_PREFIX.match(text) or _TASK_WORD.search(text) else "reminder"


def task_body(text: str) -> str:
    return _TASK_PREFIX.sub("", text, count=1).strip()


def has_timing_intent(text: str) -> bool:
    """Conservative gate: never turn a malformed requested date into no alarm."""
    from app.nlp import patterns as patterns
    from app.nlp.dates import has_datetime_intent, has_recurrence_intent
    from app.nlp.spanish import has_spanish_timing

    if (
        has_datetime_intent(text)
        or has_spanish_timing(text)
        or has_recurrence_intent(text)
        or patterns.DATE_RE.search(text)
    ):
        return True
    ordinary_units = {
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
    }
    if any(
        m.group().casefold() not in ordinary_units
        for m in patterns.UNCONSUMED_TEMPORAL_RE.finditer(text)
    ):
        return True
    return bool(
        re.search(
            r"\b(?:at|a\s+las?)\s*[+\-]?\d"
            r"|(?<!\w)[+\-]?\d{1,3}(?::[^\s]*|\s*[ap]\.?m\b)"
            r"|\b(?:\d+|un[ao]?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+"
            r"(?:segundos?|minutos?|horas?|d[ií]as?|semanas?|meses|a[nñ]os?)\b",
            text,
            re.IGNORECASE,
        )
    )
