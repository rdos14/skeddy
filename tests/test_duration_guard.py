"""Regressions: complete durations and fail-closed temporal interpretation."""

from datetime import datetime, timedelta

import pytest

from app.nlp import parse

NOW = datetime(2026, 10, 20, 17, 2, 21)


@pytest.mark.parametrize(
    "text,minutes",
    [
        ("in one minute today test", 1),
        ("in one minute test", 1),
        ("in 1 minute test", 1),
        ("in 2 minutes test", 2),
        ("in 1 min test", 1),
        ("in 1 minute today test", 1),
        ("in one hour test", 60),
        ("in 2 hours test", 120),
        ("in 1 minute later test", 1),
    ],
)
def test_complete_relative_duration(text, minutes):
    result = parse(text, now=NOW)
    assert result is not None
    assert result.schedule.kind == "once"
    assert result.schedule.run_date == NOW + timedelta(minutes=minutes)
    assert result.message == "Test"


@pytest.mark.parametrize(
    "text",
    [
        "in two minutes today test",
        "in five seconds today test",
        "in 1 second today test",
        "after two hours today test",
        "within 1 minute today test",
        "in 1.5 hours today test",
        "in -1 minute today test",
        "in 0 minutes today test",
        "every 0 minutes test",
        "every two hours today test",
        "tomorrow at 8am next friday test",
        "in one minute tomorrow test",
        "in one minute today tomorrow test",
        "in 1 minute today at 9pm test",
        "today at 8am test",
        "today test",
        "tomorrow test",
        "2026-10-21 test",
        "tomorrow at 9am next week test",
        "in 1 min and 2 hours today test",
        "tomorrow at 9am two minutes test",
    ],
)
def test_unsupported_or_conflicting_time_is_rejected(text):
    assert parse(text, now=NOW) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "next wednesday at 8am study wells for presentation",
            datetime(2026, 10, 21, 8),
        ),
        ("next friday at 8am test", datetime(2026, 10, 23, 8)),
        ("this friday at 8am test", datetime(2026, 10, 23, 8)),
    ],
)
def test_supported_english_weekday_forms(text, expected):
    result = parse(text, now=NOW)
    assert result is not None
    assert result.schedule.run_date == expected


@pytest.mark.parametrize(
    "text,minutes",
    [
        ("every 1 minute test", 1),
        ("every 15 minutes test", 15),
        ("every 2 hours test", 120),
    ],
)
def test_interval_unit_is_consumed_in_full(text, minutes):
    result = parse(text, now=NOW)
    assert result is not None
    expected = {"hours": minutes // 60} if minutes >= 60 else {"minutes": minutes}
    assert result.schedule.kind == "interval"
    assert result.schedule.interval == expected
    assert result.message == "Test"


def test_supported_explicit_date_keeps_its_date_and_title():
    result = parse("2026-10-23 at 08:00 study wells", now=NOW)
    assert result is not None
    assert result.schedule.run_date == datetime(2026, 10, 23, 8)
    assert result.message == "Study wells"


def test_relative_today_does_not_silently_cross_midnight():
    assert parse("in one hour today test", now=datetime(2026, 10, 20, 23, 30)) is None


def test_relative_and_tomorrow_can_agree_explicitly():
    result = parse("in one hour tomorrow test", now=datetime(2026, 10, 20, 23, 30))
    assert result is not None
    assert result.schedule.run_date == datetime(2026, 10, 21, 0, 30)
    assert result.message == "Test"
