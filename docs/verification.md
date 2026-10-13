# Verification and remaining work

Updated 2026-10-13. This is the current record; [history](history/README.md)
holds earlier evidence and superseded gaps under original identifiers. Results
cover only work actually executed.

## The investment pipeline stays in the default space, 2026-10-13

The maintainer asked that what was built for the default space, such as the
portfolio editor, stay there, and that new spaces rely on the general agent
tools alone.

- **Tools.** The seven pipeline tools are `default_space_only` in the
  catalogue. Another space is listed the general tools, cannot give an agent
  a pipeline tool, cannot receive an agent that uses one by a move or copy,
  and cannot start as a copy of the default roster. Its runs drop pipeline
  tools from every definition, so a row that still lists one is neither
  offered nor permitted it. Migration 034 removes them from other spaces'
  agents and per-tool answers.
- **Features.** The portfolio and market watch endpoints answer 404 for any
  other space, and the watch checks the default space alone. Home's portfolio
  card and pipeline offer, Automations' pipeline offer and Market watch, and
  Runs' Market alerts filter show only there; a space switch clears that
  filter. Another space's User Summary groups notes, daily notes, workbooks
  and charts, with its own empty-state text.
- **Executed.** New tests: the API refusals and tool lists
  (`test_default_space_only.py`), a run in another space whose legacy row
  lists `read_prices` (refused, never called, not offered), the watch
  ignoring another space's switched-on file, migration 034 on a version-33
  database, and the app's cards, filter, switcher, tool requests and summary
  groups. The other session's portfolio test now expects the 404. `just ci`:
  backend **1,409 passed, 12 skipped**; desktop **653 passed in 62 files**;
  lint, formatting and both typecheckers clean. A copy of the dev database
  upgraded to schema 34 with Main's 11 agents and 5 runs unchanged; it has no
  other space, so the migration had nothing to remove there.
- **Unverified.** Not seen in the window; it applies after `just dev-app`
  restarts. Agents copied out of Main before today keep their general tools
  and lose only the pipeline ones.

## A refused call sent again is not a failure, 2026-10-13

After the capacity fix the maintainer pressed **Run now** on Daily decision
at 15:39 Taipei. It completed in 4 minutes 10 seconds for about $1.20 and
wrote the decision for the 2026-10-12 session and the October workbook:
`track_forecasts` appended 130 forecasts, 25 of them analyst forecasts. The
run reported one error. The supervisor's first `spawn_agent` arrived with
arguments that were not one JSON object ("Extra data at character 605"), so
`ToolCall.argument_error` refused it before it ran, and the supervisor sent
the same request again 9 seconds later, which ran. The summary still said
"1 error during this run" with "Review these before trusting the outcome",
and in Morning collection or Theses and risk the chain gate would have
stopped the next stage.

- **The rule.** A tool error whose call never ran, with no `tool.called` for
  its `call_id`, is forgiven once the same agent has run that tool after it.
  The run summary lists it calmly as a call sent again, apart from failures
  and without the warning, and the canvas's error count leaves it out
  (`isResentRefusal` and `changedNothing` in `state/reducer.ts`). The chain
  gate passes it (`_resent_refusals` in `scheduler.py`). A refusal never
  followed up, a call that ran and failed, and a refusal followed only by
  another agent's call still count as failures, since a worker the refused
  call would have started may never have run.
- **Executed.** Schedule tests for the resent call and the four cases that
  still block, reducer tests for the three readings, and run summary tests
  for the calm listing and the failure without a resend. `just ci`: backend
  **1,399 passed, 12 skipped**; desktop **643 passed in 61 files**; lint,
  formatting and both typecheckers clean.
- **Unverified.** The running app shows the old summary until `just dev-app`
  restarts. The refused call was replayed through tests, not a new run.

## Personal stock data can be edited on Home, 2026-10-13

**Home → My portfolio → Edit portfolio** edits holdings, additional watched
stocks, share counts, optional purchase prices and dates, cash, currency and
the three percentage limits. Owned stocks are automatically watched. Saving
updates the existing `portfolio/positions.csv`, `config/watchlist.json` and
`config/limits.json`; it makes no model calls and places no trades.

- **Data integrity.** Decimal inputs retain their precision, including JSON
  limit values. Extra CSV columns, aliases and custom JSON metadata survive.
  Originals are backed up before replacement; a failed later write restores
  earlier files by renaming prewritten recovery copies. Malformed input and
  mixed currencies are reported without replacing data. Revision checks
  reject stale saves, and a save cannot overlap an active run in that space.
- **Editing.** Failed saves retain the form. Unsaved edits survive navigation
  and space changes within the window. Delayed loads cannot replace edits,
  and a save completing after navigation cannot erase a newer draft. Loading
  failures do not expose an empty form that could overwrite existing inputs.
- **Runs.** Changed personal inputs allow a manual morning run to review the
  same market session again. Existing forecasts stay immutable. Configured
  holdings and watched stocks take priority over cached discoveries within
  the 50-stock research limit.
- **Executed.** Backend **1,380 passed, 12 skipped**, excluding the frozen
  binary tests; the rebuilt frozen backend's **14 smoke tests passed**.
  Desktop **641 passed in 61 files**. Ruff, formatting, ESLint, strict mypy
  on macOS and Windows, and TypeScript passed. The production frontend and
  macOS arm64 sidecar both built. The dev sidecar copy was updated for the
  next app restart. Tests cover actual portfolio-tool consumption, rollback,
  stale edits, decimal precision, space isolation, active-run protection,
  discovery capacity and asynchronous form behavior.
- **Unverified.** The packaged window has not been exercised with this form.
  No live personal data was changed and no paid model calls were made.

## A model at capacity is waited out, 2026-10-13

The retry's Theses and risk stage failed when GPT-5.6 Terra, the bull
analyst's ChatGPT model, answered that it was at capacity after three
successful calls. That stopped the chain before the decision. The ChatGPT
mapping knew usage limits and rate limits but not the App Server's
`serverOverloaded` flag. It read the reply as a plain failure, which the
agent never retries.

- **Classification.** `ProviderOverloadedError` is a temporary rate limit.
  On ChatGPT it comes from the `serverOverloaded` flag, the SDK's busy error,
  or "at capacity" or "overloaded" in the message. Through an API key it
  comes from HTTP 529, a 503 that says it is overloaded, Anthropic's
  `overloaded_error` event mid-stream, and OpenAI's overloaded codes. A
  usage limit still wins over it, and an explicit rate limit stays a rate
  limit.
- **Retry.** The same model is tried again after about 1, 2 and 4 minutes
  (each wait capped at 5), within the run's time limit, and never once
  output has streamed. The log reads "model is at capacity right now.
  Waiting N seconds before trying it again."
- **Executed.** Provider, cooldown, Responses and orchestrator suites:
  **222 passed**, including the Terra case through the App Server runtime,
  the three classification routes, 529 and 503 through both API adapters,
  the mid-stream event, three waits then success, and failure after the
  third wait. The desktop sentence test passed. `just ci`: backend
  **1,370 passed, 12 skipped**; desktop **629 passed in 60 files**; lint,
  formatting and both typecheckers clean.
- **Unverified.** No real capacity refusal has occurred since. The stage
  stops if a model stays busy past about 7 minutes of waiting.

## Knowledge in two sections, and file actions that fail gracefully, 2026-10-13

The end user found the files still unfriendly and asked for two sections,
**User Summary** (non-technical results) and **Technical Details** (the raw
or technical files), Preview as the default view, and file management that
handles failure gracefully.

- **Sections.** Knowledge opens on User Summary, grouped and newest first:
  - decisions, portfolio and weekly reviews, and market alerts;
  - forecast workbooks, named for their month;
  - charts and dashboards;
  - daily notes and other notes.

  Every dated report is readable as one page. Technical Details keeps
  Recent, the note tree, Agent files (now only raw data, settings and
  records) and Saved context. `state/sections.ts` places each path in one
  section, and a run's file links follow it.
- **Preview.** Notes open in Preview, Write and Split a click away. Data
  files open in a new Preview: CSV, TSV, JSON-lines or a JSON list as a
  table, other JSON indented, text as written. Charts open drawn, and one
  whose data a run has not written yet says **No data yet**.
- **Failures.**
  - Before: a file that failed to load left an editor whose Save would
    write empty text over it, and a "new" note or file at a taken path
    silently replaced it. Now the file cannot be saved until it loads, and
    `create` writes are refused with 409.
  - Deleting a note now keeps a backup.
  - A 404 on open, delete or folder delete counts as gone and refreshes the
    list.
  - Leaving a data file with unsaved edits asks first.
  - Disk errors name the file instead of a bare 500.
  - A stopped engine reads as such, not as "Failed to fetch".
- **Executed.**
  - `just ci`: backend **1,360 passed, 12 skipped**; desktop **628 passed
    in 60 files**; ruff, formatting, strict mypy on macOS and Windows,
    ESLint and TypeScript passed.
  - New backend tests cover `create` refusals, note-delete backups and a
    disk refusal in words.
  - New desktop tests cover classification, User Summary, the Preview
    table, the load-failure Try again, taken names, already-gone deletes and
    the unsaved-file guard.
  - Headless Chrome against the dev server with a scratch sidecar (schema
    33) and a copy of the current space: User Summary listed the decision,
    the review, **Forecasts for October 2026**, five charts and the
    dashboard, and no raw file. The decision opened in Preview, the
    dashboard drawn with two **No data yet** cards, a raw movers file as a
    26-row table and `config/limits.json` indented. Technical Details listed
    no workbook or chart. At 900 px there was no horizontal scroll.
- **Unverified.** The packaged window has not run it. The running dev
  window hot-reloaded the new screens but keeps the old sidecar, without the
  409 protection, until `just dev-app` restarts.

## The fresh retry's decision run, 2026-10-13

After restarting `just dev-app` the maintainer pressed **Run now** on Morning
collection at 13:40 Taipei (01:40 New York). The chain ran unattended in 16
minutes: collection 2.5, theses and risk 8, decision 5. `track_forecasts`
recorded 130 forecasts for the 2026-10-12 session, 30 `analyst_thesis` (AAOI,
AVGO, INTC, META, MU, PLUG) and 100 baselines, with no conflicts, problems or
skips. The run titles showed in Runs. The decision reported two errors.

- **"There is no directory at facts."** Four listings went out at once, one
  for a "facts" folder the goal implied; the decision then listed
  `raw/filings/` and read the facts there. Migration 033 names that folder in
  the goal and the decision's input. A missing path's error now names what
  exists nearest it.
- **"read_file needs a 'path' argument."** One read in a batch of ten arrived
  as `{}`; MSFT's facts, the one holding missing from the batch, were never
  read. The ChatGPT adapter swallowed unparseable `arguments_json`, as did
  the OpenAI chat and Anthropic decoders. Unreadable arguments now set
  `ToolCall.argument_error`, and the agent answers with the reason and a
  request to resend, never running the call. Tests cover all three adapters
  and the loop, where the batch's readable call still runs.
- **Found while tracing.** The supervisor named the file
  `decisions/2026-10-13.md` for the 2026-10-12 session: 028's goal had lost
  026's warning not to give the decision a date, which 033 restores. A
  second pass the supervisor added read `predictions/2026-10.xlsx` as text,
  78,630 bytes of event and about 29,000 input tokens; `read_file` now
  describes a binary file instead, and 033 asks for no such pass.
- **The run summary.** A lookup that found nothing (`read_file`, `list_dir`,
  `search_knowledge`) is a missed lookup, listed calmly and apart from
  failures; the badge, Errors figure and warning count failures only.
- **Executed.** `just ci`: backend **1,357 passed, 12 skipped**; desktop
  **613 passed in 59 files**; ruff, formatting, strict mypy on macOS and
  Windows, ESLint and TypeScript passed. A copy of the live database upgraded
  to schema 33 with the new goal and prompt passages and kept its runs.
- **Unverified.** The running app still has the code from before these
  fixes; they apply on the next restart of `just dev-app`. The dated file
  `decisions/2026-10-13.md` from this run was left as written. The summary's
  new styling was checked by component tests, not in the window.

## Unattended chain repair and run titles, 2026-10-13

The maintainer ran the chain again (**Run now** at 01:47 Taipei, then the
07:00 schedule) and asked what went wrong, for fixes, for the generated
outputs to be removed for a fresh retry, and for an automation's runs to show
their title in Runs.

- **The Mac slept.** `pmset -g log` shows the 07:00 morning collection
  starting in a 07:52 DarkWake with the lid closed and advancing only in
  later DarkWakes (08:19, 09:20, 12:23) until the 12:40 full wake; a
  decision call in flight when the lid closed at 02:01 waited until 03:09.
  Timed starts and market checks now wait until the computer has been awake
  two minutes (`orchestrator/power.py`), and a going run holds off idle
  sleep. On this Mac, `KeepAwake` created a real `PreventUserIdleSystemSleep`
  assertion through `caffeinate -i -w <pid>` and removed it on the last
  release.
- **Every forecast was the unchanged close.** The decision was told to copy
  `expected_return_pct`, which no thesis wrote, and passed `symbols` for 7 of
  25 tickers. `track_forecasts` now records each thesis as `analyst_thesis`
  from its band; disagreement or unsaved evidence keeps the baseline, and
  migration 031 has the decision call it with no arguments. On a copy of
  this morning's files, issued after the close, it recorded 125 forecasts,
  the real META 21-session thesis as 742.96 to 757.82 within 750.39 to
  765.25, and openpyxl read the workbook with warnings as errors.
- **A forecast made mid-session.** The 01:47 run (13:47 New York) forecast
  Monday's close from Friday's, citing Monday's midday Micron headline. No new
  forecast is issued during US regular hours; the same probe at 17:55 UTC
  recorded none and said why.
- **A cited headline vanished.** The 07:52 collection rewrote
  `raw/news-2026-10-12.jsonl` and dropped the headline the bear thesis cited;
  the event log still held it. A day's file now keeps earlier headlines.
- **Path slips stopped the chain.** `list_dir` returned bare names, the
  decision's `read_file` failed on them, and any tool error blocked the next
  stage. Entries are now space-relative paths, and a failed lookup no longer
  blocks.
- **Run titles.** `runs.title` (migration 032) holds the schedule's name or
  `Market alert:` and its symbols; Runs shows it above the goal, and the run's
  header folds the goal under **What it was asked to do**. Earlier runs are
  backfilled from their schedule or alert batch.
- **Fresh retry.** With no run going, the dev app was stopped and the
  database and space were backed up to
  `.dev/backups/fresh-start-20261013-132108` (98 files; integrity check ok).
  Removed: 87 generated files, 5 runs, 1,135 events and 107 approvals. Kept:
  the 9 inputs, settings, keys, the five enabled schedules and 634 spend rows
  with their run links cleared. A copy of the cleaned database upgraded to
  schema 32 with the new prompt, goals and column.
- **Executed.** `just ci`: backend **1,350 passed, 12 skipped**; desktop
  **612 passed in 59 files**; ruff, formatting, strict mypy on macOS and
  Windows, ESLint and TypeScript passed. No Rust changed, so `check-tauri`
  was not rerun.
- **Unverified.** The chain has not yet run with these fixes, and no real
  sleep and wake has been observed with the new sidecar. The titles were
  checked by component tests, not in the window. A weekday market holiday
  counts as trading hours (there is still no holiday calendar).

## Market watch, and the review of the research extension, 2026-10-13

The maintainer resent the friend's answers with the 2026-10-12 work still
uncommitted, asked for it to be finished to standard practice, then asked for
a 24/7 market monitoring agent. They chose alerts inside AgentBase, as desktop
notifications and on Discord; watching only while the app is open; and
automatic explanations with a daily cap (BUILD_SPEC Phase 18).

- **A forecast citing a report fact was refused.** Yahoo's annual and
  quarterly facts have no publication time and their file name no date, so
  `track_forecasts` rejected every scenario citing one, which the analysts are
  told to do. Evidence without its own time now counts from its document's
  `fetched_at`; screener rows are citable. A failing test came first; a fact
  fetched after issuance is still refused.
- **Workbook layout.** Each session's sheet is a row per ticker with every
  horizon's prediction, actual close and error side by side, then an **All
  forecasts** sheet. openpyxl read the generated workbook with warnings as
  errors and LibreOffice converted both sheets; Excel was not tried.
- **Opening it in the app.** The shell's `open_workbook` opens a visible
  `.xlsx` inside the data directory in the spreadsheet app, and **Show in
  folder** reveals it; a browser tab still downloads. A Rust test covers the
  path check. The packaged window has not run it.
- **Smaller fixes.** Headlines are `claim_type: "unclassified"` instead of
  "opinion"; the HTTPS helpers shared by the market tools are the public
  `tools/builtin/fetching.py`; the user agent names the package version;
  `read_prices` uses the tracker's horizons.
- **Market watch.** `orchestrator/monitor.py` reads Yahoo's keyless spark
  quotes, 20 symbols a request, every `check_every_minutes` from 04:00 to
  20:00 New York time on weekdays, for a space whose `config/monitor.json`
  turns it on. Alerts are `market_alerts` rows (migration 030); one
  `monitor` run per check, by the new shipped `market-explainer` on the news
  scanner's model, writes `alerts/{date}-{HHMM}.md`, capped per day and
  waiting while the space runs anything else. Home lists alerts with a badge,
  the window raises desktop notices through the shell's `notify_alert`, and
  Discord posts to `discord_alert_channel_id` with mentions disabled.
- **Executed.** Backend **1,330 passed, 12 skipped**; desktop **609 passed in
  59 files**; ruff, formatting, strict mypy on macOS and Windows, ESLint and
  TypeScript passed; the shell's **9 Rust tests** and `clippy -D warnings`
  passed. The monitor's 30 tests use a recorded spark response (MU and the
  S&P 500, 2026-10-12) and an offline client. A browser check against a
  scratch sidecar at schema 30, with the watch on, made a live spark request
  for six symbols (HTTP 200 at the checked address); Home listed seeded
  alerts with the reason and a **New** mark; Automations showed the watch
  and its thresholds; **Change what raises an alert** opened
  `config/monitor.json`; Settings showed the alert channel and notices. A
  waiting alert started a `monitor` run that failed for want of a model key,
  and the alert recorded the failure.
- **Unverified.** No live move crossed a threshold, so no real alert, real
  explanation, Discord post or desktop notification has happened; the
  packaged window has run neither `notify_alert` nor `open_workbook`. The
  running app needs a restart to apply migration 030; Main's watch starts
  off until **Turn on** in Automations.

## Current models and bounded rate-limit recovery, 2026-10-12

The next Main retry at 17:01 Taipei failed on a generic ChatGPT HTTP 429
after one morning run; the earlier same-space concurrency and headline-host
problems were fixed. This error alone still does not distinguish a temporary
throttle from account exhaustion.

- Refreshed the catalogue against official provider documentation. Haiku 5.5
  is the current fast Anthropic choice; GPT-6.1 Sol is the balanced/strong
  OpenAI choice. Migration 029 updates exact untouched Anthropic fast example
  definitions and unused defaults while retaining edited models and used
  spaces. New OpenAI API spaces use GPT-6.1 Sol. Whole-request long-context
  tiers are priced for Haiku 5.5 and GPT-6/GPT-5.6 Sol, including budget
  projections. Legacy choices remain available, with documented retirements.
  Default-agent matching uses exact shipped fields because migration 028
  advances prompt timestamps even without user edits; regression coverage
  includes older installations with distinct created/updated times.
- GPT-6 API requests now use Responses with low reasoning, local function
  tools, store:false, and encrypted reasoning replay scoped to the same
  conversation. Retained GPT-5.4/5.5/5.6 Chat Completions tool requests disable
  reasoning where required. Tests cover streamed and collected results,
  continuation, malformed calls, cutoffs, usage and provider errors.
- ChatGPT inference shares one FIFO queue across models and runs with five
  seconds between starts. Abandoned turns receive a bounded best-effort
  remote interrupt before the permit releases. Temporary throttling can
  retry twice after about 60/120 seconds with jitter, respecting server hints,
  remaining time and both budget checks. Confirmed usage/billing limits,
  partial streamed output, excessive waits and exhausted attempts stop.
  Cooldowns remain in the event log but do not block a recovered chain or
  inflate the UI's failure count. Cancellation interrupts cooldowns promptly.
- Read-only SDK model/list returned GPT-6 Astra, GPT-5.6 Sol/Terra/Luna and
  GPT-5.5, but no GPT-6.1 Sol or GPT-6 Luna. Main retains its chosen GPT-5.6
  supervisor and example agents rather than selecting an unlisted model.
  This metadata check made no inference requests and does not prove quota
  availability. Account limits cannot be reset by code.
- Executed: **1,273 backend source tests passed, 12 skipped**, **593 desktop
  tests passed in 56 files**, and **14 rebuilt frozen tests passed** at schema
  029. Ruff/format, ESLint and strict mypy on macOS/Windows plus TypeScript
  checks passed. The first unrestricted desktop run hit worker startup and
  timing failures; rerunning with two workers passed the complete suite.
- Removed **52 generated files** after backing up Main and its SQLite
  database to .dev/backups/retry-fresh-20261012-224828/. Preserved all nine
  current inputs, model/account settings and failed-run history; indexing
  confirms zero generated notes. The cached debug sidecar matches the rebuilt
  binary for the next restart, which applies migration 029. No paid model
  request or live complete chain was run after these changes.

## Failed-run diagnosis and fresh retry, 2026-10-12

Read the real Main event log at schema 028. At 16:27 Taipei on October 12,
startup caught up Morning collection, Weekly knowledge and Weekly review at
once; their supervisor requests began within milliseconds. All three runs
ultimately failed with ChatGPT's exhausted-retry HTTP 429. The log establishes
neither a quota exhaustion nor a transient throttle as the specific cause.
No budget, malformed price, duration or step limit caused the terminal failure.

Separately, read_market asked for approval because the retained saved host
policy excluded feeds.finance.yahoo.com. The scheduled request expired after
120 seconds, so news/discovery and reports never ran. The active inputs still
had the old AAPL-only watchlist, zero cash and 30% sector cap.

- Fixed same-space schedule contention with a lock and queue. Continuation
  stages run before other roots; queued timed roots retain their due date,
  completion/failure rechecks them, and manual Run now rejects another active
  automation in that space. Different spaces remain independent. Untimed
  custom branches use process-local queue state with existing interrupted-run
  recovery; a durable arbitrary-branch queue remains outside this fix.
- ChatGPT errors now retain SDK rate/usage metadata and map HTTP 429 from both
  SDK errors and failed stream notifications to clear model-specific guidance.
  This initial repair added no extra retries above App Server; the bounded
  recovery described above was added after the subsequent single-run failure.
  [Official OpenAI error guidance](https://developers.openai.com/api/docs/guides/error-codes)
  distinguishes throttling and usage errors; code cannot reset account limits.
- Executed: **1,159 backend source tests passed, 12 skipped**; rebuilt sidecar
  **14 frozen tests passed**; Ruff/format and strict mypy on both platforms
  passed. No live model request was made after the fix.
- Per the user's fresh-retry request, backed up the Main space and database to
  .dev/backups/retry-fresh-20261012-165338/, cleared **17 generated files** and
  generated context, and restored the current nine starter files: six
  one-share holdings, USD 2,500 cash and 10/70/3 limits. Added only Yahoo's
  requested headline host to the saved policy and restored the exact old
  morning example cadence to Tue-Sat 07:00 local time. Run history, models,
  account credentials and other policy answers were preserved. Native file
  listing and note indexing confirmed nine inputs and zero generated notes.
  The cached debug sidecar hash matches the rebuilt binary for the next
  restart. The application currently running still needs that restart to load
  the code changes. No predictions were generated after cleanup.

## US market research and monthly Excel tracking, 2026-10-12

Implemented the requested first-use sample and migration 028. The default
follows six one-share holdings (MU, ORCL, CRWV, MSFT, NOW, AVGO), USD 2,500
cash, and 10/70/3 risk percentages. Missing acquisition costs and dates stay
unknown. Existing inputs and user-edited policies, prompts, tools, schedules
and models are preserved.

- Market discovery collects Yahoo gainers, losers, most-active stocks and
  deduplicated company headlines, with sourced sector metadata and explicit
  source gaps. Annual/quarterly Yahoo financial facts work by default;
  optional SEC contact enables official facts and bounded report excerpts.
- Forecasts use 1/2/3/5/21 complete trading sessions. Evidence-backed conditional
  agent scenarios and clearly labeled unchanged-price benchmarks are stored
  immutably. Later runs fill actual closes across every pending month.
  Monthly XLSX workbooks have daily session sheets and a binary download in
  Agent files. Every active ticker receives all five horizons, even when only
  some scenarios are submitted. Pending tickers remain priced after leaving
  discovery. Candidate quote gaps do not stop valid held-stock research.
  An unfinished decision/workbook can resume during the same session.
- Executed: **1,142 backend source tests passed, 12 skipped**; **592 desktop
  tests passed in 56 files**; Ruff/format, strict mypy on macOS and Windows,
  ESLint and TypeScript checks passed. OpenAPI was regenerated. The final
  sidecar was rebuilt and passed all **14 frozen smoke tests**
  for startup, schema 028, debug streaming and clean shutdown. The sandbox
  cannot initialize PyInstaller's semaphore, so frozen tests ran with approved
  system permissions rather than weakening the application sandbox.
- Live, approval-gated data smoke in a temporary example workspace: all three
  Yahoo lists returned five equities, six holdings remained included, and
  verified headline stocks brought the universe to **24**. **36** headlines
  were deduplicated. All six holdings returned latest annual/quarterly facts.
  Completed prices for all 24 succeeded for session **2026-10-09**; portfolio
  calculation preserved unknown P&L; the tracker created **120** baseline
  forecasts in predictions/2026-10.xlsx. A rejected general-feed ticker hint
  was reported explicitly. No model credentials or real portfolio were used.
- Unverified: the complete new chain on a real model, full SEC extraction with
  a real contact, and a packaged Tauri window. Forecast skill is not established
  by tool tests. Automation still requires the app to stay open; it catches up
  once after a missed schedule rather than inventing missed daily forecasts.

## Phase 17 and run-review UX, 2026-10-01, on `main`, not released

### The Journal, and Visualize folded into Knowledge, 2026-10-08

The maintainer asked whether to merge Visualize into Knowledge, and whether
runs should append to one growing file rather than write dated ones. They
chose a Journal and the merge. Agents still write one dated file per session,
for the reasons in BUILD_SPEC Phase 17's file contracts note.

- **Journal.** A Knowledge tab reads every note dated in its file name,
  outside `memory/` and `templates/`, as one page, newest first, a week of
  dates at a time. A month's report, such as `scores/review-2026-10.md`, heads
  its month. The dates down the browser jump to one; **Show** narrows the
  page to one kind. Nothing on disk changes.
- **Visualize folded in.** The rail has no Visualize section, so the
  shortcuts run 1 to 8 (Usage is 6). In Agent files a data file has a Text /
  Chart switch, and **Save chart** writes a `.viz.json` under a name no chart
  has and opens it. A saved chart, dashboard or diagram opens drawn, with
  Text for its source, and **From template…** adds Chart, Dashboard and
  Mermaid diagram. The editors moved from `VisualizationView.tsx` to
  `FileViews.tsx`. The tour's Visualize step merged into the Knowledge step.
- **Checks.** Frontend: **585 passed in 56 files**. The three Visualize tests
  became six in `FilesPanel.test.tsx`; the Journal has ten, Knowledge one
  more, the file helpers three. eslint and tsc are clean; the hygiene test
  passed, 16. A browser check ran against a scratch sidecar at schema 27,
  seeded with nine sessions of decisions and portfolio reviews, two weekly
  reviews and a daily note:
  - the Journal showed 21 reports from 11 dates;
  - picking Sep 24 widened the page to all 11 and scrolled that date to the
    top; **Show: Decisions** left nine;
  - the pipeline dashboard drew two charts and named its missing third;
  - `summary.csv` drew as a bar chart, suggesting
    `visualizations/summary.viz.json`, and `flow.mmd` drew;
  - at 960 px wide neither page scrolled sideways.
- **Unverified.** The packaged Tauri window (WebKit) has not shown either.
  Its scroll anchoring differs from Chrome's, so a picked date scrolls only
  after every report above it has loaded.

### Empty portfolio, and a second fresh start, 2026-10-07

- **An empty portfolio is valid** (`15735a6`). A missing, blank or
  header-only `positions.csv` made `compute_portfolio` fail, and the tool
  error stopped the chain. It is now an empty book: every value is 0,
  `empty_book` is true, a `note` says nothing is recorded, and the currency
  comes from the saved prices. Tests covered all three forms, then
  `check_limits` on the result. The full backend suite passed, **1103
  passed, 12 skipped**.
- **Second fresh start.** At the maintainer's request the dev app was
  stopped and backed up to `.dev/backups/fresh-start-20261007-202721/`,
  integrity `ok`. Five runs, 923 events and 75 approvals were removed, with
  89 spend rows detached and all 448 kept. Generated files moved into the
  backup; the space holds the three `config/` files and `positions.csv`.

### Fewer files in view, 2026-10-07

The maintainer found too many files in Knowledge. One AAPL session already
wrote 11 working files beside a decision and a portfolio review, and run
summaries filled the Notes tree. The files on disk are unchanged, since the
tools, gates and charts depend on their paths; what the window shows by
default is simpler:

- **Recent:** each day shows reports and inputs, with the runs' working data
  behind one **Show N working files** line.
- **Agent files:** folders holding only working data start folded. A search,
  or a file opened from a run, unfolds its folder.
- **Notes:** the `memory` folder starts folded unless the open note is in it.

`isWorkingFile` (`state/files.ts`) names that data: `raw/`, `theses/`,
`risk/` and `scores/`, plus `portfolio/computed.json` and `weights.csv`.
Notes and anything elsewhere are never folded away.

**Executed:** the classifier test and the folding tests failed first, and
older tests now unfold before asking for working files. The full desktop
suite passed **568 tests in 55 files**, with ESLint and `tsc` clean. Headless
Chrome on a time-preserving copy of the live space showed:

- Recent as the decision, the review and "Show 11 working files", then four
  inputs under Earlier.
- Agent files with `config` and `portfolio` open and `raw`, `risk` and
  `theses` folded.
- Notes with `memory` folded.

### Decisions that show their sources, migration 027, 2026-10-07

The maintainer asked why the decision table's header read "size %NAV", and
for decisions that show their sources and reasons. The shipped decision
prompt causes all three problems:

- It lists the columns as `size %NAV` and `action (buy/add/hold/trim/exit/pass)`,
  and the agent copied them as headers.
- It asks for reasoning only for non-pass rows, so a pass said nothing.
- It never asks the agent to resolve the evidence the theses cite.

Migration 027 updates the prompt where it is still the shipped text; the
maintainer's row was, apart from its model.

- **Plain headers:** the columns are named, and Size (% of portfolio) is
  explained under the table.
- **Reasoning for every row:** a pass says which cause applied.
- **A SOURCES section:** each cited evidence id is resolved to its news title,
  publisher and URL or to its movers figures, beside the risk results. An
  empty theses file is listed as an analyst finding no supported call.
- **A rule against overstatement:** the decision may not make thin evidence
  sound stronger than its sources.

Executed: the three new migration tests failed first. On a copy of the live
database the prompt moved and its GPT-5.6 Terra model stayed. The full backend
suite passed, **1100 passed, 12 skipped**.

Not verified: a decision written with 027 on a real model.

### Finding a run's files, 2026-10-07

After restarting with 025, the chain ran unattended from **Run now** through
Theses and risk to Daily decision (`91b242c6`, `52718b11`, `e71b7671`). It had
no tool or model error, and each gate passed. The maintainer could not find
the `decisions/2026-10-07.md` the run reported. Three causes:

- Knowledge loaded its lists once, and every section stays mounted, so files
  written later never appeared until a restart.
- The Notes tree showed only titles. The decision read "DECISION TABLE".
- The run view never listed the files it wrote. Outputs were split between
  Notes (Markdown) and Agent files (data) with no common view.

Changes:

- **The four deterministic tools report their files.** Each result carries a
  `written` array, never in the files themselves. `score_predictions` names
  the ledger only when it appended to it.
- **The run view lists the files it wrote.** The list comes from the log:
  `write_file` paths plus those four tools' `written` arrays. Read or fetched
  text is not trusted, even if it carries that key. A note opens in Notes;
  anything else opens in Agent files.
- **Knowledge lists stay current.** They reread when the section is shown,
  when a run finishes and on window return.
- **Knowledge's Recent tab.** It lists notes and agent files together, newest
  first, by day, without run memories.
- **The Notes tree.** It sorts by file name and shows the file name under a
  title that hides it. The open note or file scrolls into view.

**Executed:**

- **Backend:** tests first for every `written` array. Full suite **1097
  passed, 12 skipped**, with ruff and `mypy` clean.
- **Desktop:** tests first for the file selector (including untrusted
  `written` keys), the run's file chips and their folding, Recent's order and
  opening, and Knowledge rereading when shown or after a finished run. The
  data-file request and the tree's file names are covered too. ESLint and
  `tsc` are clean, and the full suite passed **566 tests in 55 files**.
- **Headless Chrome**, on a copy of the live data and a scratch sidecar:
  - The decision run showed "Wrote 1 file", and its chip opened the note.
  - The theses run showed three chips, and its risk file opened in Agent
    files.
  - A file written beside a scripted run appeared at the top of Recent 22
    seconds later, with no interaction.
  - Both themes were checked.

**Also this session** (`818a67b`, migration 026): Daily decision's supervisor
took the local date for the session's. It sent decision looking for theses
dated 2026-10-07, so the decision said its inputs were absent. The goal now
has decision read the date from the theses file names. The five-auction
Treasury response was 27,989 characters, past the 20,000 a fetch shows, so the
calendar now requests four fields.

Not verified: these window changes in the packaged app, and migration 026 on
a real model.

### First one-pass chain after the fresh start, and migration 025, 2026-10-07

The maintainer restarted the dev app (schema 24) and pressed **Run now** on
Morning collection at 18:10 Taipei, with the US market closed.

- **Morning collection completed** (`b7853d7b`):
  - `read_prices` reported the complete 2026-10-06 session, although the
    supervisor had assumed 2026-10-07. The movers row carries its `id`.
  - The news file is named for the local date and hour.
  - The calendar used one filtered query. Its five auctions read, for
    example, "9-Year 10-Month Note auction", and `as_of` is the run's start.
- **Theses and risk started on its own** (`31cdcc85`):
  - Bull cited a movers id and a news id and copied 333.63 and 345.34
    exactly. Bear wrote an empty file.
  - `check_limits` refused: "portfolio/computed.json is for 2026-10-07, not
    thesis date 2026-10-06". The gate kept Daily decision from starting.
- **Two causes:**
  - Told the time, portfolio-review passed the local date as `as_of`.
  - Leaving it out would also have failed, a latent fault since Phase 17:
    with nothing held, `compute_portfolio` dated the book by the day
    `positions.csv` was saved. October 1 passed only because that file was
    saved that day.
- **Fix** (`aabfc70`):
  - A cash-only book is computed for the newest session in
    `raw/prices/summary.csv`, and the `as_of` description tells models to
    leave it out.
  - Migration 025 has portfolio-review leave `as_of` out and date its review
    by the computed `as_of`.
  - The new test reproduces the live failure, `compute_portfolio` then
    `check_limits` for 2026-10-06. The full backend suite passed, **1095
    passed, 12 skipped**, and ruff and `mypy` are clean.
- **Rerun setup:** that session's generated files moved to
  `.dev/backups/session-2026-10-06-rerun-20261007-184500/`, so **Run now**
  can treat 2026-10-06 as new again. The two runs stay in history. Automatic
  management archived their saved-context notes, so no later run retrieves
  them.

Not verified: the chain to the decision with 025, which needs the dev app
restarted.

### Fixes from reviewing that chain, and a fresh start, 2026-10-07

The maintainer asked for every fixable finding below to be fixed and the
generated state cleared.

- **`read_prices` leaves out a session still trading** (`31a4719`), judged by
  the chart's `currentTradingPeriod`. The `2330.TW` recording, taken at 10:18
  Taipei, now yields 2026-09-29 until 13:30 and 2026-09-30 after. Live at
  23:19 Taipei on October 1, AAPL reported 2026-09-30 (49.9 million shares),
  not the partial day. Each movers row carries `id` `movers-{date}-{SYMBOL}`.
- **Every agent is told when its run started** (`0116f25`, `1a73c1e`): local
  time with its offset, and UTC, from `created_at`, in each system prompt.
  The first version read the run row before `run.started`, and a Discord
  run's reply then landed first; `test_channels` caught it, and the read now
  follows `run.started`.
- **Migration 024** (`cdb7cb9`). The goals name the session's date, not
  "today's", and Daily decision writes `decisions/{session date}.md`. The
  architects drop `raw/social-*`, copy figures exactly and may cite a movers
  `id`. The calendar's `as_of` is its collection time, an auction reads
  "4-Week Bill auction", and the query starts at the run's date. On a copy of
  the live database all five guarded rows moved, and their models, tools,
  policies and `updated_at` stayed.
- **Executed:** ruff, format and `mypy --strict` on both platforms; the full
  backend suite, **1091 passed, 12 skipped**, with the two existing warnings.
  No frontend file changed after `18c30f6`.
- **Fresh start**, with the app closed and rehearsed first on a copy:
  - Backup at `.dev/backups/fresh-start-20261007-180033/`, integrity `ok`,
    with the database, the space and every moved file.
  - Six runs, 822 events and 65 approvals were removed by the store's own
    deletion rule. 76 spend rows were detached; all 359 rows remain.
  - Last-run markers were cleared. Morning collection (missed since October
    2), Weekly knowledge and Weekly review moved to their next times, so
    nothing catches up at launch.
  - 23 generated files moved into the backup. The space holds the three
    `config/` files and `portfolio/positions.csv`.
  - A source sidecar on the rehearsed copy migrated it to v24 and started
    no run.

Not verified: the whole chain in one unattended pass, on a real model, with
these fixes. The first chance is Morning collection at 07:00 Taipei on
Thursday 2026-10-08, or **Run now** before then.

### First chain on the corrected history, and migration 023, 2026-10-01

With the dev app rebuilt, the maintainer moved the default space to ChatGPT
(GPT-5.6 Sol supervising Luna and Terra) and pressed **Run now** at 22:32
Taipei. Every output was checked against the tool results it came from.

- **Morning collection completed** (`e655ea47`). `market-movers` read the
  watchlist once and called `read_prices`: 3 steps, and no agent in the chain
  was stopped as stuck. The movers, price and portfolio files match their tool
  results. All 10 news records copy their `read_feed` ID, URL, title and
  timestamps exactly. The calendar holds the two auctions the Treasury had
  announced for October. Its `as_of` holds the bills' issue date, not a
  collection time: agents have no clock, and only the ChatGPT runtime gives
  them the date and zone. Run during US trading hours, AAPL's 2026-10-01 bar
  is a partial session (7.6 million shares against a 42.3 million mean).
- **Theses and risk wrote nothing** (`44245fa1`). Migration 021's goal began
  "Use only the movers file from today's new market session", and the
  supervisor told both architects to read nothing else. Movers rows carry no
  evidence id, and the architects may not write a thesis without one, so
  neither wrote a file. `check_limits` refused the missing bull file, and the
  gate kept Daily decision from starting, as designed.
- **Migration 023** (maintainer's choice of fix): the goal dates the stage by
  that movers file's session and sends the architects to the session's files
  in `raw/` and `portfolio/computed.json`. Bull and bear always write their
  dated file, empty when the evidence supports no call, and list `raw/` before
  reading. Only exact shipped text moves; models, tools, policies and
  `updated_at` stay. Not changed, by the same choice: evidence ids on movers
  rows, a clock for runs, and skipping an unfinished session.
- **Executed:** a scratch copy of the live space ran all four tools: prices,
  the empty book, scoring, and `check_limits`, which refuses missing theses
  and passes empty ones with no items. Migration 023 applied to a copy of the
  live database moved the goal and both prompts and kept their models. The
  three new migration tests failed before 023 was registered. The full
  backend suite passed, **1086 passed, 12 skipped**. A source sidecar on a
  fresh data folder (port 8790) migrated to v23 and served the new goal and
  prompts.

After a restart loaded 023, the maintainer ran the rest by hand on the same
session's files:

- **Theses and risk completed** (`7ed44190`) with no tool error. Bull wrote two
  AAPL predictions (5 and 7 sessions, confidence 0.54, both news ids found in
  `raw/news-2026-10-01-22.json`, invalidation at the session low 328.37). Bear
  wrote an empty file. `check_limits` passed AAPL on all three rules, and the
  risk review followed, so the gate started Daily decision.
- **Daily decision failed once** (`f25cfb3a`): ChatGPT refused the decision
  agent's second request as "flagged as potentially violating our usage
  policy". Its history held only the task, four `list_dir` calls and their
  listings; the six earlier `decision` runs on GPT-5.6 Terra were never
  flagged. **Run now** on Daily decision (`a8fbfabe`) sent a request of the
  same shape, which passed, and wrote `decisions/2026-10-01.md`: AAPL **pass**
  at 0% NAV, low conviction, with the three required sections and no figure
  absent from its inputs. The flag did not repeat, so it is treated as a
  false positive; a provider refusal still fails the run.
- **Still open:** the risk review and the decision's watch list name the
  missing `raw/social-*` input, which nothing produces (social sources are out
  of scope), and they read two routine Treasury bill auctions as market
  events. The chain has not yet run unattended from Morning collection to the
  decision in one pass, nor with real positions.

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

**Run now lists its run at once.** The maintainer saw a Run now take a while
to appear in Runs: Automations opened the run but left the list to the shell's
poll, every 30 seconds while nothing runs. It now rereads the list as Home's
Run once does. Executed: the new Schedules test failed first; ESLint, `tsc`
and the full desktop suite, **556 tests**, passed.

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
