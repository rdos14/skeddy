# Automatic Task markers

New user requests are created as Task when they start with the standalone
prefix `t `, or contain the complete word `tarea` or `task` anywhere. Matching
is case-insensitive and uses word boundaries: `taskforce`, `multitask`,
`tarea_id` and `task_id` do not match. The `t ` prefix is removed from the
visible title; other words remain intact. `original_text` is preserved exactly.

- No date/time intent: create a pending Task with no alarm and no invented
  deadline. Persistence uses an inactive primary `Schedule(kind='once')` with
  no run_date and explicit ItemState.kind=task. Never register a DateTrigger
  with a missing date: APScheduler can otherwise fire it immediately.
- Valid date/time or duration: create Task with the parsed schedule. It stays
  pending after the alarm fires until Complete.
- Recognized date missing a clock: existing persistent date prompts retain
  Task classification from the original request, including across restart.
- Other incomplete/unsafe date or recurrence requests reject or request an
  explicit clock; never silently turn them into an unscheduled Task or pick
  an implicit 09:00.
- Numbered batches classify each line independently and still require
  confirmation; typed unscheduled Tasks do not inherit another line's clock.
- Without a Task marker, normal Reminder creation remains unchanged.

Numeric dates remain day-first (DD/MM/YYYY, DD/MM/YY, DD-MM-YY), never MM/DD.
This changes creation only. Existing item types/schedules are not reclassified
or reparsed, and a later explicit Change type remains authoritative.

Source: app/nlp/item_intent.py; creation handlers, pending-date completion and
batch confirmation pass the explicit item_kind to ReminderRepository.create.
No schema or dependencies change.
