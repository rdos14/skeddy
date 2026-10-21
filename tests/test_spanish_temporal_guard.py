"""Reject known unsupported Spanish timing; never treat it as a bare clock."""

from datetime import datetime, timedelta

import pytest

from app.nlp import parse


@pytest.mark.parametrize("now", [datetime(2026, 10, 20, 8), datetime(2026, 10, 20, 18)])
@pytest.mark.parametrize(
    "text",
    [
        "en 10 minutos a las 10am revisar equipo",
        "dentro de una hora a las 10am revisar equipo",
        "en dos días a las 10am revisar equipo",
        "la semana que viene a las 10am revisar equipo",
        "el próximo mes a las 10am revisar equipo",
        "dentro de un año a las 10am revisar equipo",
    ],
)
def test_unsupported_spanish_timing_is_not_replaced_by_a_clock(text, now):
    assert parse(text, now=now) is None


@pytest.mark.parametrize(
    "title,expected_title",
    [
        ("llamar a mamá", "Llamar a mamá"),
        ("revisar equipo", "Revisar equipo"),
        ("revisar backup_miercoles", "Revisar backup_miercoles"),
        ("revisar sabadometro", "Revisar sabadometro"),
        ("llamar a Julio", "Llamar a Julio"),
    ],
)
def test_english_duration_keeps_non_temporal_spanish_payload(title, expected_title):
    now = datetime(2026, 10, 20, 8)
    result = parse(f"in 5 minutes {title}", now=now)
    assert result is not None
    assert result.schedule.run_date == now + timedelta(minutes=5)
    assert result.message == expected_title
