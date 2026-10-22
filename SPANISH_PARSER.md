# Spanish one-off dates (point 2)

Spanish scheduling is deterministic and bounded; it is not general natural-language
understanding. English parsing and stored schedules are preserved; retired Uzbek
temporal forms are rejected rather than interpreted.

## Supported

A Spanish request requires a recognized day/date **and an explicit clock**:

- `mañana a las 10am revisar equipo`
- `recuérdame revisar equipo para hoy a las 20:30`
- `próximo sábado a las 830am revisar equipo`
- `este viernes a las 9:00 a. m. revisar equipo`
- `jueves 30 de julio de 2026 a las 8:30am revisar equipo` (use a future date)

Accented/unaccented weekday names, uppercase AM/PM, compact clocks, 24-hour
colon clocks and dotted/spaced `a. m.` / `p. m.` are recognized. Midnight/noon
are validated rather than guessed. Temporal text and request prefixes are removed
from the title; user text is persisted verbatim as `original_text`.

The shared English/history datetime analyzer also accepts numeric Spanish dates
as day-first `DD/MM/YYYY`, `DD/MM/YY` or `DD-MM-YY` only. Two-digit years use
the explicit `20YY` policy; `MM/DD` is invalid. See [DATETIME_PARSER.md](DATETIME_PARSER.md)
for the public analysis API, pending-date flow and numbered-paste preview.

## Calendar policies

- `hoy` is today; an expired clock is rejected, never rolled to tomorrow.
- `mañana`/`manana` is always tomorrow, regardless of today's clock.
- A bare weekday selects its next future occurrence, including today if future.
- `próximo` (prefix or suffix) excludes today when the weekday matches today.
- `este` without `próximo` refers to the current week; a past request is rejected.
  In the user's `este lunes próximo` form, `próximo` determines the next occurrence.
- Numeric day + Spanish month uses the stated year or the current year; expired
  dates are rejected, not moved silently to another year. A stated weekday must
  match the calendar date and any stated `este/próximo` modifier.
- All deadlines use the existing user timezone / local-clock deployment contract.
  No timezone, data schema, default hour or existing schedule is changed.

## Safe rejection and exclusions

No hour is invented for date-only requests. Conflicting/repeated dates or clocks,
invalid calendar values, partial years, signed/decimal clocks, time ranges,
unsupported clock arithmetic (`y media`, etc.), Spanish recurrence and period
phrases (`de la noche`, etc.) are rejected. Spoken-number dates, arbitrary language,
voice input and notes/tasks without deadlines are not implemented here.
Known reserved temporal words inside an ambiguous title can cause conservative
rejection. This is preferable to silently dropping requested timing.

## Verification

- TDD: observed failing today/tomorrow, weekday, compact/dictated clock, numeric
  calendar, recurrence/clock-ambiguity, partial-year and modifier-conflict tests
  before their fixes.
- Full isolated suite: **220 passed, 3 xfailed**; Ruff passes.
- **29/29 history safety contracts pass unconditionally**. Fourteen previously
  pending compatibility cases are promoted only after an unconditional audit;
  expected deadlines/titles/timezone/reference-error oracles are unchanged.
- 14 positive history integration cases prove real handler -> SQLite -> scheduler
  -> database reopen -> job restoration with the expected deadline, preserving a
  pre-existing user's reminder. Rejection tests also cover missing-hour requests.
- Original private history: 26 inputs checked, zero scheduling differences versus
  anonymized fixtures; 17 accepted, 9 safely rejected under the explicit-time policy.
- Remaining 3 compatibility xfails concern legacy English `half a hour`, and
  English expressions containing version/URL date-like payloads. They are not
  falsely counted as supported features and do not hide safety failures.

Deployment remains a separate release gate: use an exact-commit image with unchanged
installed dependencies, a real owner-scoped disposable-DB delivery control, a
verified database backup/restore, preserved prior image/Compose, and unchanged
historical rows / unrelated services after cutover. Do not replay history into the
production database.
