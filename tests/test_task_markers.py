"""Task classification is explicit, bounded and case-insensitive."""

import pytest

from app.nlp.item_intent import item_kind_for, task_body


@pytest.mark.parametrize(
    "text",
    [
        "t revisar propuesta",
        "T revisar propuesta",
        "  t\trevisar propuesta",
        "tarea revisar propuesta",
        "TAREA revisar propuesta",
        "revisar esta tarea mañana a las 9",
        "revisar (task) tomorrow at 9am",
        "remind me of this TASK in one minute",
    ],
)
def test_task_markers_are_recognized(text):
    assert item_kind_for(text) == "task"


@pytest.mark.parametrize(
    "text",
    [
        "tomorrow at 9am review",
        "Tengo que revisar equipo",
        "taskforce mañana a las 9",
        "multitask review",
        "review tarea_id 27/10/2026 9am",
        "review task_id 27/10/2026 9am",
        "revisar tareas mañana a las 9",
    ],
)
def test_other_words_do_not_trigger_task(text):
    assert item_kind_for(text) == "reminder"


def test_only_standalone_initial_t_is_removed_from_title():
    assert task_body(" t revisar equipo") == "revisar equipo"
    assert task_body("revisar la tarea del equipo") == "revisar la tarea del equipo"
    assert task_body("task revisar equipo") == "task revisar equipo"
    assert task_body("tomorrow review") == "tomorrow review"
