"""Per-line analysis for numbered HTML/history pastes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.nlp.dates import DateAnalysis, analyze_datetime, has_datetime_intent
from app.nlp.item_intent import (
    has_timing_intent,
    item_kind_for,
    task_body,
)
from app.nlp.parser import ParsedReminder, parse
from app.nlp.recurrence import Schedule

_ITEM = re.compile(r"^\s*(?P<number>\d+)\s*[.)]\s*(?P<text>.+?)\s*$")


@dataclass(frozen=True, slots=True)
class BatchItem:
    number: int
    original_text: str
    status: str
    analysis: DateAnalysis
    parsed: ParsedReminder | None = None


@dataclass(frozen=True, slots=True)
class BatchAnalysis:
    items: tuple[BatchItem, ...]

    @property
    def complete_items(self) -> tuple[BatchItem, ...]:
        return tuple(item for item in self.items if item.status == "complete")

    @property
    def rejected_items(self) -> tuple[BatchItem, ...]:
        return tuple(item for item in self.items if item.status != "complete")


def is_batch_input(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) > 1 and all(_ITEM.match(line) for line in lines)


def analyze_batch(text: str, *, now: datetime | None = None) -> BatchAnalysis:
    """Analyze each numbered line independently; never share a clock/title."""
    now = now or datetime.now()
    items: list[BatchItem] = []
    for fallback, line in enumerate(text.splitlines(), 1):
        match = _ITEM.match(line)
        if not match:
            continue
        item_text = match.group("text").strip()
        body = task_body(item_text)
        unscheduled = bool(
            item_kind_for(item_text) == "task" and body and not has_timing_intent(body)
        )
        parsed: ParsedReminder | None = None
        if unscheduled:
            title = body[:1].upper() + body[1:]
            analysis = DateAnalysis(
                status="complete", message=title, reason="task without alarm"
            )
            parsed = ParsedReminder(title, Schedule(kind="once"), "No active alarm")
        elif has_datetime_intent(body):
            analysis = analyze_datetime(body, now=now)
        elif item_kind_for(item_text) == "task" and has_timing_intent(body):
            analysis = DateAnalysis(
                status="missing_time", reason="an explicit clock is required"
            )
        else:
            parsed = parse(body, now=now)
            analysis = DateAnalysis(
                status="complete" if parsed else "invalid",
                due=parsed.schedule.run_date
                if parsed and parsed.schedule.kind == "once"
                else None,
                message=parsed.message if parsed else "",
                reason="legacy grammar" if parsed else "unrecognized datetime",
            )
        if not unscheduled:
            parsed = parse(body, now=now) if analysis.status == "complete" else None
        items.append(
            BatchItem(
                number=int(match.group("number") or fallback),
                original_text=item_text,
                status=analysis.status,
                analysis=analysis,
                parsed=parsed,
            )
        )
    return BatchAnalysis(tuple(items))
