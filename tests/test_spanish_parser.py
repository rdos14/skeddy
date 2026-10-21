"""Spanish date interpretation must consume the full intent, not guess."""

from datetime import datetime, timedelta

import pytest

from app.nlp import parse


@pytest.mark.parametrize("hour", [8, 18])
def test_manana_is_tomorrow_before_and_after_the_requested_clock(hour):
    now = datetime(2026, 10, 20, hour)
    result = parse("mañana a las 10am revisar equipo", now=now)
    assert result is not None
    assert result.schedule.run_date == (now + timedelta(days=1)).replace(hour=10)
    assert result.message == "Revisar equipo"


def test_hoy_uses_today_with_a_future_explicit_clock():
    now = datetime(2026, 10, 20, 8)
    result = parse("recuérdame revisar equipo para hoy a las 10am", now=now)
    assert result is not None
    assert result.schedule.run_date == now.replace(hour=10)
    assert result.message == "Revisar equipo"


def test_hoy_with_an_expired_clock_is_rejected():
    assert (
        parse("hoy a las 10am revisar equipo", now=datetime(2026, 10, 20, 18)) is None
    )


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("este viernes", "2026-10-23T09:00:00"),
        ("próximo sábado", "2026-10-24T09:00:00"),
        ("sábado próximo", "2026-10-24T09:00:00"),
        ("este lunes próximo", "2026-10-26T09:00:00"),
        ("MIÉRCOLES", "2026-10-21T09:00:00"),
    ],
)
def test_weekday_intent_not_tomorrow_fallback(phrase, expected):
    result = parse(
        f"revisar equipo para el {phrase} a las 9am", now=datetime(2026, 10, 20, 8)
    )
    assert result is not None
    assert result.schedule.run_date == datetime.fromisoformat(expected)
    assert result.message == "Revisar equipo"


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("este sábado", "2026-10-24T09:00:00"),
        ("próximo sábado", "2026-10-31T09:00:00"),
    ],
)
def test_this_and_next_on_the_same_weekday(phrase, expected):
    result = parse(f"{phrase} a las 9am revisar equipo", now=datetime(2026, 10, 24, 8))
    assert result is not None
    assert result.schedule.run_date == datetime.fromisoformat(expected)


@pytest.mark.parametrize(
    "text",
    [
        "este lunes a las 9am revisar equipo",
        "pasado mañana a las 9am revisar equipo",
        "hoy mañana a las 9am revisar equipo",
        "mañana a las 9am y a las 10am revisar equipo",
    ],
)
def test_ambiguous_conflicting_or_unimplemented_modifiers_reject(text):
    assert parse(text, now=datetime(2026, 10, 20, 8)) is None


@pytest.mark.parametrize(
    "clock,hour,minute",
    [
        ("830am", 8, 30),
        ("8:30am", 8, 30),
        ("9:00 a. m.", 9, 0),
        ("12:00 a.m.", 0, 0),
        ("12 p. m.", 12, 0),
        ("20:30", 20, 30),
    ],
)
def test_compact_colon_and_dictated_meridiem(clock, hour, minute):
    now = datetime(2026, 10, 20, 8)
    result = parse(f"Recordatorio para mañana a las {clock}: revisar equipo.", now=now)
    assert result is not None
    assert result.schedule.run_date == datetime(2026, 10, 21, hour, minute)
    assert result.message == "Revisar equipo"


@pytest.mark.parametrize(
    "prefix", ["jueves 30 de julio", "30 de julio", "30 de julio de 2026"]
)
def test_named_numeric_calendar_date_with_optional_consistent_weekday(prefix):
    result = parse(
        f"revisar equipo para el {prefix} a las 830am", now=datetime(2026, 7, 29, 8)
    )
    assert result is not None
    assert result.schedule.run_date == datetime(2026, 7, 30, 8, 30)
    assert result.message == "Revisar equipo"


@pytest.mark.parametrize(
    "text",
    [
        "mañana a las 13pm revisar equipo",
        "mañana a las 25:00 revisar equipo",
        "mañana a las 9:60 revisar equipo",
        "mañana a las 8:00:30 revisar equipo",
        "mañana a las 9am 2026-11-01 revisar equipo",
        "viernes 30 de julio a las 9am revisar equipo",
        "31 de febrero a las 9am revisar equipo",
        "mañana revisar equipo",
        "el próximo sábado revisar equipo",
    ],
)
def test_invalid_conflicting_or_missing_components_reject(text):
    assert parse(text, now=datetime(2026, 7, 29, 8)) is None


@pytest.mark.parametrize(
    "text",
    [
        "mañana a las 10.5am revisar equipo",
        "mañana a las -5am revisar equipo",
        "mañana a las +5am revisar equipo",
        "mañana de 8am-9am revisar equipo",
        "todos los viernes a las 9am revisar equipo",
        "cada viernes a las 9am revisar equipo",
        "mañana a las 10 y media revisar equipo",
        "viernes a las 9 de la noche revisar equipo",
    ],
)
def test_unsupported_clock_arithmetic_ranges_and_recurrence_reject(text):
    assert parse(text, now=datetime(2026, 10, 20, 8)) is None


@pytest.mark.parametrize(
    "text",
    [
        "mañana 10.5am revisar equipo",
        "30 de julio de 20260 a las 9am revisar equipo",
        "30 de julio de 2026x a las 9am revisar equipo",
        "30 de julio de 666 a las 9am revisar equipo",
    ],
)
def test_partial_decimal_clock_and_partial_year_are_never_consumed(text):
    assert parse(text, now=datetime(2026, 7, 29, 8)) is None


@pytest.mark.parametrize("qualifier", ["este", "próximo"])
def test_weekday_modifier_cannot_contradict_an_explicit_calendar_date(qualifier):
    now = datetime(2026, 7, 29, 8)
    assert now.weekday() == 2 and datetime(2026, 8, 6).weekday() == 3
    assert (
        parse(f"{qualifier} jueves 6 de agosto a las 9am revisar equipo", now=now)
        is None
    )
