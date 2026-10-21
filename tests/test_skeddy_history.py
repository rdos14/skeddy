"""History-derived contracts, with explicit, strict accounting for known gaps.

SKEDDY_HISTORY_STRICT=1 turns known gaps into ordinary failures for auditing.
No production database, token, network connection or moving clock is used.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.nlp import parse

DATA = json.loads(
    (Path(__file__).parent / "fixtures/skeddy_history_anonymized.json").read_text()
)
CASES = DATA["cases"]
STRICT_AUDIT = os.environ.get("SKEDDY_HISTORY_STRICT") == "1"


def _parameters(target):
    parameters = []
    for case in CASES:
        marks = []
        if case["baseline_" + target] == "gap" and not STRICT_AUDIT:
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    raises=AssertionError,
                    reason=f"History {target} gap: {case['gap_reason']}",
                )
            )
        parameters.append(pytest.param(case, id=case["id"], marks=marks))
    return parameters


def _assert_intent(case, result):
    if case["oracle_kind"] in {"no_time", "policy"}:
        # A note/task flow or a default-hour policy is not a complete Schedule.
        assert result is None, "Do not invent a deadline for an unspecified time"
        return
    assert result is not None, "Requested form is not implemented"
    assert result.schedule.kind == "once"
    assert result.schedule.run_date is not None
    zone = ZoneInfo(case["timezone"])
    actual = result.schedule.run_date
    actual = (
        actual.replace(tzinfo=zone)
        if actual.tzinfo is None
        else actual.astimezone(zone)
    )
    expected = datetime.fromisoformat(case["expected_due"]).replace(tzinfo=zone)
    assert actual == expected, "Deadline differs from explicit temporal intent"
    if case["oracle_kind"] == "context":
        # This checks only the clock token, not editing an existing note/task.
        return
    title = result.message.casefold()
    assert case["payload"].casefold() in title, "Task payload was lost"
    for fragment in case["forbidden_title_fragments"]:
        assert fragment.casefold() not in title, "Temporal input leaked into title"
    for fragment in case.get("preserve_payload_fragments", []):
        assert fragment.casefold() in title, "Non-temporal payload was consumed"


@pytest.mark.parametrize("case", _parameters("compatibility"))
def test_history_intent_contract(case):
    result = parse(case["input"], now=datetime.fromisoformat(case["now"]))
    _assert_intent(case, result)


@pytest.mark.parametrize("case", _parameters("safety"))
def test_history_returns_correct_intent_or_rejects(case):
    result = parse(case["input"], now=datetime.fromisoformat(case["now"]))
    if result is not None:
        _assert_intent(case, result)


def test_fixture_shape_and_anonymization():
    assert len(CASES) == DATA["case_count"]
    assert DATA["source_case_count"] + DATA["derived_case_count"] == len(CASES)
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert sum("derived_from" in case for case in CASES) == DATA["derived_case_count"]
    serialized = json.dumps(DATA, ensure_ascii=False)
    assert not re.search(r"/open[0-9a-f]|skeddy\.me/\d|message\d{4,}", serialized)
    assert all(
        url.startswith("https://example.invalid/")
        for url in re.findall(r'https?://[^\s"<>]+', serialized)
    )
    for case in CASES:
        assert case["baseline_safety"] in {"pass", "gap"}
        assert case["baseline_compatibility"] in {"pass", "gap"}
        assert case["timezone"] == "America/Mexico_City"
        assert "original_input" not in case and "source_id" not in case
        datetime.fromisoformat(case["now"])
        if case["oracle_kind"] == "policy":
            assert case["expected_due"] is None
            assert case["observed_reference_due"].startswith(case["expected_date"])


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["oracle_kind"] == "conflict"],
    ids=lambda case: case["id"],
)
def test_reference_bot_errors_are_not_used_as_the_oracle(case):
    requested = datetime.fromisoformat(case["expected_due"])
    observed = datetime.fromisoformat(case["reference_due"])
    assert requested.weekday() == case["requested_weekday"]
    assert observed.weekday() != case["requested_weekday"]
    assert requested != observed
