# HTML-history datetime support

The phase-1 parser is deliberately bounded and offline. `app.nlp.analyze_datetime`
returns a `DateAnalysis` with exactly one of these statuses:

- `complete`: `due` and the cleaned `message` are safe to schedule.
- `missing_time`: `target_date` is frozen, but the user must supply one explicit
  clock. `parse()` returns `None` for this status.
- `past`: the requested date/time is already expired. It is never moved to
  tomorrow or another future occurrence.
- `invalid`: malformed, conflicting, repeated, or unsupported temporal input.

`app.nlp.parse` remains the safe scheduling contract: it returns a
`ParsedReminder` only for `complete`, otherwise `None`. Use
`app.nlp.combine_pending_date(target_date, clock_text, now=...)` to apply a
later clock to the stored date; it does not reparse the original words.

## Accepted phase-1 forms

- English weekday: `Saturday at 9:00 AM`, `next Sunday at 1:54 PM`,
  `this Tuesday at 09:00` and bare weekday forms.
- English month ordinal: `August 29th, 2027 at 9:00 AM`.
- Numeric day-first dates in both Spanish and English: `DD/MM/YYYY`,
  `DD/MM/YY`, and `DD-MM-YY`. A two-digit year is explicitly `20YY`; there is
  no locale or `strptime` pivot. `MM/DD` is invalid, including `12/31/2026`.
- Past summaries: `yesterday at 10am`, `7 hours ago`, and `4 hours ago` are
  classified as `past`, never as future reminders.

`app.nlp.analyze_batch` parses numbered multiline input independently and
returns per-line `BatchItem` statuses. It never shares the first line's clock.
`app.services.batch.serialize_batch` stores a preview. The handler's
`/confirm` uses `confirm_batch` to create only still-future `complete` items in
one transaction; incomplete and past lines are not silently scheduled.

## Pending drafts

`PendingDraft` and `PendingDraftRepository` are owner-scoped SQLite state with
an expiry time. Drafts and batch previews use a bounded **24-hour TTL**; the
handler removes expired state when it is read. `Database.create_all()` creates
the additive tables. A date-only message creates no reminder or scheduler job;
the next clock reply combines with the persisted date. A numbered batch is
routed as a new preview even when a draft exists. `/cancel` removes both the
draft and batch preview. Existing reminder rows and serialized schedules are
not rewritten.
