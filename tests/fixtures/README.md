# Skeddy history-derived parser contracts

## Provenance and privacy

These are **anonymized/adapted temporal patterns**, not a public copy of a chat.
The source export contained 169 non-service messages (61 user, 108 bot).
26 unique relevant inputs were selected; 35 other inputs were classified as
commands (10), setup/menu (22), duplicate note prompts (2), or non-text (1).
Three clearly labeled counterfactuals were added: tomorrow before the requested
clock, a model-version token, and a non-sensitive example URL containing a date.

Every personal task body becomes `payload_alpha`. Original titles, names,
project identifiers, Telegram message IDs, `/open` identifiers, access links,
and the source-to-case mapping are not committed. Private source provenance and
raw-input audit results remain outside this repository in protected local files.
Comparing original and anonymized inputs found no scheduling/kind/exception
classification changes across the 26 source-derived cases.

## Oracle rules

- Freeze the received **local** timestamp, including seconds, and attach
  `America/Mexico_City`; do not compare naive UTC against local deadlines.
- Exact user time expressions define the desired deadline. A rounded bot
  response such as `in 11 hours` is not an exact timestamp oracle.
- Check deadline, task-payload preservation, removal of temporal fragments
  from the title, and preservation of non-temporal model/URL text separately.
- Two reference-bot confirmations contradict the requested weekday. Their
  reference deadline is retained as evidence but **not** used as a golden answer:
  Friday was confirmed as Wednesday; next Sunday as Monday.
- Six requests lack an explicit clock. Skeddy's observed noon default is kept
  in `observed_reference_due`, not `expected_due`. Choosing a Toddy default hour
  versus asking the user remains a product decision; current contract is safe
  rejection, not silently inventing 09:00 or adopting noon.
- Note/task creation without a clock and editing an existing note are outside
  the standalone parser. No-time inputs must not generate an arbitrary deadline;
  the `18:00` case checks the clock token only, not a complete edit conversation.

## Two independent contracts per case

1. **Compatibility:** produce the intended schedule and clean payload, or reject
   when a time/default-hour policy is deliberately undefined.
2. **Safety:** return either the correct interpretation or `None`; never silently
   accept a partial/wrong interpretation.

Only pending **compatibility** gaps use
`xfail(strict=True, raises=AssertionError)`. They are **not passing features**.
Safety assertions are unconditional: they cannot be hidden behind xfail, and
fixture metadata requires every safety baseline to be `pass`. Unexpected parser
exceptions are not absorbed as expected failures; a compatibility improvement
produces strict XPASS until its baseline is reviewed. No expected deadline is
computed from the parser under test.

For an unconditional red/green release audit, disable expected-failure marks:

```sh
SKEDDY_HISTORY_STRICT=1 python -m pytest tests/test_skeddy_history.py -q --tb=short
```

Established isolated runner (source mounted read-only, no credentials or network):

```sh
docker run --rm --network=none \
  --mount type=bind,source=/home/rdos14/projects/skeddy,target=/app,readonly \
  --env SKEDDY_HISTORY_STRICT=1 skeddy-qa:baseline \
  python -m pytest tests/test_skeddy_history.py -q --tb=short -p no:cacheprovider
```

## Measured baseline (parser commit 95e7f91)

- 29 temporal cases: 26 from history plus 3 counterfactuals.
- 3 exact requested forms are understood; 4 more are safely rejected as
  unimplemented. Other passing contracts include safe no-time/policy rejection
  and the clock-only context case; these are not proof of complete task support.
- 11 cases accept a wrong deadline; 2 more retain unconsumed temporal words
  despite a coincidentally correct deadline. A counterfactual proves the Spanish
  tomorrow case fails when the requested clock has not already passed today.
- Strict history audit: **31 passed, 30 failed**. These 30 assertions are
  17 compatibility gaps plus 13 safety gaps, not 30 distinct input phrases.
- Full default suite: **92 passed, 30 xfailed**; Ruff passes.

## Point 1 candidate: conservative Spanish temporal rejection

The original audit above remains historical evidence. Current fixture safety
baselines track this candidate, not the old 95e7f91 behavior. Intent/deadline,
timezone, payload and reference-bot error oracles were not changed.

- Root cause: a recognized clock could select today's/tomorrow's fallback while
  Spanish temporal words survived because the residual guard knew only Uzbek
  and English. Extend that guard; do not implement Spanish scheduling.
- Reject known Spanish day/date/unit markers and contextual month phrases.
  Word boundaries preserve identifiers such as `backup_miercoles`; month names
  require a date-like preposition so `llamar a Julio` remains a valid payload.
  This is a bounded conservative vocabulary, not universal language detection;
  reserved temporal words in a title can still cause safe rejection.
- RED evidence: 13 history safety assertions failed before the fix; a real
  temporary SQLite handler test confirmed an invalid request created rows.
  Additional non-weekday timing controls failed 14 assertions before coverage
  was extended. A `Julio` payload regression was observed and fixed with a
  contextual month guard.
- GREEN: **29/29 history safety cases pass without xfail**. Full suite:
  **159 passed, 17 xfailed**, with Ruff and formatting checks passing. Remaining
  xfails are only unimplemented compatibility, not unsafe acceptance.
- **34 real SQLite/scheduler integration cases** cover empty and pre-populated
  databases, no added users/reminders/jobs, preserved existing row values and
  triggers, and persisted equality plus integrity after reopening the database.
  Only the clock and Telegram I/O are substituted; parser/repositories/scheduler
  are real. The scheduler is not started and no notifications are sent.
- No deployment, production database writes, reinterpretation of stored
  reminders, token, webhook or polling changes. Review this candidate before
  authorizing a production cutover. Rollback of development work is the parent
  commit f0b9fd8; production still uses the preserved 95e7f91 image.

Safety-only audit (unconditional in both normal and strict modes):

```sh
python -m pytest tests/test_skeddy_history.py -k returns_correct_intent_or_rejects -q
```

## Remaining roadmap, not implemented here

Correct Spanish weekdays/today/tomorrow and accented speech-to-text forms,
compact clocks (`830am`), fractional durations (including the user's exact
`half a hour` spelling), spoken dates, non-temporal version/URL handling, and an
explicit default-hour/task policy remain separate work. Agree each scope before
implementation. Point 1 changes rejection only, not supported reminder grammar.
