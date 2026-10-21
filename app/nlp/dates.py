"""Bounded English and slash-date one-off datetime analysis.

The analyzer deliberately exposes incomplete and unsafe intent instead of
letting the reminder parser guess a clock or roll a past date forward.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.nlp import patterns as P

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_MONTH_ALT = "|".join(_MONTHS)
_WEEKDAY_ALT = "|".join(_WEEKDAYS)
_DATE_MARKER = re.compile(
    rf"(?<!\w)(?:(?P<modifier>next|this|last)\s+)?"
    rf"(?P<weekday>{_WEEKDAY_ALT})(?!\w)"
    rf"|(?<![\w/-])(?P<slash>\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)(?![\w/-])"
    rf"|(?<!\w)(?P<month>{_MONTH_ALT})\s+"
    r"(?P<month_day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*,?\s*(?P<month_year>\d{4}))?(?!\w)",
    re.IGNORECASE,
)
_YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)
_AGO = re.compile(
    r"\b(?P<amount>\d+)\s+(?P<unit>minutes?|hours?|days?)\s+ago\b",
    re.IGNORECASE,
)
_NUMERIC_LIKE = re.compile(
    r"(?<!\d-)(?<!\w)\d{1,2}[/-]\d{1,2}(?:[/-]\d+)?"
)
_CLOCK = re.compile(
    r"(?<![\w:/.+-])(?:(?:at|a\s+las?)\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<ampm>[ap]\s*\.?\s*m\.?)?(?!\w|[:.]\d|\.)",
    re.IGNORECASE,
)
_RECURRENCE = re.compile(
    r"\b(?:every|each|har|daily|everyday|weekly|monthly|hourly|"
    r"cada|diariamente|semanalmente|mensualmente|anualmente)\b",
    re.IGNORECASE,
)
_BAD_CLOCK = re.compile(
    r"(?:\b(?:at|a\s+las?)\s*[+-]?\d+(?:[.,]\d+)"
    r"|(?<!\w)[+-]\d+(?:[.,]?\d*)\s*[ap]\s*\.?\s*m\.?"
    r"|\b(?:at|a\s+las?)\s*\d{1,2}:\s*(?!\d))",
    re.IGNORECASE,
)
_UNSUPPORTED_CLOCK_WORDS = re.compile(
    r"\b(?:y|and)\s+(?:media|half|cuarto|quarter)\b|\bo['’]?clock\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DateAnalysis:
    """Result of :func:`analyze_datetime`.

    ``status`` is one of ``complete``, ``missing_time``, ``past`` or
    ``invalid``.  ``target_date`` is retained for ``missing_time`` so a UI or
    pending draft can ask for a clock without reparsing the user's date words.
    """

    status: str
    due: datetime | None = None
    target_date: date | None = None
    message: str = ""
    reason: str = ""
    temporal_text: str = ""
    date_spans: tuple[tuple[int, int], ...] = ()
    clock_span: tuple[int, int] | None = None

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def missing_time(self) -> bool:
        return self.status == "missing_time"

    @property
    def past(self) -> bool:
        return self.status == "past"


def has_datetime_intent(text: str) -> bool:
    if _RECURRENCE.search(text):
        return False
    for _marker in _DATE_MARKER.finditer(text):
        return True
    return bool(
        _YESTERDAY.search(text) or _AGO.search(text) or _NUMERIC_LIKE.search(text)
    )


def _clock(
    text: str, date_spans: list[tuple[int, int]]
) -> tuple[time, tuple[int, int]] | None | bool:
    candidates = []
    for match in _CLOCK.finditer(text):
        span = (match.start(), match.end())
        if any(
            match.start() >= start and match.end() <= end for start, end in date_spans
        ):
            continue
        raw = match.group(0)
        ampm = re.sub(r"[\s.]", "", match.group("ampm") or "").lower()
        if not (
            ampm
            or match.group("minute")
            or re.search(r"\b(?:at|a\s+las?)\b", raw, re.I)
        ):
            continue
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        if ampm and not 1 <= hour <= 12:
            return False
        if hour > 23 or minute > 59:
            return False
        if ampm:
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        candidates.append((time(hour, minute), span))
    if len(candidates) > 1:
        return False
    return candidates[0] if candidates else None


def has_recurrence_intent(text: str) -> bool:
    """Return whether the text belongs to recurring, not one-off, grammar."""
    return bool(_RECURRENCE.search(text))


def has_unsupported_clock(text: str) -> bool:
    """Return whether a bounded parser would only consume part of a clock."""
    return bool(_BAD_CLOCK.search(text) or _UNSUPPORTED_CLOCK_WORDS.search(text))


def _has_temporal_residue(text: str, spans: list[tuple[int, int]]) -> bool:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    remainder = "".join(chars)
    return bool(
        P.UNCONSUMED_TEMPORAL_RE.search(remainder)
        or _UNSUPPORTED_CLOCK_WORDS.search(remainder)
    )


def _invalid_analysis(
    text: str, spans: list[tuple[int, int]], reason: str
) -> DateAnalysis:
    return _analysis("invalid", text=text, spans=spans, reason=reason)


def _target_from_weekday(
    marker: re.Match[str], now: datetime, has_clock: bool, clock: time | None
) -> date:
    target = _WEEKDAYS[marker.group("weekday").lower()]
    modifier = (marker.group("modifier") or "").lower()
    if modifier == "next":
        offset = (target - now.weekday()) % 7 or 7
    elif modifier == "last":
        offset = -((now.weekday() - target) % 7 or 7)
    elif modifier == "this":
        offset = target - now.weekday()
    else:
        offset = (target - now.weekday()) % 7
        if offset == 0 and has_clock and clock is not None:
            candidate = now.replace(
                hour=clock.hour, minute=clock.minute, second=0, microsecond=0
            )
            if candidate <= now:
                offset = 7
    return (now + timedelta(days=offset)).date()


def _mask_message(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    remainder = "".join(chars)
    # Only remove the HTML-history wrapper, never punctuation belonging to the
    # user's payload (for example ``(QA, alpha)``).
    remainder = re.sub(r"\(\s*📋\s*\)", " ", remainder)
    remainder = remainder.replace("📋", " ")
    remainder = re.sub(r"\b(?:at|on)\s*$", "", remainder, flags=re.IGNORECASE)
    remainder = re.sub(
        r"^(?:\s*(?:remind\s+me(?:\s+to)?|recu[eé]rdame|recordarme|"
        r"recordatorio(?:\s+(?:de|que))?|contenido\s+del\s+recordatorio)"
        r"[\s:,.—-]*)+",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    words = remainder.split()
    message = " ".join(words).strip(" .,:;—-")
    return message[:1].upper() + message[1:] if message else "Reminder"


def _analysis(
    status: str,
    *,
    due: datetime | None = None,
    target_date: date | None = None,
    text: str,
    spans: list[tuple[int, int]],
    clock_span: tuple[int, int] | None = None,
    reason: str = "",
) -> DateAnalysis:
    all_spans = list(spans)
    if clock_span:
        all_spans.append(clock_span)
    all_spans.sort()
    temporal_text = " ".join(
        text[start:end].strip() for start, end in all_spans
    ).strip()
    return DateAnalysis(
        status=status,
        due=due,
        target_date=target_date,
        message=_mask_message(text, all_spans),
        reason=reason,
        temporal_text=temporal_text,
        date_spans=tuple(spans),
        clock_span=clock_span,
    )


def analyze_datetime(text: str, *, now: datetime | None = None) -> DateAnalysis:
    """Analyze bounded English/slash date intent without creating a reminder."""
    now = now or datetime.now()
    if has_recurrence_intent(text):
        return _invalid_analysis(text, [], "recurring input is not a one-off date")
    markers = list(_DATE_MARKER.finditer(text))
    yesterday = list(_YESTERDAY.finditer(text))
    ago = list(_AGO.finditer(text))
    if not markers and not yesterday and not ago and _NUMERIC_LIKE.search(text):
        return _analysis("invalid", text=text, spans=[], reason="invalid numeric date")
    if len(markers) + len(yesterday) + len(ago) != 1:
        return _analysis(
            "invalid", text=text, spans=[], reason="conflicting date expressions"
        )

    date_spans: list[tuple[int, int]] = []
    target: date | None = None
    relative_due: datetime | None = None
    marker = markers[0] if markers else None
    if (
        marker
        and marker.group("weekday")
        and re.search(
            r"\b(?:today|tomorrow|yesterday)\b|\bin\s+\d+\s+\w+",
            text,
            re.I,
        )
    ):
        return _analysis(
            "invalid", text=text, spans=[], reason="conflicting date expressions"
        )
    if marker:
        date_spans.append((marker.start(), marker.end()))
        if marker.group("weekday"):
            target = _target_from_weekday(marker, now, False, None)
        elif marker.group("slash"):
            parts = [int(part) for part in re.split(r"[/-]", marker.group("slash"))]
            date_parts = re.split(r"[/-]", marker.group("slash"))
            separators = re.findall(r"[/-]", marker.group("slash"))
            if len(set(separators)) > 1:
                return _invalid_analysis(
                    text, date_spans, "mixed numeric date separators"
                )
            day, month = parts[:2]
            year = parts[2] if len(parts) == 3 else now.year
            if len(date_parts) == 3 and len(date_parts[2]) == 2:
                year += 2000
            try:
                target = date(year, month, day)
            except ValueError:
                return _analysis(
                    "invalid",
                    text=text,
                    spans=date_spans,
                    reason="invalid calendar date",
                )
        else:
            try:
                target = date(
                    int(marker.group("month_year") or now.year),
                    _MONTHS[marker.group("month").lower()],
                    int(marker.group("month_day")),
                )
            except ValueError:
                return _analysis(
                    "invalid",
                    text=text,
                    spans=date_spans,
                    reason="invalid calendar date",
                )
    elif yesterday:
        date_spans.append((yesterday[0].start(), yesterday[0].end()))
        target = (now - timedelta(days=1)).date()
    else:
        match = ago[0]
        date_spans.append((match.start(), match.end()))
        amount = int(match.group("amount"))
        if amount <= 0:
            return _analysis(
                "invalid",
                text=text,
                spans=date_spans,
                reason="nonpositive relative amount",
            )
        unit = match.group("unit").lower()
        kwargs = {"minutes": amount} if unit.startswith("minute") else {"hours": amount}
        if unit.startswith("day"):
            kwargs = {"days": amount}
        relative_due = now - timedelta(**kwargs)
        target = relative_due.date()

    # A second weekday/month/date marker is invalid even when the first one is
    # otherwise parseable.  This also catches ordinal/date/weekday conflicts.
    residual_markers = [
        m
        for m in _DATE_MARKER.finditer(text)
        if marker is None or m.start() != marker.start()
    ]
    if residual_markers:
        return _analysis(
            "invalid",
            text=text,
            spans=date_spans,
            reason="conflicting date expressions",
        )

    if _BAD_CLOCK.search(text) or _UNSUPPORTED_CLOCK_WORDS.search(text):
        return _invalid_analysis(text, date_spans, "unsupported or malformed clock")
    clock_result = _clock(text, date_spans)
    if clock_result is False:
        return _invalid_analysis(text, date_spans, "invalid or repeated clock")
    all_spans = list(date_spans)
    if isinstance(clock_result, tuple):
        all_spans.append(clock_result[1])
    if _has_temporal_residue(text, all_spans):
        return _invalid_analysis(
            text, date_spans, "unsupported or conflicting temporal text"
        )
    if relative_due is not None and clock_result is not None:
        return _analysis(
            "invalid", text=text, spans=date_spans, reason="relative date with clock"
        )
    if clock_result is None and relative_due is not None:
        return _analysis(
            "past",
            due=relative_due,
            target_date=target,
            text=text,
            spans=date_spans,
            reason="relative time is in the past",
        )
    if clock_result is None:
        if target is not None and target < now.date():
            return _analysis(
                "past",
                target_date=target,
                text=text,
                spans=date_spans,
                reason="requested date is in the past",
            )
        return _analysis(
            "missing_time",
            target_date=target,
            text=text,
            spans=date_spans,
            reason="a clock is required",
        )

    clock, clock_span = clock_result
    if marker and marker.group("weekday") and not marker.group("modifier"):
        target = _target_from_weekday(marker, now, True, clock)
    if relative_due is not None:
        due = relative_due
    else:
        assert target is not None
        due = datetime.combine(target, clock)
        if marker and marker.group("weekday"):
            expected = _WEEKDAYS[marker.group("weekday").lower()]
            if due.weekday() != expected:
                return _analysis(
                    "invalid",
                    text=text,
                    spans=date_spans,
                    clock_span=clock_span,
                    reason="weekday conflicts with date",
                )
            if marker.group("modifier") == "next":
                expected_date = _target_from_weekday(marker, now, True, clock)
                if target != expected_date:
                    return _analysis(
                        "invalid",
                        text=text,
                        spans=date_spans,
                        clock_span=clock_span,
                        reason="next weekday conflicts with date",
                    )
            if marker.group("modifier") == "this":
                week_start = (now - timedelta(days=now.weekday())).date()
                week_end = week_start + timedelta(days=6)
                if not week_start <= target <= week_end:
                    return _analysis(
                        "invalid",
                        text=text,
                        spans=date_spans,
                        clock_span=clock_span,
                        reason="this weekday conflicts with date",
                    )

    if due <= now:
        return _analysis(
            "past",
            due=due,
            target_date=target,
            text=text,
            spans=date_spans,
            clock_span=clock_span,
            reason="requested time is in the past",
        )
    return _analysis(
        "complete",
        due=due,
        target_date=target,
        text=text,
        spans=date_spans,
        clock_span=clock_span,
    )


def combine_pending_date(
    target_date: date, clock_text: str, *, now: datetime
) -> DateAnalysis:
    """Apply only a newly supplied clock to a previously frozen calendar date."""
    if _BAD_CLOCK.search(clock_text) or _UNSUPPORTED_CLOCK_WORDS.search(clock_text):
        return DateAnalysis(status="invalid", reason="one explicit clock is required")
    result = _clock(clock_text, [])
    if not isinstance(result, tuple):
        return DateAnalysis(status="invalid", reason="one explicit clock is required")
    clock, span = result
    remainder = clock_text[: span[0]] + clock_text[span[1] :]
    if remainder.strip():
        return DateAnalysis(status="invalid", reason="clock reply contains extra text")
    due = datetime.combine(target_date, clock)
    status = "past" if due <= now else "complete"
    return DateAnalysis(
        status=status,
        due=due,
        target_date=target_date,
        message="Reminder",
        temporal_text=clock_text[span[0] : span[1]].strip(),
        clock_span=span,
        reason="requested time is in the past" if status == "past" else "",
    )


# Short aliases keep the public API discoverable for callers that prefer a
# noun over the operation name.
analyze_date = analyze_datetime
analyze = analyze_datetime
