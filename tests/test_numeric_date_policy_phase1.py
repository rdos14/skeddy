from datetime import datetime

from app.nlp import analyze_datetime, parse

NOW = datetime(2026, 1, 1, 8)


def test_numeric_dates_are_always_day_first_with_explicit_20yy_policy():
    for text in (
        "payload alpha 05/06/2027 at 9am",
        "payload alpha 05/06/27 at 9am",
        "payload alpha 05-06-27 at 9am",
    ):
        result = parse(text, now=NOW)
        assert result is not None
        assert result.schedule.run_date == datetime(2027, 6, 5, 9)


def test_mm_dd_is_invalid_not_locale_reinterpreted():
    analysis = analyze_datetime("payload alpha 12/31/2026 at 9am", now=NOW)
    assert analysis.status == "invalid"
    assert parse("payload alpha 12/31/2026 at 9am", now=NOW) is None
    assert parse("payload alpha 27/10/20260 at 9am", now=NOW) is None
