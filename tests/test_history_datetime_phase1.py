from datetime import datetime

from app.nlp import analyze_batch, analyze_datetime, parse

NOW = datetime(2026, 10, 21, 16, 49)


def test_day_first_slash_date_preserves_payload_and_clock():
    result = parse("payload alpha 27/10/2026 9am", now=NOW)
    assert result is not None
    assert result.schedule.run_date == datetime(2026, 10, 27, 9)
    assert result.message == "Payload alpha"


def test_english_weekday_and_month_ordinal_dates():
    saturday = parse("payload alpha 📋 Saturday at 9:00 AM", now=NOW)
    next_sunday = parse("payload alpha (📋 next Sunday at 1:54 PM)", now=NOW)
    august = parse("payload alpha (📋 August 29th, 2026 at 9:00 AM)", now=NOW)
    assert saturday is not None
    assert saturday.schedule.run_date == datetime(2026, 10, 24, 9)
    assert next_sunday is not None
    assert next_sunday.schedule.run_date == datetime(2026, 10, 25, 13, 54)
    future = parse(
        "payload alpha August 29th, 2027 at 9:00 AM", now=NOW
    )
    assert future is not None
    assert future.schedule.run_date == datetime(2027, 8, 29, 9)
    assert august is None


def test_past_english_date_is_rejected_without_tomorrow_fallback():
    analysis = analyze_datetime(
        "payload alpha (📋 August 29th, 2026 at 9:00 AM)", now=NOW
    )
    assert analysis.status == "past"
    assert parse("payload alpha August 29th, 2026 at 9:00 AM", now=NOW) is None


def test_missing_time_is_reported_and_parse_keeps_none_contract():
    for text in ("payload alpha next tuesday", "payload alpha 27/10"):
        analysis = analyze_datetime(text, now=NOW)
        assert analysis.status == "missing_time"
        assert analysis.target_date is not None
        assert parse(text, now=NOW) is None


def test_invalid_and_conflicting_dates_are_rejected():
    for text in (
        "payload alpha February 30th, 2027 at 9am",
        "payload alpha August 29th, 2026 Friday at 9am",
        "payload alpha next Tuesday August 29th, 2026 at 9am",
    ):
        assert analyze_datetime(text, now=NOW).status == "invalid"
        assert parse(text, now=NOW) is None


def test_relative_past_forms_are_explained_not_rolled_forward():
    for text in (
        "payload alpha yesterday at 10am",
        "payload alpha 7 hours ago",
        "payload alpha 4 hours ago",
    ):
        analysis = analyze_datetime(text, now=NOW)
        assert analysis.status == "past"
        assert parse(text, now=NOW) is None


def test_numbered_history_is_analyzed_per_line_without_one_clock():
    text = (
        "1) payload alpha (📋 August 29th, 2026 at 9:00 AM)\n"
        "2) payload beta (📋 last Sunday at 1:54 PM)\n"
        "3) payload gamma (📋 yesterday at 10:00 AM)\n"
        "4) payload delta (📋 7 hours ago)\n"
        "5) payload epsilon (📋 4 hours ago)\n"
        "6) payload zeta (📋 Saturday at 9:00 AM)"
    )
    batch = analyze_batch(text, now=NOW)
    assert len(batch.items) == 6
    assert [item.status for item in batch.items] == [
        "past",
        "past",
        "past",
        "past",
        "past",
        "complete",
    ]
    assert batch.items[5].parsed is not None
    assert batch.items[5].parsed.schedule.run_date == datetime(2026, 10, 24, 9)
