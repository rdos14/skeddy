"""Unit tests for the natural-language reminder parser."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.nlp import analyze_batch, analyze_datetime, parse

NOW = datetime(2026, 9, 26, 12, 0)  # a Saturday, noon


def test_returns_none_for_non_temporal_text():
    assert parse("salom qalaysan", now=NOW) is None


def test_relative_minutes():
    result = parse("in 30 minutes turn off the kettle", now=NOW)
    assert result is not None
    assert result.schedule.kind == "once"
    assert result.schedule.run_date == datetime(2026, 9, 26, 12, 30)
    assert "kettle" in result.message.lower()


def test_relative_english():
    result = parse("in 2 hours call mom", now=NOW)
    assert result.schedule.kind == "once"
    assert result.schedule.run_date == datetime(2026, 9, 26, 14, 0)


def test_tomorrow_with_time():
    result = parse("tomorrow at 9 call the doctor", now=NOW)
    assert result.schedule.kind == "once"
    assert result.schedule.run_date == datetime(2026, 9, 27, 9, 0)


def test_daily():
    result = parse("every day at 22:00 drink water", now=NOW)
    assert result.schedule.kind == "cron"
    assert result.schedule.cron == {"hour": 22, "minute": 0}


def test_weekly_specific_day():
    result = parse("every monday at 10 send the report", now=NOW)
    assert result.schedule.kind == "cron"
    assert result.schedule.cron["day_of_week"] == "mon"
    assert result.schedule.cron["hour"] == 10


def test_every_monday_english():
    result = parse("every monday at 18:30 water the plants", now=NOW)
    assert result.schedule.cron["day_of_week"] == "mon"
    assert result.schedule.cron["hour"] == 18
    assert result.schedule.cron["minute"] == 30


def test_interval_minutes():
    result = parse("every 15 minutes check the status", now=NOW)
    assert result.schedule.kind == "interval"
    assert result.schedule.interval == {"minutes": 15}


def test_hourly():
    result = parse("every hour rest your eyes", now=NOW)
    assert result.schedule.kind == "cron"
    assert result.schedule.cron == {"minute": 0}


def test_first_monday_of_month_the_headline_example():
    result = parse(
        "every first monday at 9 check the server logs",
        now=NOW,
    )
    assert result.schedule.kind == "cron"
    cron = result.schedule.cron
    assert cron["day"] == "1-7"
    assert cron["day_of_week"] == "mon"
    assert cron["hour"] == 9
    assert cron["minute"] == 0


def test_last_friday_of_month():
    result = parse("every last friday of the month at 17:00 close the report", now=NOW)
    assert result.schedule.cron["day"] == "22-31"
    assert result.schedule.cron["day_of_week"] == "fri"


def test_day_period_default_evening():
    result = parse("tomorrow evening wash the car", now=NOW)
    # evening -> 19:00
    assert result.schedule.run_date == datetime(2026, 9, 27, 19, 0)


def test_explicit_date():
    result = parse("27.09 at 15:30 make the payment", now=NOW)
    assert result.schedule.kind == "once"
    assert result.schedule.run_date == datetime(2026, 9, 27, 15, 30)


def test_bare_time_today_rolls_to_tomorrow_if_past():
    # 09:00 is before NOW (12:00) -> should roll to next day
    result = parse("at 9 go running", now=NOW)
    assert result.schedule.run_date == datetime(2026, 9, 27, 9, 0)


@pytest.mark.parametrize(
    "text",
    [
        "every day at 08:00 exercise",
        "every day at 8 do exercise",
    ],
)
def test_schedule_roundtrips_through_json(text):
    from app.nlp.recurrence import Schedule

    parsed = parse(text, now=NOW)
    restored = Schedule.from_json(parsed.schedule.to_json())
    assert restored.kind == parsed.schedule.kind
    assert restored.cron == parsed.schedule.cron


@pytest.mark.parametrize(
    "text",
    [
        "30 daqiqadan keyin payload",
        "ertaga soat 9 da payload",
        "ertaga 9am payload",
        "har kuni 22:00 da payload",
        "har dushanba soat10da payload",
        "har15daqiqada payload",
        "harsoatda payload",
        "har oyning birinchi dushanbasida soat 9 da payload",
        "har oyning oxirgi juma 17:00 da payload",
        "ertaga kechqurun payload",
        "27.09 soat15:30da payload",
        "soat9da payload",
        "har kuni 09:00payload",
    ],
)
def test_retired_uzbek_temporal_grammar_is_rejected(text):
    assert parse(text, now=NOW) is None


def test_retired_uzbek_guard_does_not_match_english_minute_or_identifiers():
    assert parse("in 1 minute backup_har", now=NOW) is not None
    assert parse("in 1 minute min_utf", now=NOW) is not None
    assert parse("in 1 minute backup_miercoles", now=NOW) is not None
    assert parse("in 1 minute backup_dushanba", now=NOW) is not None
    assert parse("in 1 minute Julio", now=NOW) is not None


def test_date_analysis_rejects_retired_uzbek_instead_of_completing_clock():
    analysis = analyze_datetime("ertaga 9am payload", now=NOW)
    assert analysis.status == "invalid"
    assert not analysis.complete


def test_batch_does_not_turn_retired_uzbek_task_into_an_untimed_task():
    analysis = analyze_batch("1) t ertaga payload\n2) t review notes", now=NOW)
    assert [item.status for item in analysis.items] == ["invalid", "complete"]
    assert analysis.items[0].parsed is None
