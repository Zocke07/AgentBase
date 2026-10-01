# Verification and remaining work

Updated 2026-10-01. This is the current record; [history](history/README.md)
holds earlier evidence and superseded gaps under original identifiers. Results
cover only work actually executed.

## Phase 17 and run-review UX, 2026-10-01, on `main`, not released

### Tool calls resent with their results, 2026-10-01

The maintainer's first acceptance **Run now** of the morning collection after
the repair below (run `8de6694a`, 21:47 Taipei) collected nothing.
`market-movers` on Claude Haiku 4.5 read `config/watchlist.json`, which
answered correctly, then made the identical read twice more, and the stuck
guard stopped it. A second spawn, told to read the file once, did the same.
The supervisor then stopped as its goal requires, and Theses and risk did not
start ("Morning collection had no verified read_prices result").

- **Cause.** `Message` had no place for an assistant turn's calls, so the loop
  kept only the prose, or `(tool call)`, and every adapter sent a history in
  which the model had never called anything. Anthropic received each result
  as a plain user turn, and the ChatGPT transport saw results whose IDs no
  call carried. OpenAI Chat Completions refuses a `tool` turn without a
  preceding `tool_calls`, so a worker's second request on an API key would
  have failed outright.
- **Not only Haiku.** The two pre-repair backups (16 runs on GPT-5.6 Luna and
  Terra through ChatGPT) hold seven agents stopped by the guard for the same
  reason: five `market-movers` spawns in four runs re-reading
  `config/sources.json`, `decision` re-listing the space and `bear-architect`
  re-reading the movers file.
- **Fix.** `Message.tool_calls` carries the calls. Anthropic gets `tool_use`
  blocks, with every result of one answer as `tool_result` blocks in the next
  user turn. OpenAI gets `tool_calls` with string arguments before each `tool`
  turn. Ollama gets object arguments, with the tool named in each result. The
  ChatGPT conversation shows each call beside its result. A cut-off answer's
  calls never ran and stay off. `llm.request` logs each turn's calls and each
  result's call ID, repeating arguments as it already repeats results; logged
  runs replay unchanged. `estimate_usage` counts resent arguments, so the run
  and monthly pre-flight checks stay upper bounds (test written first).
- **Executed:** nine new tests, each failing before the change except the
  cut-off guard; ruff, format and `mypy --strict` on both platforms; the full
  backend suite, **1083 passed, 12 skipped**, with the two existing warnings.
  No frontend file changed, and the frontend checks were not rerun. A one-off
  `read_prices` for AAPL into a scratch folder, not the space, succeeded at
  22:12 Taipei.

Not verified: a real model on the corrected history. The running dev app keeps
the old sidecar until it is restarted (`just dev-app` rebuilds it).

**Found, not changed:** during US trading hours (21:30 to 04:00 Taipei) the
chart's last bar is the session in progress, and `read_prices` counts it as
complete. At 22:12, AAPL's 2026-10-01 bar held 6.4 million shares against a
20-day mean of 42.3 million. A Run now in a Taipei evening writes that partial
session as `raw/movers-2026-10-01.json`, and the next 07:00 run then finds no
newer session and stops the chain.

### Live-run repair and fresh-start reset, 2026-10-01

The maintainer's October 1 screenshots and an explicitly authorised inspection of
`.dev/data` showed three completed runs that had not achieved their goals.
Morning collection had 16 tool failures, including Stooq 404 and Yahoo 429;
its saved movers file was an empty array. Theses and risk then wrote empty
thesis files and a risk file without a computed portfolio. Daily decision
reported a pass at 0% despite missing inputs. The same install's five
affected agent definitions still had old shipped prompts and tool lists:
migration 021 had treated a model-only edit as a complete user edit. A
`market-movers-2` graph node was a second spawn, not a separate roster entry.

- Migration 022 (`155294c`) upgrades only exact old shipped prompt and
  allowlist matches even when `updated_at` differs from `created_at`. Its
  regression tests preserve chosen models and genuinely edited instructions.
- The seeded morning and theses schedule followers now require successful
  tool evidence, not merely a completed run (`4392669`). Tool/model errors,
  failed price symbols, no new session, missing portfolio calculation, missing
  hard-rule checks or missing dated risk review block the next stage. Tests
  cover these cases and unchanged generic schedule behavior.
- Before each of those commits, `just check`, the full backend suite, and
  the full desktop suite passed with `set -o pipefail`: first **1068 passed,
  12 skipped**, then **1074 passed, 12 skipped** on the backend; each had two
  existing warnings. The desktop suite passed **53 files, 555 tests** each
  time. No automated test made an external network request.
- For this documentation and live-repair handoff, `just check` passed and the
  full backend suite passed again. The first desktop run timed out in the
  existing replay-identity test after 554 other tests passed; an unchanged
  full-suite rerun passed all **53 files, 555 tests**. The backend run needed
  the usual native-binary semaphore access after a sandboxed attempt stalled.
- With the app closed, a consistent database backup and copy of the Main
  space were saved at `.dev/backups/phase17-repair-67N7Wx/` and SQLite
  reported `integrity_check=ok`. The live database migrated from schema 21 to
  22, retaining the affected agents' selected GPT models. Its saved host list
  was changed from Google News and Stooq to Google News, Yahoo chart and the
  Treasury API. The old Stooq source descriptor was replaced, AAPL gained the
  required sector, and the missing zero-cash `positions.csv` starter was
  added. The packaged sidecar binary was rebuilt successfully.
- Exactly three completed runs, their 704 events and 74 approvals, and their
  schedule last-run markers were removed. The generated `raw`, `theses`,
  `risk`, `decisions`, `memory/runs` and knowledge-backup folders were moved
  into that recovery backup. The live space now contains only the three
  configuration files and the portfolio starter. All 283 spend ledger rows
  remain, so deleting history did not erase incurred costs or bypass limits.

Not verified: a real model and the live Yahoo and Treasury services after
this repair; Yahoo's unofficial endpoint may still return HTTP 429. If it
does, the daily chain now stops and reports the failure instead of writing a
decision from empty data. The maintainer should restart the dev app so it
loads the rebuilt sidecar, enter actual holdings and cash when available, then
perform Phase 17's first acceptance run and inspect the tool results.

Phase 17 now implements the investment pipeline designed on 2026-09-30. The
work was built and committed one test-first unit at a time: Sonnet 5.5 and
migration 020 (`8ccf628`); `read_prices` (`b6b0824`);
`compute_portfolio` (`2d2ff29`); `check_limits` (`192677a`);
`score_predictions` (`6ff1a7c`); migration 021 and the three-host default
(`459542c`); and the nine starter files and dashboard (`687da47`).

- **Models and migration.** Claude Sonnet 5.5 is the current Anthropic
  balanced model. Fresh spaces start on Sonnet 5.5, GPT-6 Sol, or GPT-5.6 Sol
  through a ChatGPT plan. Untouched shipped Sonnet roles move in migration
  020. The shipped `decision` role retains its strong intent across GPT-6 Sol,
  including GPT-5.6 Sol on a plan. Used spaces and edited definitions stay put.
- **Deterministic tools.** All four tools are medium risk. `read_prices` uses
  Yahoo's keyless unofficial chart endpoint and recorded JSON fixtures;
  `compute_portfolio` writes exact book and weight files; `check_limits`
  writes hard-rule results and headroom; `score_predictions` appends resolved
  predictions once and writes the monthly scorecard plus stable accuracy and
  calibration files. No test uses the network.
- **Pipeline wiring.** Migration 021 gives untouched roster definitions their
  tools, updates untouched schedule goals, and handles migration 019's seeded
  schedules without misclassifying every install as used. Fresh installs list
  `news.google.com`, `query1.finance.yahoo.com`, and
  `api.fiscaldata.treasury.gov`; used installs retain their saved list or the
  former default. The event collector now uses only configured Treasury URLs,
  removing the SEC, BLS, and issuer requests that failed in the maintainer's
  runs.
- **Starter input.** On 2026-10-01 the maintainer allowed a suggested starter
  universe. Six illustrative watchlist companies across distinct sectors now
  make a first collection possible, without creating a holding or cash balance.
  Home asks the person to review the list, enter real positions and cash, and
  set personal limits. It creates sources, default limits, a zero-cash positions
  template, four stable chart definitions, and the dashboard without replacing
  existing files.
- **Run audit.** The captured runs did not satisfy their goals. Stooq returned
  404, SEC and BLS returned 403, an issuer page returned 404, and the old
  prompts then looked for `portfolio/computed.json` and dated risk output that
  no shipped step could produce. A later decision stage honestly wrote a pass
  at 0% only because those inputs were absent. The new price, portfolio, limit,
  and scoring tools remove those missing producers; the narrowed calendar
  removes the known failing sources.
- **Run-review UX.** Visualize and Usage have distinct icons; Knowledge uses
  Notes, Agent files, and Saved context; cards and text containers wrap without
  fixed-width clipping; Markdown preview uses the available width; Usage has a
  visible Y axis whose ticks scale from actual daily values; Runs presents
  dense results and errors more clearly; the app chrome uses the AgentBase
  network mark; saved context defaults to conservative model-assisted
  management with audit reasons and backups; and Automations **Run now** is
  labelled separately from a timed schedule start.
- **Configuration and light theme.** The Agent files editor now explains what
  every pipeline starter feeds and which fields are actually consumed. The
  compact AgentBase mark uses dedicated light and dark brand colours, with no
  blurred shadow in the light rail.

The Sonnet 5.5 entry was checked again on Anthropic's official models overview
on 2026-09-30 before implementation: `claude-sonnet-5-5`, released
2026-09-28, $2 per million input tokens and $10 per million output tokens, 1M
context, 128K maximum output, and retirement no earlier than 2027-09-28.

- **Gate.** Before the final implementation commit and again for the
  documentation unit, `just check` passed; backend **1067 passed, 12 skipped**
  with two existing warnings; desktop **52 files, 553 tests**. The first
  documentation backend attempt reached **1061 passed** but the sandbox denied
  the frozen binary's system semaphore; the identical unrestricted rerun
  passed all 1067 tests.
  For the 2026-10-01 configuration and light-theme unit, `just fmt-desktop`
  and `just check` passed, followed by the full backend suite (**1067 passed,
  12 skipped, two existing warnings**) and desktop suite (**53 files, 555
  tests**), with `set -o pipefail` set for the gates.
- **Browser.** A scratch sidecar used a temporary `AGENTBASE_DATA_DIR` and
  port 8790; Vite ran on 5173; Chrome requests for 8787 were rewritten over
  CDP; onboarding was disabled through `PATCH /settings`. At 1440 and 800 px,
  the fresh host settings, Home setup card, all nine created files, all five
  enabled schedules, and the four-chart dashboard were checked. Seed data was
  written only to the scratch space for the charts. There was no horizontal
  overflow, field error, or console error. The maintainer's `.dev/data` was
  not used for these UI checks.
  A later light-theme pass used the same topology with a fresh schema-21 data
  directory. At 1440 by 900 the rail mark rendered at 24.75 px with its light
  palette, no filter, and no horizontal overflow.
  The 2026-10-01 starter pass used another temporary schema-21 directory on
  port 8790. Headless Chrome on Vite 5173, with CDP rewriting 8787 requests
  and onboarding disabled by `PATCH /settings`, showed the six watchlist
  symbols and sectors in the Agent files template. The setup card named the
  illustrative list and current Agent files tab. At 1440 and 800 px there
  was no horizontal overflow, UI alert, or page exception. A screenshot was
  inspected for the light logo and editor layout. No live data was touched.
- **Not verified.** No real model has run the daily morning-to-decision chain
  after these changes.
  The live Yahoo and Treasury services are deliberately absent from automated
  tests. The packaged Tauri/WebKit app and Windows build were not rerun for
  this phase.

The maintainer must perform Phase 17's first acceptance test: fill the
watchlist and positions, choose **Run now** on Morning collection with a real
model, let the Theses and risk and Daily decision stages follow, and confirm
the event log contains successful tool results and the space contains movers,
prices, portfolio figures, hard-rule checks, and `decisions/{date}.md`. Every
figure must trace to a `tool.result`; model prose alone is not evidence that a
tool ran.

## Investment pipeline audit, 2026-09-30, historical pre-build audit

The shipped roster was compared with the maintainer's plan and standalone
roster design, and that design was folded into BUILD_SPEC Phase 17 and the user
guide. What the audit found is in Phase 17; the implementation above addresses
the in-scope gaps.

The data sources were probed once with `curl` from the maintainer's Mac:
- `news.google.com` RSS answered with 112 KB of XML.
- `stooq.com` returned HTTP 200 with a JavaScript browser check instead of
  its CSV, both with and without a date range.
- Yahoo's chart endpoint returned JSON for `AAPL` (a year of daily history:
  251 sessions, 28 KB) and for `2330.TW`.
- Nasdaq's history API returned JSON when sent a browser user agent.
- TWSE's open data returned the day's listing as JSON.
- The Treasury's auctions API returned JSON.
- `bls.gov` returned 403 to a program with no identifying header.
- The Fed's FOMC calendar page was 165 KB of HTML.

The maintainer's own install showed three gaps:
- `decision` on GPT-5.6 Terra, by way of GPT-6 Sol, after a provider switch
  and a plan repair.
- A lone decision stage writing a correct "pass" for want of inputs.
- A space folder with no `raw/`, `theses/`, `portfolio/` or `scores/` files.

Anthropic's models overview and deprecations pages were read on the same day:
- Claude Sonnet 5.5 (`claude-sonnet-5-5`, released 2026-09-28) at $2 and $10
  per million tokens, the same as Sonnet 5, which became legacy.
- Opus 5.5 at $4 and $20, matching the price list.
- Claude Haiku 4.5 active, with no deprecation announced.

Phase 17's models unit uses these figures. At the time of this audit, nothing
was built or run beyond these reads.

## Visualize and Usage refinements, 2026-09-29, on `main`, not released

From the maintainer's screenshots:
- `config/limits.json` charted as one bar group labelled "10".
- The Values checkboxes squeezed their labels against the far edge.
- The legend cut names short.
- Usage drew a single day of spend as one bar across the whole chart.
- An open Usage showed $0.1374 while the header showed $0.16.

- **Gate.** `just check` passed; desktop **49 files, 529 tests**; backend
  **1017 passed, 12 skipped, 1 failed**, the failure being the hygiene test on
  the same untracked file outside this work.
- **Tests first.** The new parsing and first-chart tests failed on the old
  code. They cover:
  - flat, nested and keyed JSON objects;
  - a movers file and a theses file shaped as the roster's prompts describe;
  - averaging a repeated category, and counting the rows a plain chart leaves
    out.
  New chart tests cover round axis steps, a bar width cap and whole legend
  names that wrap. New Usage tests cover a slot for every day and reading
  the report again when the header's total moves.
- **Browser.** A scratch sidecar on port 8790, Vite and headless Chrome, at
  1440 by 900 and 900 by 800. Results:
  - limits drew as three bars on a 0, 10, 20, 30 axis;
  - sources drew as a table;
  - movers and theses drew by ticker, the theses as "3 groups from 5 rows ·
    average";
  - checkboxes were 13 px wide;
  - Usage showed 30 day slots with narrow bars;
  - there were no console errors.
  The first pass found the chart clipped at 900 px, a layout that predates
  this work, and the Usage baseline broken; both were fixed and checked again.
- **Not checked.** The light theme and the dashboard editor's checkboxes were
  not looked at, though the same rule serves both. Usage following the header
  was checked in unit tests only.

## ChatGPT plan models, 2026-09-29, on `main`, not released

A signed-in ChatGPT account refused GPT-6 Sol, the space's model, with an
HTTP 400 from Codex. `8cef8c2` reads the account's Codex `model/list` and keeps
pickers, new-space defaults and tier mappings to it; the review fixes that
followed are covered below.

- **Gate.** `just check` passed (ruff, format, mypy on the host and
  `--platform win32`, eslint, tsc); backend **1016 passed, 12 skipped, 1
  failed**, the failure being the hygiene test on an untracked file outside
  this work; desktop **49 files, 518 tests**. `just schemas` changed nothing.
- **Review.** Two read-only reviewers and a verifier ran. The correctness
  reviewer failed after five restarts and the verifier was interrupted, so
  each of the constraints reviewer's six findings was checked against the code
  by hand; all six held and were fixed. The worst: a repair that moved only
  agents could not be saved, because the form counted only space fields as a
  change. Its new test failed on the old code.
- **Tests.** New tests cover the agents-only repair and the check after it,
  the offer disappearing when access leaves the plan and returning when the
  section is shown again, Home sending a missing model to Space settings, the
  app-wide check leaving the backing model alone, a provider change and the
  catalogue default keeping to the plan, a plan with no priced model, and a
  model list the SDK cannot read.
- **GPT-6 Sol to GPT-5.6 Sol.** At the maintainer's choice a space on GPT-6
  Sol is offered GPT-5.6 Sol, the plan's strong model; agents keep GPT-6 Sol's
  own tier (GPT-5.6 Terra). Its tests failed first and then passed; the gate
  above passed again with it (backend 1017 passed). Of its two reviewers, the
  documentation one found the user guide giving a false reason, now reworded;
  the call-site one did not finish, so the two call sites (the pre-flight
  suggestion and the Space settings repair) were checked by hand.
- **Live.** These checks ran against fakes of the runtime and the Codex
  client. The maintainer's own Usage screen then showed a scheduled stage run
  through a signed-in plan on GPT-5.6 Sol and GPT-5.6 Terra (7 calls,
  $0.1374 at API-equivalent prices).

## Autonomy first (Phase 16), 2026-09-29, branch `autonomy-first`, not released

Built on a separate worktree branched from `main` at `b718844`, so the
maintainer's checkout and other sessions were untouched. Nothing was pushed,
tagged or version-bumped.

- **Gate.** On the branch head: `just lint typecheck` passed (ruff, format,
  mypy on the host and `--platform win32`, eslint, tsc); backend **986 passed,
  26 skipped**; desktop **49 files, 510 tests**; the hygiene test passed.
- **Test-first units.** The sandbox guard on app-owned paths, the host list and
  the projected cost ceiling had failing tests before their code. New backend
  tests cover the high-risk invariant at the gate, settings, spaces and 017;
  018 against used and fresh databases (a run, a saved setting, a schedule, a
  space of its own; an answer already saved is kept); 019's guards (an edited
  agent and a deleted agent); the unattended expiry and its precedent; the
  supervised run; `run.started`'s policy record; Run now; the interrupted
  re-run; chains (loops, depth, other spaces, deletion, a failed or cancelled
  stage, closing) including one chain through the real launcher and hook; and
  the Discord approval view.
- **Browser.** A scratch sidecar (fresh data directory, port 8790) and Vite in
  headless Chrome over CDP, at 1280 by 900: the rail order; the fresh install's
  defaults (Autonomous, `news.google.com, stooq.com`, 120 seconds, originator,
  no high tick, `run_shell` offering only ask or deny); the five seeded
  schedules off; **Turn on the daily pipeline** writing the three templates
  and enabling all five; Automations showing each stage and the next time;
  the unattended readout; the demo run's policy line and "allowed by policy
  (low risk runs on its own)" in its log; no console errors. The first pass
  found Automations still showing the stages off after Home turned them on
  (sections stay mounted); fixed and checked again, and the whole check ran
  once more on a fresh data directory after the review's fixes.
- **Adversarial review.** A workflow of three read-only reviewers (safety
  and constraints, backend correctness, frontend) and one verifier that tried
  to refute each finding reported 21 findings; the verifier judged 19 real
  (two pairs were duplicates). The first attempt returned nothing because every
  reviewer hit the session limit; it was run again. Fixed with tests: on
  Windows a trailing dot or space in a write name (`notes/lesson.md.`,
  `memory./x.md`) got past the memory guard, since Windows drops it as it
  creates the file (refused now, whatever the platform); an upgraded install
  choosing Autonomous kept the pinned `*` host list; an interrupted chain
  stage re-ran beside its head at launch (reproduced by the verifier); an
  expired question outranked a later yes for the run; a stale repeat-this-goal
  draft reopened on a space switch; a pipeline turn-on stopped at a refusing
  stage; `hidden` did not hide the missed-time choice (the class sets
  `display`); a case-variant data file could be overwritten; Home could act on
  a list still loading from another space; schedule times went stale while
  idle; a blank unattended wait saved as 0; the agent editor hid an older
  `high` level; and several sentences were false in edge cases (a refused
  shell "always asks", an unanswered call "denied by your answer", a
  Supervised space with an always-allowed tool). Two findings were rejected as
  the design's intent (a yes for the run covers any host of that tool; Run
  now gets the scheduled wait). Recorded as not built: a cap on concurrent
  scheduled runs, and the native window title.
- **Not verified.** A real model running a scheduled chain end to end in the
  packaged app; a live Discord question answered with **Allow for this run**;
  the Windows build, including the trailing-dot refusal on NTFS itself (the
  check is on the name, so it is platform independent, but no Windows host
  ran it); a screen reader.

## 0.4.8: steady canvas, folding log, start-up stages, spend breakdown, space providers

Released 2026-09-28 from a separate worktree at the 0.4.7 commit carrying only
this work: the maintainer's checkout also held another session's uncommitted
comment pass, which stays uncommitted there.

- **Canvas flicker.** `layout()` rebuilt every React Flow node on each event
  without `measured`, so React Flow dropped its handle bounds and unmounted
  every edge until it measured again. In headless Chrome, a MutationObserver
  counted edge and label removals while 493 simulated events (three token
  streams) went through the run store at two per frame: **1,066** before,
  **6** after (the first draw), with all 4 edges and 2 labels drawn at the end.
  jsdom draws no edges, so `graph.test.ts` checks the cause. Remaining layout
  shifts happen once each: the approval panel appearing and going, and the
  supervisor's account arriving at the end.
- **Folding log.** In Chrome at 1024 by 700 the folded log was 36 px against
  128, the canvas 296 px against 204; unfolding restored the newest row, and
  the choice persisted.
- **Start screen.** Checked in Chrome against a port with nothing listening:
  the six-second note appears and no retry count is shown.
- **Spend breakdown.** Checked in Chrome with seeded spend; it fits the 800 by
  600 window.
- **Models.** Prices checked against both providers' pages on 2026-09-27.
  Migration 016 ran on a real v15 database: the default space gained
  `anthropic`, moved to Opus 5.5, and the untouched `decision` agent moved too.
  Switching that space to OpenAI in Chrome listed all ten roster agents, and
  saving moved the space and every agent (Haiku to Luna, Sonnet and Opus to
  Sol). The contrast audit found no failures on the new panels in either theme.

The browser checks ran on the maintainer's checkout, whose extra changes are
comments and two equivalent loader rewrites. On the release tree itself:
`just check` passed; desktop **49 files, 477 tests**; backend, including the
DNS-bound files and the tree-wide hygiene test, **892 passed, 26 skipped**. Not
checked: the Tauri window (WebKit), where the flicker was reported; a real
model run; a screen reader. The tag workflow builds, smoke-tests and publishes
the installers.

## 0.4.7 local release gate, 2026-09-26

The 0.4.7 candidate adds bounded RSS/Atom, safe `news-scanner` migration,
clearer missing-key guidance, and responsive/accessibility work over 0.4.6.
`just check` passed backend Ruff/format, native/Windows strict mypy, desktop
lint, and TypeScript. Backend (excluding artifact/hygiene checks): **849
passed, 4 skipped**. Hygiene: **15 tests**, with only tree-wide em dash
deselected for the maintainer's untracked document. Desktop: **47 files, 456
tests**.

Apple Silicon sidecar freeze, production frontend/Rust builds, and ad-hoc
signing completed. `cargo clippy --all-targets -- -D warnings` passed; `cargo
test`: **7 tests**. Required artifact verification launched the frozen sidecar
and inspected the bundled app/mounted disk image: **18 passed, 4 Windows-only
skipped**. `AgentBase_0.4.7_aarch64.dmg` is 27,924,355 bytes, SHA-256
`88ab2ec44414d609974c4279c8f2d8aed08844e1687b525c40e63589dfc88efc`.
Tag workflow still gates publication and Windows installer.

## AgentBase product rename, 2026-09-24, released as 0.4.6

Product, backend/TypeScript/Rust packages, Tauri bundle/sidecar, environment,
schemas, CI artifacts, and current docs use AgentBase. First canonical launch
can adopt an empty new app-data directory, renaming SQLite plus WAL/SHM without
overwriting an existing profile. Legacy keychain/browser/schema values remain
readable; writes use AgentBase.

Executed: the full backend suite (**868 passed, 12 skipped**), backend Ruff
lint and format checks, mypy strict on both the native and cross platform,
the desktop suite (**47 files, 453 tests passed**), desktop lint, typecheck
and production build, a sidecar freeze, `cargo clippy --all-targets`, and
`cargo test` (**7 passed**, including the legacy-keychain-entry precedence
tests). The pinned Codex runtime dependency download that stalled a prior
attempt in this environment completed on retry, in about 25 minutes.

## After 0.4.5: a plainer, responsive and accessible window

On 2026-09-26, at the maintainer's request, the window was reworked for
people without a technical background, for the 800 by 600 minimum window,
and for keyboard, screen-reader and reduced-motion users, with motion added
to its chrome. Before any change, every section was screenshotted at 1440 by
900 and 800 by 600 against a scratch sidecar. Found: at 800 px, 171 elements
in Runs spilled past the right edge (the replay bar reserved 22 rem, and the
run area's grid had no column template, so its column took its widest child),
and at 600 px tall the run's title and summary row collapsed to 0 px; light
theme text in `--faint` measured 2.6:1 and white on the orange buttons
3.76:1; the folded rail hid its labels with `display: none`, taking them from
screen readers; there was no skip link and no `<main>` in the shell.

Changed: text tokens raised to AA (a contrast audit over Home, Settings and
Runs reports no failures in either theme, and reports 2.6:1 and 3.76:1 when
the old values are put back, so it is not vacuous); a skip link, one main
landmark, one focus ring, forced-colours rules; the rail folds below 1,100 px
and opens as a drawer; the run area, replay bar, log filters and form rows
wrap, and the run's summary keeps its first lines in a short window. Copy: a
header with the model's own name ("Claude Opus 5"), rounded spend ("$0 of
$20", exact figures in the tooltip) and **Finish setup** in place of "runs
will be refused"; the missing-key message without "keychain" or "sidecar"
(`providers/factory.py`); Home's setup card, task placeholder, a three-name
agent summary and **Preview notes**; plain start-up, reconnect and run status
words; Settings reordered so provider and keys come first, with a bar that
jumps between sections, a Save bar pinned to the window and key names in
words. Motion: CSS only, on sections, menus, the tour, toasts, buttons, cards,
the rail's active bar and skeleton placeholders, with exits through
`usePresence`; none on the canvas, log, approval panel or summary.

Executed: `just check`; **448 frontend tests** (new: `moneyShort`,
`modelLabel` and `providerLabel`; the budget meter's glance and tooltip; the
loading state by its accessible name) and **797 backend tests** pass, with 7
skipped and the DNS-bound `test_sandbox.py` and `test_tools.py` deselected on
this Mac; the one failure is the em-dash check on the maintainer's untracked
`agentspace-investment-agents.md`. In Chrome against the scratch sidecar: no
element past the right edge in any section at 800 by 600 or in Runs at 1024
by 700; the first Tab showed **Skip to content** and Enter focused
`main-content`; the space menu played `pop-in` and, on closing, `pop-out` with
clicks disabled, and was removed after it; under emulated reduced motion it
went at once and a section's animation measured 1 ms instead of 320 ms; the
tour rose in and sank out; the drawer opened with a scrim and closed on Esc;
the Settings **Keys** link jumped to its section with Save still in view.
**Not exercised:** the Tauri window itself, a screen reader, and Windows High
Contrast; the dark theme was checked by the contrast audit, not by eye.

## After 0.4.5: complete feed input for news-scanner

On 2026-09-26 a real `news-scanner` run received Google News RSS through
`http_get`'s 20,000-character model-facing limit. The XML ended inside an item,
so the scanner correctly refused unverifiable extraction and wrote an empty
array. The new `read_feed` tool keeps the existing public-address and
no-redirect network boundary, streams at most 2 MB, parses RSS or Atom locally
with unsafe XML features disabled, and returns at most 20 complete, bounded
entries. It normalizes dates and publisher domains, calculates reproducible
SHA-1 IDs and title deduplication keys, and removes exact or same-title
duplicates within 24 hours. Migration 015 moves only the completely untouched
built-in scanner to the tool and preserves edited definitions. Executed:
`just check`; **164 focused backend tests** for tools, the URL sandbox, roster
migration, registry and approvals (one Windows-only skip); **843 backend
tests** with eight platform or build skips after excluding the frozen sidecar,
mounted disk image and repository-hygiene files that this managed sandbox
cannot exercise cleanly; frontend lint and typecheck; **446 frontend tests**.
A live fetch of the failing AAPL Google News query read all 82 valid feed
entries and returned the requested 10 complete entries, each with a
40-character ID. The unrestricted backend invocation reached 863 passes and
eight skips; its remaining failures were the managed sandbox refusing DNS,
disk-image mounting and PyInstaller semaphores, plus an unrelated untracked
working document caught by the tree-wide prose check. The DNS-dependent tests
are now deterministic; the other exclusions do not exercise this change.

## 0.4.4: guards on runaway runs, a per-run cost ceiling, data files in the app

On 2026-09-19 the maintainer's first real `news-scanner` run spent 345k
tokens and $0.45 on eight steps that all failed alike: every answer was 4096
tokens out, the `write_file` call's JSON arrived truncated, `_parse_arguments`
turned it into `{}`, the tool said "needs a 'path'", and Haiku retried the
same oversized write at 68k tokens of context. Three guards followed.
`MAX_OUTPUT_TOKENS` raised the request's output limit from 4096 to 16,384; an
answer whose `stop_reason` is `max_tokens` or `length` no longer runs its
tool calls but logs a `tool.error` naming the limit and tells the model to
write less at a time; and an agent that fails the same way, or makes the
identical call, three times in a row completes with reason `stuck`, which
fails the run when the supervisor is the one repeating. A per-run cost
ceiling (`max_run_cost_micros`, $2.00 by default, 0 off; a space's own via
migration 014) is checked from the ledger before each model call like the
deadline, and the Schedules readout names it. Migration 014 is the fourth
column on `spaces` since 0.4.0. The Knowledge section gained **Data files**:
the plain-text files beside the notes, listed, edited and deleted through
new endpoints, JSON parsed before a write, three config templates offered
when the list is empty. Executed: `just check`; **790 backend tests** (new:
the cut-off answer not run and the nudge, the stuck agent after identical
failures, the stuck supervisor failing the run, the identical successful
call, the cost ceiling reached and the ceiling of zero, the file endpoints'
list, write, JSON refusal, path refusals, read, delete with backup); **434
frontend tests** (the Files panel's list, edit, JSON refusal, template and
delete; the stuck phrase). In Chrome against the scratch sidecar, migrated
to 14: a template was saved from the Data files tab, a second file typed
and saved, and both listed with their sizes; Settings showed $2.00 per run.
**Not exercised:** a real cut-off from a model, and a real run reaching the
cost ceiling; both rest on the scripted provider.

## 0.4.3: the provider change moves space models, news-scanner reads, folder delete, a folding rail

On 2026-09-19 the maintainer saw the header read "openai · claude-haiku-4-5"
after changing the app-wide provider: a space that inherits the provider was
keeping a model of the old one. `PATCH /settings` now moves every such space
to the new provider's default model (a space with a provider of its own is
untouched; Ollama's model is typed, so those become blank), and the
catalogue names each provider's default so the space page picks the same
one. Their first real run of `news-scanner` stopped on "cannot run without
access to configuration files": 010 shipped it with `http_get` and
`write_file` only, so it could not read `config/`; migration 013 adds
`read_file`, guarded on the allowlist still being what 010 wrote. The
Knowledge tree gained a folder delete (a second click, a copy of every file
under `.agentspace/backups/` first, `DELETE .../knowledge/folder`, the root
and hidden folders refused) and the rail a fold to icons (a button beneath
Settings, Ctrl/Cmd+B, remembered in the browser). Executed: `just check`;
**784 backend tests** (new: the provider change over the API and the
catalogue's defaults, the folder delete with its backup and refusals, the
roster's widened scanner); **430 frontend tests** (the rail folding from
its button and the shortcut, the folder delete's confirmation and toast).
In Chrome against the scratch sidecar, migrated to 13: the scanner's
allowlist read `["http_get","read_file","write_file"]`; a provider change to
openai moved both inheriting spaces to `gpt-5.5` and back to `claude-opus-5`
with the header following; the rail folded to 56 px with the space's
initial; a seeded `scratch/` folder was deleted from the tree after the
confirmation and its copy appeared under `.agentspace/backups/`.

## 0.4.2: the model on the space, the runs filter, schedule limits, the summary handle, full-screen canvas

On 2026-09-19, after 0.4.1: the supervisor's account gained a drag handle
(a height given makes it scroll, unfolded), the canvas gained a **Full
screen** control (fixed over the window, Esc leaves it, the run re-framed on
entering and leaving), and the **Answers by tool** hint was rewritten around
an example. Executed: `RunPanel.test.tsx` (full screen on and off, both
handles offered, the canvas handle withdrawn while expanded), **425 frontend
tests**, ESLint and `tsc`. In Chrome against the scratch sidecar: the
summary dragged from 197 to 137 px and scrolled with its fold gone; the
canvas filled the 1440 by 900 viewport at scale 1 and returned on Esc.

Then three more, at the maintainer's request, on 2026-09-19. **The model
moved to the spaces**: Settings chooses the provider only, every space names
its model (no Inherit; `api/spaces.py` fills the provider's default from
`DEFAULT_MODELS` on a create without one, a model set to null, or a change of
provider), the app-wide `model` stays as an unshown fallback that follows the
provider, and migration 012 gave each existing space the model it was
inheriting (an inheriting space the app-wide one, a space on its own provider
that provider's default, an Ollama space nothing). **The run list narrows by
origin** (`GET /runs?origin=`, a Show select above the list). **Schedules**
carry their own `max_run_seconds` (also migration 012), laid over the space's
by the launcher for that run alone, and the section's readout says in one
paragraph what an unattended run will do on its own (levels, always-allowed
and refused tools) and where it stops. Executed: `just check`; **782 backend
tests** pass (new: the space model rules over the API, the settings fallback
following the provider, migration 012 on a version-11 database with three
kinds of space, the origin filter, a schedule's limit reaching the launcher
and a bad one refused); **428 frontend tests** pass (Settings without a model,
a space refusing a blank model and moving it with the provider, the origin
filter re-reading from the first page, the readout merging the stricter
tool answer, the schedule editor's time limit). In Chrome against the scratch
sidecar, migrated 11 to 12: both spaces read `claude-opus-5`, Settings showed
no model select, Space settings offered "Inherit (anthropic)" and the model
list without Inherit, the readout read "runs read_file without asking
whatever the level, is refused run_shell; everything else asks and, with
nobody to answer, waits up to 600 seconds, then the run fails. It stops at 20
steps per agent, 5 agents and 600 seconds, unless a schedule sets its own
time limit below.", and the Scheduled filter listed the three scheduled runs
alone. **Not exercised:** a scheduled run actually outlasting the space's
limit under its own (the limit reaches `RunLimits` through
`execute_run`, covered by the launcher test only).

## 0.4.1: the investment roster, per-tool answers, the Runs panels and the Obsidian button

On 2026-09-19 the maintainer clicked **Open in Obsidian** on a Mac without
Obsidian and got the launcher's exit status as the error. The shell now has
an `obsidian_available` command that looks for Obsidian where its installer
puts it (`/Applications` and `~/Applications` on macOS, `%LOCALAPPDATA%`'s
`Programs\Obsidian` and `Obsidian` on Windows), the Knowledge toolbar offers
the button only when it answers yes, and a failed open reports what still
works (the folder in Obsidian's own picker) while the launcher's error goes
to the shell's stderr. Executed: `cargo test` (3, including the candidate
paths per platform), `cargo clippy --all-targets -D warnings`, `cargo fmt
--check`, `just check`, and `KnowledgeView.test.tsx` (18, two new: the
button absent when the shell says no, and the shell's refusal shown in
words). **Not exercised:** a Mac or Windows machine with Obsidian installed,
so the positive path (button shown, vault opened) rests on the earlier 0.3.x
check of the URI and on the path list.

The same day, at the maintainer's request, migration 010 made the default
space's built-ins the ten definitions of the investment research pipeline
(`store/010_investment_roster.sql`), with the three generic roles kept as
the starter roles a new space is seeded from. Executed:
`test_investment_roster.py` (15) covers the fresh roster's models, tools,
step ceilings and narrowed approval lists, the no-shell and collectors-only
fetch properties, the bear prompt mirroring the bull, an upgrade from a
version-9 database in which an edited writer survives as a deletable row, an
untouched researcher and reviewer are retired, and a user's own `decision`
agent keeps its row while the shipped one is skipped, and an untouched
researcher moved to another space staying there, deletable. The rest of the
backend suite passes with the shared `agents` fixture seeding the starter
roles beside the roster (764 passed, 11 skipped, the DNS-bound sandbox and
tools files deselected here), `just check` passes and the OpenAPI snapshot
was regenerated for one docstring. **Not exercised:** a run of the pipeline
against a model, which needs the config files and scripts the prompts assume
and the user guide lists; and the migration against the maintainer's own
0.4.0 database, which happens at the next launch of a build carrying it.

Later that day, three more of the maintainer's requests. The run canvas's
handoff labels moved into React Flow's HTML label layer (`HandoffEdge` in
`RunGraph.tsx`): every forward handoff turned on one vertical run between
the columns and a label at a path's centre was crossed by its siblings, so a
forward label now sits over the last stretch into its card and a return
label under the card it leaves, each with the whole task as its tooltip, and
cut-short card text carries its full text as a title. The run list, the
canvas and the inspector gained drag handles (`Splitter.tsx`, sizes kept per
browser by `useStoredSize`). And the gate gained per-tool answers: the
settings' `tool_policies` (ask / allow / deny, validated against the
catalogue), a space's stricter copy (migration 011 adds `spaces.tool_policies`
and `approvals.scope`), `ToolRuntime.policy_for` (an allow narrowed by a
definition's levels), `ApprovalService` refusing by policy or allowing by a
run-wide precedent, `POST /approvals/{id}` taking `scope`, and the dialog's
**Allow for this run**. Executed: `just check`; **777 backend tests** pass
(`test_approval_gate.py` gained five: refusal without asking, an allow
running unasked, a definition narrowing an allow, a run-wide yes answering
a later write but not a read, and a no never being for a run;
`test_tool_runtime_policy.py`, the settings, spaces and approvals API tests
cover the rest); **424 frontend tests** (39 files) pass, with the reducer
keeping `policy`, `precedent` and `scope` apart, the dialog's third button,
the Settings table dropping an answer set back to ask, and the space table
offering only stricter answers. Exercised in Chrome against the scratch
sidecar (migrated 9 to 11 on a database with runs): a seeded three-worker
run showed every handoff label clear of the lines, the three handles were
dragged with real mouse events, clamped so the log kept its minimum, and
the sizes survived a reload; the Settings table showed `read_file` allowed
and `run_shell` refused after a PATCH, the space table offered ask or deny
for the allowed tool, deny alone for the asking ones and nothing for the
refused one; a slow demo run's dialog showed Deny, Allow and Allow for this
run. **Not exercised:** the gate against a live model (the demo run's
approval events bypass the store, so its third button answers a 404); a
space's stricter answer changing what a real run does, covered by
`test_per_tool_answers_only_get_stricter` and the API tests only.

## 0.4.0: scheduled runs, Usage, the tour, and two layout fixes

Phase 13, on 2026-09-19, in seven commits after 0.3.3. The sidecar gained
migration 009 and `store/schedules.py` (three cadences, `LocalZone`,
`next_occurrence`, a store that keeps `next_run_at` consistent with
`enabled`), `orchestrator/scheduler.py` (one task: a catch-up pass at launch,
then sleep until the earliest time or a 60 s poll, launching through
`RunLauncher` with origin `schedule`), `api/schedules.py` (CRUD, run-now,
preview) and `budget/usage.py` behind `GET /usage`; `RunOrigin` gained
`schedule`, the settings response gained `version`, `data_dir` and the
`onboarding_completed` setting. The window gained the Schedules section in
Space settings, the Usage section, the tour and About box, per-agent usage in
the run inspector, the folded summary with the memory row, and the Agents and
canvas fixes.

Executed: `ruff`, `ruff format --check`, `mypy --strict` over `src` and
`tests`, and **747 backend tests** pass with 11 skipped (the 74 deselected are
`test_sandbox.py` and `test_tools.py`, whose `example.com` lookups fail on this
Mac's DNS; CI runs them). `test_schedules.py` (19) covers the cadence
arithmetic with a hand-written summer-time zone, including 09:00 the morning
after a DST switch landing at 07:00 UTC, `LocalZone` against the C library
under `TZ=Europe/Amsterdam`, the store, and the scheduler's passes: a due
schedule fires once with origin `schedule`; a schedule three days overdue at
launch runs once or is skipped per its policy and moves to tomorrow either
way; a schedule whose previous run is still going is skipped; an archived
space turns its schedule off; the loop fires on time and wakes for an edit.
`test_api_schedules.py` (9) and `test_api_usage.py` (3) cover the endpoints,
including the space-narrowed and prior-period reports and a deleted run's
spend listed as such. `tsc`, `eslint --max-warnings 0` and **408 frontend
tests** (37 files) pass, including `replayIdentity.test.tsx` over the reducer's
new per-agent fields, and `test_repo_hygiene.py` passes.

Exercised in Chrome against a scratch sidecar on port 8790 (the maintainer's
own 0.3.3 held 8787; the page's requests were rewritten over CDP) with
screenshots read back: on a fresh data directory the tour opened on the
sidecar's flag, every step spotlit its target with the section switched
beneath it, the keys step scrolled its target into view after a fix, **Try a
demo run** from the last step started the scripted run, closed the tour and
opened the run, and `onboarding_completed` read `true` afterwards; a weekly
schedule was created from the picker with the preview reading "Weekdays at
09:00. Next: Mon, Sep 21, 09:00 AM, ..."; **Run now** started a run and the row
read "Started by hand." with a link to it; with `next_run_at` set into the
past in SQLite the poll started a run with origin `schedule` within 70 s and
moved the schedule to Monday; after the sidecar was stopped, the schedule set
three days overdue and the sidecar restarted, the row read "Started a run:
the app was closed at 01:23 on Wednesday 16 September, so it ran at launch."
and the next time was again Monday, not three runs. The Usage page rendered
seeded spend rows (ten calls across three runs and a deleted run) with the
cards, the day bars, both tables and the run table, narrowed to the space and
widened to all spaces. With a second space, the Agents editor showed the
move-or-copy bar above the editor and the tools list cut short with ellipses
(a second overflow, the fieldset's min-content width, was found here and
fixed). A completed demo run showed the "read 1" chip, the Outcome title with
its pill, the handoff label between the cards and the return handoff beneath
them; the inspector listed the researcher's one model call, 412 in, 38 out,
and 412 tokens of context.

**Not exercised:** the Tauri window itself (no screen access here); a
scheduled run against a real model (every scratch run failed at once for want
of a key, as expected, which is also how a schedule's failure reads in Runs);
a DST switch on the real clock rather than the injected zone; the memory row
against a run that wrote a memory (the demo run writes none; the row is
covered by `RunSummary.test.tsx`); and the Usage bars past a month with rows
on every day, which the flex layout would compress to about 30 bars.

## 0.3.3: Obsidian-flavoured vault, workflow canvas, shell shortcuts

Frontend-only work on 2026-09-18, released as 0.3.3, in four commits. The vault
gained a parser for the Obsidian dialect (`lib/markdown.ts`: frontmatter
properties, wikilinks with aliases and headings, embeds, tags, highlights,
strikethrough, callouts with fold state, nested and task lists, tables, code
fences, a single newline as a break) and a renderer (`components/Markdown.tsx`)
that builds elements from the tree and never from strings; `Markdown.test.tsx`
asserts that a `<script>` and an `<img onerror>` in a note stay text and that
only `http`, `https` and `mailto` become links. The Knowledge section is laid
out as a vault: a folding folder tree, the note head with path, tags and
properties, source and preview, a links pane, a status line, `[[` completion,
a formatting bar, a quick switcher (Ctrl/Cmd+O) that creates missing notes,
Ctrl/Cmd+S and Ctrl/Cmd+E, an unsaved-changes guard, task boxes that write
back to the source, tags that filter the tree, a force-directed graph with a
local scope, and toasts. The run canvas draws goal, supervisor, workers and
outcome as cards with state pills and per-tool chips, routes return handoffs
beneath the cards, and opens an inspector with the agent's last message,
handoffs and tool calls. Citations on Home and in a run open their note; the
rail badges approvals and proposed memories; Ctrl/Cmd+1..6 switch sections.

`tsc`, `eslint --max-warnings 0` and **384 frontend tests** (34 files) pass,
including `replayIdentity.test.tsx` against the new canvas and inspector, and
`test_repo_hygiene.py` passes. Exercised in Chrome against a scratch sidecar
(`AGENTSPACE_DATA_DIR` under the session scratchpad, Vite on 5173, headless
Chrome over CDP with screenshots read back): a seeded note with callouts,
highlights, nested tasks, a table and a fenced block renders in split,
preview, light and dark; a `[[note#heading|alias]]` link opens the target;
the whole-vault and local graphs draw their edges; Ctrl+O finds a note and
offers to create one; typing `[[ret` in the source lists notes and Enter
inserts `[[Retention policy]]` and marks the note unsaved; the demo run's
canvas shows the four cards, both handoff edges with their labels and the
`read_file` chip, and clicking the supervisor opens the inspector; **Preview
context** on Home renders each excerpt and its citation opens the note in
Knowledge. Two collisions found only in the browser were fixed before the
commit: the quick switcher's `.switcher` class had restyled the space
switcher, and the editor's `.editor` class the agent editor. **Not
exercised:** the Tauri window itself (no screen access on this machine), the
external-link behaviour inside the shell (an `http` link copies its address
there, since the webview is granted no opener), and a vault near the
10,000-note limit, where the graph falls back to a circle past 600 nodes.

## 0.3.2: disk image, restart from Settings, dated snapshot prices

Checked on Apple Silicon macOS on 2026-09-18, from the first macOS field
report. Launch Services on this machine explained the report's "two
AgentSpace icons": the zipped app had only ever been opened from Downloads,
so Gatekeeper had registered six translocated copies under
`AppTranslocation`, and no copy sat in Applications for Spotlight to list.

The macOS download is now Tauri's `dmg` target, built with `CI=true` so the
Finder AppleScript is skipped on every host. The local
`AgentSpace_0.3.2_aarch64.dmg` is **24,571,117 bytes**, SHA-256
`cb5ddb4ac47284f79ea3afe9f3f0b300737942b0a72b8334f7aeab6b04a0da22`; mounted,
it holds exactly `AgentSpace.app`, `Applications -> /Applications` and the
volume icon. The sidecar froze at **22,130,976 bytes**, SHA-256
`99e9fec643199c8dca0eeb2e666d97448176827deea0608935ee84ab8240f8a1`.
`just build-installer`, `just verify-build` (**18 release checks passed**,
four Windows-only skipped: the rewritten `test_macos_dmg.py` mounts the image,
checks its two entries, copies the app out with `ditto`, and runs the earlier
version, executable-mode, strict-signature and sidecar launch checks on that
copy) and `just check-tauri` passed. The `test_ci_workflow.py` pins now
require the `bundle/dmg/*.dmg` upload and `dist/*.dmg` release asset and
refuse any `.app.zip`.

The shell gained `restart_app`, which stops the sidecar and then calls
Tauri's `AppHandle::restart` from a thread of its own, so Tauri's exit path
runs the `RunEvent::Exit` callback before it execs the new copy. Settings
shows **Restart AgentSpace** under the key list once a key has been written
or cleared, only inside Tauri; the Settings tests cover the offer appearing
after a change, the call to the shell, the disabled "Restarting…" state and
a refused restart, and `lib/shell.test.ts` covers the browser case. **The
relaunch itself has not been exercised live:** this machine has no screen or
accessibility access to click the button in the packaged app, and there is no
other way to invoke the command. The mechanism is the one
`tauri-plugin-process` exposes as `relaunch`, read from Tauri's source, and
clippy is clean.

`pricing._lookup` resolves an Anthropic `-YYYYMMDD` snapshot to its alias
price; `claude-haiku-4-5-20251001` now costs what `claude-haiku-4-5` costs,
and a snapshot of an unpriced family or an OpenAI-shaped date stays refused
(two new tests). `just ci` passed lint, formatting, mypy on both platforms
and the TypeScript checks with **787 backend tests** (12 skipped) and **338
frontend tests**; the five remaining backend failures were
`test_sandbox.py` and `test_tools.py` cases that resolve `example.com`, which
this machine's router resolver answered with AAAA records only during the
session, and they fail identically on the committed 0.3.1 tree. They are
network state, not code, and the tag workflow's test job re-runs them on
both runners.

## 0.3.1: the Codex runtime is fetched, not frozen

Checked on Apple Silicon macOS on 2026-09-18. The 0.3.0 sidecar carried the
Codex App Server runtime through `--collect-all codex_cli_bin`; measured
launch-to-healthy for three sidecar variants on the same machine, three runs
each, was 2.1 to 2.3 s for that 133 MB build, about 1.75 s for a 111 MB build
without the unused `codex-code-mode-host`, and 1.0 to 1.1 s for a 22 MB build
with no runtime. The `codex` binary itself is already arm64-only and stripped,
so nothing smaller than fetching it separately was available.

The sidecar now excludes `codex_cli_bin` and freezes at **22,131,376 bytes**,
SHA-256 `ad441a7ba41a3c1799e57b5e39e09d93089b8d997599311b4d2f5a41efe54ef2`;
`AgentSpace_0.3.1_aarch64-apple-darwin.app.zip` is **24,427,920 bytes**,
SHA-256 `c0c453c8dbdf0554f45bb19a55b3950755729ef6eb3d235af239c89d79a56d07`,
down from 135 MB. `just build-installer`, `just package-macos`,
`just verify-build` (**17 release checks passed**, four Windows-only skipped)
and `just check-tauri` passed.
Unit tests drive the installer against an in-process ASGI server with a
fake wheel: fetch, size and SHA-256 verification, unpacking only the members
the SDK uses with the wheel's own executable bits, atomic commit, reuse
without a second request, refusal of a hash mismatch, a short or oversized
body, an HTTP error, an unsafe member path and a wheel with no executable,
one shared task for concurrent callers, the development-checkout shortcut,
and an unsupported platform. A pinning test keeps `codex_runtime.json` equal
to the wheels in `uv.lock`. The frozen-sidecar tests now assert that
`/auth/chatgpt` reports the runtime as `missing` and that the binary stays
under 60 MB. The Settings tests cover fetch-then-sign-in with progress and a
refused download.

Live, with the frozen binary on a scratch data directory: `POST
/auth/chatgpt/runtime` fetched the real 112,690,061-byte macOS wheel from
PyPI in 15 s, the status went `preparing` then `disconnected` with the runtime
`ready`, the install held `bin/codex`, `codex-path/rg` and `codex-resources`
(217 MB, no wheel or helper binary left behind), `POST /auth/chatgpt/login`
through the fetched runtime returned a real `auth.openai.com` authorization
URL and was cancelled, and a relaunch reported the runtime ready with no
download. No account was signed in. `just ci` passed with **790 backend
tests** (11 skipped, the three archive checks waiting for the packaged
build) and **334 frontend tests**.

## 0.3.0: memory inbox, incremental retrieval and the inspector

The 0.3.0 additions were checked on Apple Silicon macOS on 2026-09-17. At
10,000 notes on disk, measured with a scratch vault: a cold index took 1.5 s,
a warm index 0.04 s (down from 0.84 s before chunk signals were precomputed
and the scan stopped resolving every path), and a query 0.02 to 0.11 s (down
from 0.33 to 0.54 s). `test_ten_thousand_notes_on_disk_index_and_search_within_bounds`
pins loose bounds of 5 s and 3 s against real files and took 6.4 s including
writing them. Focused tests cover citations on run memories and proposals,
merge with archived originals and a backup, pinning any note, unresolved
links and orphan counts, the merge and pin endpoints, the reducer's fold of
`run.started` excerpts and exclusions and `run.completed.memory_path`, the
Home preview's terms, token totals, model label and exclusion, the inbox's
provenance and merge flow, browser filters, daily notes, templates and
capture from the event log.

The Knowledge, Home and Runs sections were driven in headless Chrome against
the Vite dev server and a sidecar on a scratch data directory: a seeded vault
showed 3 orphans and 1 unresolved link, pinning wrote `pinned: true`, the
inbox showed a run memory's citation and **Open run**, merging two memories
produced a proposed `memory/merged/` note with both outcomes and citations
and archived the originals with `merged_into`, a note was created from
`templates/meeting.md` with `{{date}}` filled in, today's daily note opened,
**Preview context** listed two excerpts with 42 tokens sent to
`anthropic · claude-opus-5`, a run started over the API with one excluded
citation recorded it in `run.started` and the run view showed it struck
through, and **Save as note** wrote `captures/<run>-20.md` from the scripted
demo run. No real model was called; the Tauri window was not opened.

`just ci` passed with **774 backend tests** (11 skipped) and **332 frontend
tests**, with `ruff`, `ruff format`, `mypy --strict` on both platform targets,
ESLint and `tsc` clean. `just build-installer`, `just package-macos`,
`just verify-build` and `just check-tauri` then passed: the frozen sidecar is
**132,951,760 bytes**, SHA-256
`45d83b0863c3253e0a6f9a44e9985da38bf0689a21c861224d280b97836e0830`, and
`AgentSpace_0.3.0_aarch64-apple-darwin.app.zip` is **135,034,138 bytes**,
SHA-256 `285fafb2912bbad527297ec9740bb815d17ad6f096b1310eb973e2fffba52663`,
with **16 release checks passed** and the four Windows-only NSIS checks
skipped. The archive is five times 0.2.0's because the sidecar has bundled
the Codex App Server runtime (`--collect-all codex_cli_bin`) since the ChatGPT
subscription change; that size was recorded below but its effect on the
download was not called out until now. `replayIdentity.test.tsx`'s intermediate-position
test, which renders 58 panels in one test, exceeded its 5 s timeout in some
full-suite runs while the machine reported a load average above 100 from
system processes; it passed in isolation and in other full runs.

## Markdown knowledge, local RAG and durable memory

The 2026-09-15 knowledge-vault addition was checked on Apple Silicon macOS.
Each space now exposes ordinary Markdown notes through the native Knowledge
section, including safe source/preview modes, YAML properties and tags,
wikilinks, backlinks, retrieval search and a linked-note graph. The same local
retriever supplies cited, untrusted context to run goals and worker handoffs.
Successful runs write unique `memory/runs/<run-id>.md` outcome notes, and the
desktop shell can open only a validated space folder through an encoded
Obsidian URI.

`just lint typecheck` passed for 108 Python source files on both the macOS and
Windows mypy targets, plus desktop ESLint and TypeScript. The complete suites
passed with **763 backend tests** and **324 frontend tests**; 11 backend tests
skipped for absent platform or release-archive prerequisites. Focused tests
also covered external Markdown parsing, relative links, heading retrieval,
stable citations, path and `.obsidian` refusal, API CRUD/CORS, run memory and
the agent-facing search tool. Rust formatting, Clippy and both Rust unit tests
passed. A fresh sidecar containing migration 007 was built at **132,920,928
bytes**, SHA-256
`9028c9359be3f1105713b19b33516cdf23703235708c2cc9b71929fd4ee0b3b3`;
all **13 frozen-sidecar tests** then passed against those exact bytes. The
backend passes used normal macOS process and network facilities so their
frozen-sidecar and DNS checks could execute.

## ChatGPT subscription transport

OpenAI API-key and ChatGPT subscription access now construct the same `openai`
provider contract. The ChatGPT path uses a pinned Codex App Server runtime for
OAuth and one structured model decision, while AgentSpace retains its own
orchestrator, tool execution, approvals, events, limits and budget wrapper.

On Apple Silicon macOS, `just check` passed for 102 Python source files on both
macOS and Windows mypy targets plus desktop lint and typecheck. The full suites
passed with **750 backend tests** and **319 frontend tests**; 11 backend tests
skipped for absent platform or release-archive prerequisites. Rust formatting
and its one auth-URL test passed. The freshly frozen sidecar is **133,046,736
bytes**, SHA-256
`097497ae43ab32c3a5d0273d6420bb3d42253d82da1acc6ef5c53ac68ae09b99`.
All **13 frozen-sidecar tests** passed with normal macOS process facilities,
including first-launch data, `/auth/chatgpt` runtime startup, event streaming,
clean shutdown and zero orphan processes. The managed sandbox itself blocked
the PyInstaller executable's process/semaphore startup, matching the existing
release-check limitation recorded below. A separate direct launch of that
frozen binary returned
`{"state":"disconnected","email":null,"plan":null,"error":null}` from the
auth endpoint, then stopped cleanly through its stdin shutdown command.

## 0.2.0 macOS signing correction

The published 0.2.0 Mac archive reproduced the user's **damaged and can't be
opened** Gatekeeper error. `codesign --verify --deep --strict` showed that the
archive preserved executable modes but lacked a complete app-bundle signature.

The corrected 0.2.0 build configures Tauri's ad-hoc identity and keeps hardened runtime
disabled. Enabling the runtime caused the re-signed PyInstaller sidecar to fail
while loading its extracted Python library because the process and mapped file
had different code identities. The release test now strips signatures from
temporary copies before checking sidecar content, verifies the complete bundle
signature, then launches the archived sidecar. The corrected local archive
passed all **15 applicable release checks**; four Windows-only checks skipped.
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` is 24,188,613 bytes with local
SHA-256 `3d1ebcc69b79cf3ed5dd4691722488c3928e1a7743c3746a2e9992a3e32d4719`.

## 0.2.0 preparation

Documentation and local release preparation were completed before publication.
The [v0.2.0 release page](https://github.com/Zocke07/AgentBase/releases/tag/v0.2.0)
is the authority for publication status and downloadable artifacts. The tag
workflow is the authority for cross-platform CI results.

On Apple Silicon macOS, `just ci` passed with **738 backend tests and 313
frontend tests** after the documentation, version and Discord mention changes.
Eight backend tests skipped because their current build or platform prerequisite
was absent. The first run inside the managed command sandbox failed because it
blocked DNS and PyInstaller's System V semaphore; the same gate passed with
normal OS facilities.

`just build-installer`, `just package-macos`, `just verify-build` and
`just check-tauri` then passed. The build produced
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` (23 MB, SHA-256
`5cf8bdee4ab107b6b52b282da31b68acaacf4ca27248183e69f80fa5b99fe1af`).
Four Windows-only NSIS checks skipped on macOS; the other **14 release checks
passed**. They verified the bundle version and identifier, archived executable
modes and hashes, fresh database startup, HTTP health, and clean extracted
sidecar shutdown with Python removed from its environment. Rust Clippy passed.
The packaged Tauri window and a downloaded copy's Gatekeeper flow were not
opened in this session.

## Backend coverage baseline

`just test-backend-cov` ran on Apple Silicon macOS on 2026-09-13 before the
release changes: **733 passed, 8 skipped**, in **39.67 seconds**. Coverage was
**4,146 of 4,473 statements (92.69%, displayed as 93%)**. This does not measure
branch coverage, frontend code or Rust.

| Module | Statement coverage |
|---|---:|
| Event store | 100% |
| Budget ledger | 96% |
| Agent registry | 100% |
| Sandbox | 82% |
| Provider transport | 77% |
| Discord adapter | 58% |

The counts alone do not suggest an excessive suite. Many guards protect
failures that leave the happy path green: a sidecar omitted from a bundle,
an offered tool bypassing its definition's allowlist, a budget charge lost
when streaming stops, or a setting accepted but ignored. The history records
manual mutations used to show these tests fail when the boundary is removed;
this session has not rerun those mutations. Coverage is not a mutation score.

## Outstanding live checks

These remain open in the latest recorded evidence, even where scripted tests
cover the behavior. They are not all release blockers.

- A real OpenAI API-key request, especially streamed usage accounting, and a
  run with workers using different providers. Anthropic and Ollama already
  have live evidence in the history; the old claim that no provider was called
  is stale.
- Completing ChatGPT browser sign-in with a personal account and running a real
  subscription-backed task. The isolated Codex runtime has started and reported
  `disconnected`; automated tests cover auth lifecycle, one-decision transport,
  normalized usage and tool calls, but no personal OAuth session was used.
- A real model attempting to spawn another space's agent. Live runs proved
  that only the selected roster is offered; the refusal itself was scripted.
- Discord starting a run in a non-default space, real mentions, multiple users
  or guilds, and rate-limit pressure. Do not send chat messages as part of a
  check without the user's authorization.
- Two real clients racing to answer the same approval. Duplicate resolution
  is covered by the API tests, not a recorded live race.
- Large transcripts, large windowed event logs, and backward replay cost.
  Small-run correctness does not establish performance at tens of thousands
  of events. Parallel workers are not implemented.
- A downloaded macOS release passing Gatekeeper's manual-open flow. Earlier
  Mac checks launched a locally built app, which had no download quarantine.
- **Restart AgentSpace** from Settings in the packaged app on either
  platform: the sidecar stopping, the window reopening, and the new sidecar
  binding port 8787 with the changed key in its handshake.
- Installing 0.3.2 from the disk image on a Mac by hand, and confirming
  Spotlight lists the app afterwards.
- A schedule firing in the packaged app against a real model with a
  pre-authorized policy, and its catch-up after the app was closed overnight.
  Since Phase 16: the seeded pipeline's chain running stage after stage on a
  real model, and a scheduled question expiring while the run carries on.
  Phase 17's acceptance adds the same chain producing prices, portfolio
  figures, rule checks and a scored ledger with no model doing arithmetic.

The first Mac session already closed automatic browser SSE reconnect,
two simultaneous browser streams, clicking run deletion, both-theme replay
comparison, packaged startup/shutdown and the native keychain round trip.
See the history for the measured limits, including small graph measurement
differences in the pixel comparison.
