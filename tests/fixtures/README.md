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

Known gaps use `xfail(strict=True, raises=AssertionError)`. They are **not passing
features**. Unexpected parser exceptions are not absorbed as expected failures;
an improvement produces strict XPASS until the fixture's baseline is reviewed.
No expected deadline is computed from the parser under test.

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

## Candidate roadmap, not implemented here

Prioritize safe rejection of unsupported Spanish temporal phrases before
partial AM/PM clock matching, then Spanish weekdays/today/tomorrow and accented
speech-to-text forms. Follow with compact clocks (`830am`), fractional durations
(including the user's exact `half a hour` spelling), spoken dates, non-temporal
version/URL handling, and an explicit default-hour/task policy. Agree each scope
before implementation. This change adds tests only: no parser code, deployment,
production schedules, tokens, webhooks or live test notifications were changed.
