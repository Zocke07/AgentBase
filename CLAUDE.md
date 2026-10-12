# CLAUDE.md

## Read first

Read [BUILD_SPEC.md](BUILD_SPEC.md) in full at the start of a session. It is the
design and constraint authority. This file holds current working context; the
[historical session record](docs/history/README.md) preserves earlier findings
and decisions. Read the relevant history when changing a boundary it explains.

The product and repository are **AgentBase**. Its bundle identifier is
`dev.agentbase.desktop`; preserve it after the one-time rename migration so
future changes do not relocate users' data or disconnect their stored keys.

## Current state

- **Market watch, BUILD_SPEC Phase 18 (2026-10-13).** A sidecar task beside
  the scheduler (`orchestrator/monitor.py`) reads Yahoo spark quotes for a
  space's holdings, watchlist and indexes every few minutes, 04:00 to 20:00
  New York time on weekdays, while `config/monitor.json` says
  `"enabled": true`. Moves past the file's thresholds become `market_alerts`
  rows (migration 030); one `monitor`-origin run per check, by the shipped
  `market-explainer`, writes `alerts/{date}-{HHMM}.md`, at most
  `max_explanations_per_day`, waiting while the space runs anything else.
  Alerts reach Home (badge on the rail), desktop notifications through the
  shell's `notify_alert` command, and a Discord channel set in
  `discord_alert_channel_id`. Only while the app is open; no catch-up.
- **Review of the 2026-10-12 extension (2026-10-13).** A forecast citing an
  annual or quarterly fact was refused (facts carry no publication time), so
  evidence now counts from its document's `fetched_at`, and screener rows are
  citable. Each session's workbook sheet is a row per ticker with every
  horizon's prediction beside its actual, plus an **All forecasts** sheet.
  The shared HTTPS helpers moved to `tools/builtin/fetching.py`. In the app,
  a workbook opens in the spreadsheet app through the shell's
  `open_workbook` command.
- **Failure repair, 2026-10-12.** Startup had launched three caught-up
  automations in Main together, and ChatGPT returned HTTP 429. Schedules now
  queue within a space, giving the chain priority and preserving due times;
  other spaces remain independent. ChatGPT 429 and SDK usage-limit metadata
  produce clear messages. One shared ChatGPT queue spaces requests by five
  seconds; the agent permits two bounded cooldown retries for temporary
  throttling, never for confirmed usage limits or partially streamed output.
  The user's retained host policy lacked Yahoo's feed host; the requested
  fresh retry adds that specific host and restores the six-stock example.
  Generated outputs are backed up outside the active vault before removal;
  credentials and failed-run history remain. Verification is recorded below.
- **Model refresh, 2026-10-12.** Catalog includes Haiku 5.5 and GPT-6.1 Sol;
  migration 029 upgrades untouched Anthropic fast example agents, and new
  OpenAI API spaces use GPT-6.1 Sol. Used spaces and edited models remain.
  GPT-6 API tool calling uses Responses with low reasoning and stateless
  encrypted reasoning replay. Long-context prices feed projected budgets.
  The user's ChatGPT model list still lacks GPT-6.1 Sol and GPT-6 Luna, so
  Main stays on its supported GPT-5.6 models instead of forcing an upgrade.
- **US research and forecast tracking extension, 2026-10-12.** Migration
  028 gives untouched investment agents market-wide Yahoo gainers, losers,
  volume leaders and headlines; cited annual/quarterly Yahoo financial data
  and optional SEC facts/excerpts; and immutable 1/2/3/5/21-session forecasts
  with daily sheets in monthly Excel workbooks. Nine first-use files now
  contain the requested sample: MU, ORCL, CRWV, MSFT, NOW, AVGO, one share
  each, USD 2,500 cash and limits 10/70/3. Unknown acquisition cost/date stay
  blank and P&L/duration stay null. Source failures are explicit; optional
  candidate quote gaps do not block valid holdings. Same-session retries can
  finish an interrupted decision/workbook. Fresh schedules use Tue-Sat 07:00
  local time, disabled until enabled; active/custom schedules, saved inputs,
  models and network policies are preserved. XLSX files download through
  Knowledge without entering the text editor. See docs/verification.md.
- The product was renamed to **AgentBase** on 2026-09-24. New installs use the
  AgentBase package, bundle, sidecar, schema, data, keychain and browser-storage
  namespaces. On its first canonical launch, an empty AgentBase data directory
  adopts the prior profile and its SQLite database. Legacy credentials, browser
  preferences and saved visualization schemas remain readable during the
  transition; current AgentBase values take precedence.
- Phases 0 through 9 and the spaces redesign are implemented. Do not restart
  Phase 0 or replace completed work from an earlier phase.
- **Phase 17 is implemented on `main`** (2026-10-01). The shipped investment
  pipeline now has Claude Sonnet 5.5 and migration 020, deterministic
  `read_prices`, `compute_portfolio`, `check_limits`, and
  `score_predictions` tools, migrations 021 to 027, nine starter files, and its
  four-chart dashboard. Fresh installs list Google News, Yahoo's chart host,
  and the Treasury API; used installs keep their saved host list. The remaining
  acceptance item is the maintainer's first daily morning-to-decision chain on
  a real model. Migration 022 repairs exact old shipped investment agent
  prompts and tool lists after model-only edits, preserving chosen models and
  genuine prompt edits. The shipped daily scheduler chain now stops on tool or
  model failures and requires verified price, portfolio and hard-rule results
  before starting downstream stages.
  The standalone roster design (`agentspace-investment-agents.md`) was folded
  into BUILD_SPEC Phase 17 and the user guide, then removed.
- **Unreleased on `main` since 0.4.8**, as recorded in `docs/verification.md`:
  - Phase 16.
  - Phase 17's end-to-end investment pipeline, migrations 020 and 021, four
    deterministic tools, starter inputs, and stable dashboard.
  - ChatGPT plan models: the account's model list bounds the pickers, defaults
    and mappings; a space and the strong shipped `decision` role on GPT-6 Sol
    are offered GPT-5.6 Sol.
  - Run review and navigation: a distinct Usage icon; Notes, Data files, and
    Saved context taxonomy; responsive text; a wider Markdown preview; a
    denser Runs view; a real network logo; automatic saved-context
    management; and distinct **Run now** provenance.
  - Charts handle settings objects, readable axes, repeated categories, and
    the pipeline dashboard. Usage has a slot for every day, follows the
    header meter, and scales a visible Y axis from actual usage.
  - Knowledge's Journal reads every dated report as one page, and the
    Visualize section is folded into Knowledge (2026-10-08): a data file in
    Agent files draws as a chart, and saved charts, dashboards and diagrams
    open drawn.
- **Autonomy first** (BUILD_SPEC Phase 16, 2026-09-29, merged to `main`, not
  yet released): autonomous workflows are the primary
  way a space runs. Fresh installs answer low and medium risk by policy;
  migration 018 pins upgraded installs to the answers they had. High risk
  (`run_shell`) is never answered by policy nor kept as a yes for the run
  (017). Agent writes to `memory/`, hidden folders and memory-typed notes are
  refused by the sandbox; a policy fetch reaches listed hosts only
  (`auto_approve_hosts`); the per-run cost ceiling is projected; a scheduled
  run's unanswered question expires after `unattended_question_seconds` and
  the run carries on; `run.started` records the policy and each automatic
  answer names its `rule`. Manual execution is **Run once** with **Step
  through** (`supervised`). Generated saved context defaults to conservative
  model-assisted management, the seeded pipeline ships switched off (019),
  and there is still no tray or service mode.
- The current release line is **0.4.8**: a steady run canvas, a folding event
  log, named start-up stages, a spending breakdown in the header, and spaces
  that own their provider with tier-mapped model switches and Opus 5.5 and
  GPT-6 in the catalog (migration 016), over 0.4.7's complete bounded RSS and
  Atom input for the news scanner, clearer setup guidance, and a responsive
  accessible window, over 0.4.6's rename to AgentBase across the product, package, bundle
  and data identifiers, with one-time adoption of a pre-rename install's data
  and database and read-through fallbacks for its keychain entries, browser
  preferences and saved visualizations, over 0.4.5's
  charts from CSV and JSON, portable agent-written visualization specs,
  dashboards, Mermaid, exports and visual RAG metrics, over 0.4.4's guards on
  runaway runs, per-run cost ceiling (migration 014) and data files in
  Knowledge, over 0.4.3's
  provider-change fix and folding rail (013), 0.4.2's model on each space
  (012), 0.4.1's investment roster (010) and per-tool answers (011), 0.4.0's
  schedules, Usage and tour, 0.3.3's run canvas and vault and 0.3.2's
  packaging. It includes the Windows installer and an ad-hoc signed,
  unnotarized Apple Silicon macOS disk image (a zip until 0.3.1; the image's
  Applications link keeps the app out of Downloads, where Gatekeeper
  translocates it and Spotlight ignores it). An incomplete first 0.2.0 Mac
  archive made Gatekeeper report that the app was damaged; the corrected
  bundle has a complete code seal. Check the release page and tag workflow
  for publication status and cross-platform CI evidence.
- The UI has a left rail, spaces, Home, Automations, Runs, Agents, Knowledge,
  Usage, Space settings, and app-wide Settings. Home lists a space's recent
  market alerts and Automations ends with its Market watch card. Knowledge separates Recent,
  Journal, Notes, Agent files, and Saved context, and rereads them when shown,
  when a run finishes and on window return (every section stays mounted). The
  Journal (`state/journal.ts`) is every note dated in its file name, outside
  `memory/` and `templates/`, newest first, read a week of dates at a time. A run lists the files its
  tools wrote (`state/files.ts`; the four deterministic tools report a
  `written` array) and opens each in Knowledge. Approvals are docked. The run canvas is a
  left-to-right workflow (goal, supervisor, workers, outcome) with an
  inspector; the Knowledge section is laid out as an Obsidian vault and one
  Markdown renderer (`components/Markdown.tsx`, over `lib/markdown.ts`)
  serves notes, agent prose and excerpts without ever emitting raw HTML.
  A first launch opens a tour, gated on the `onboarding_completed` setting.
  Copy is written for someone who is not a developer (BUILD_SPEC §0); the
  header shows the model's own name and a rounded spend that opens a
  breakdown (space share, runs, top models and spaces, per-run limit). The
  start screen names its stages (engine, settings, spaces) instead of a retry
  count. The run's event log folds to its latest step. React Flow nodes are
  declared `measured`, or every new layout remounts every edge (the canvas
  flicker). Motion is CSS on the
  chrome only, never on log-driven content, and stops under reduced motion;
  text meets WCAG AA in both themes; text containers wrap or scroll without
  fixed-width clipping; below 1,100 px the rail becomes a drawer
  (developer guide, "Motion, contrast and accessibility").
  Discord is the only chat adapter; Telegram was removed on 2026-09-11.
- A space can schedule runs (Automations): daily or weekly at a local time,
  every N hours, or after another schedule's run completes (a chain of at most
  four stages in one space), started through `RunLauncher` by one scheduler
  task in the sidecar; `RunLauncher.on_finished` tells it when a run ends. The
  app must be open; a missed time, or a run the app closed on, is run once at
  the next launch or skipped, per the schedule. There is no tray or service
  mode.
- The default space ships the ten-definition investment research roster
  (migration 010, 2026-09-19): four Haiku collectors, Sonnet analysts and a
  risk manager, an Opus decision agent, and a Sonnet reviewer, with no
  `run_shell`. Migration 015 gives `news-scanner` bounded `read_feed` input.
  Migration 020 moves untouched Sonnet roles to Sonnet 5.5. Migration 021
  gives market, portfolio, risk, and review roles the deterministic tools they
  require and narrows the untouched event collector to configured Treasury
  URLs. The three generic roles remain the starter roles for new spaces
  (`store/builtins.py`); 010 retires them from the default space only while
  untouched.
- Every space names its own provider and model (2026-09-27; migration 016
  wrote each inheriting space's provider into its row) and an agent may pick
  its own. The app-wide provider is only where a new space starts, and
  changing it moves no space; `settings.model` backs a row naming no model
  and follows the provider. `providers/catalog.py` gives every priced model
  a tier and a current flag: a provider switch maps the model to the
  target's current model at that tier or the nearest, a tie going cheaper
  (Opus 5.5 to GPT-6 Sol, by the maintainer's choice; where a ChatGPT plan
  lacks GPT-6 Sol, a space on it is offered GPT-5.6 Sol, balanced shipped
  agents on it GPT-5.6 Terra, and the strong shipped `decision` agent GPT-5.6
  Sol), and
  `GET /spaces/{id}/provider-switch` previews the switch and the agents it
  would strand, which Space settings offers to move. New spaces start on
  Sonnet 5.5, GPT-6 Sol, or GPT-5.6 Sol through a ChatGPT plan. Migration 020
  moves only an unused default space from Opus 5.5 to Sonnet 5.5. Existing
  spaces keep their models. A schedule may carry its own
  `max_run_seconds`, laid over the space's for its runs alone. `GET /runs`
  takes `origin`; an Automations **Run now** uses origin `automation`, while a
  timed start uses `schedule`. The Knowledge tree can delete a folder (backed up first);
  the rail folds to icons (Ctrl/Cmd+B).
- Three guards on runaway runs, all in `orchestrator/agent.py`: model
  answers may carry `MAX_OUTPUT_TOKENS` (16,384); an answer that hit the
  output limit is not run as a broken call but reported and nudged; an agent
  that fails the same way or makes the identical call `MAX_SAME_FAILURES`
  (3) times in a row completes with reason `stuck`. `max_run_cost_micros`
  (settings, spaces, migration 014; $2.00 by default, 0 off) fails a run
  that has spent it, checked before each model call like the deadline.
  Plain-text data files beside the notes are listed and edited through
  `/knowledge/files` and `/knowledge/file` (JSON parsed before a write).
- Knowledge's Agent files parse CSV, TSV, JSON and JSON-lines locally and draw
  bar, line, area, scatter, pie, metric and table views (`FileViews.tsx`;
  `lib/fileViews.ts` picks a file's views). A versioned `.viz.json` points at
  a data file, `.dashboard.json` composes saved charts and `.mmd` or
  `.mermaid` holds a diagram; each opens drawn, with Text for its source.
  Mermaid uses strict mode and its SVG is sanitized again before insertion.
  These are ordinary space files written through the existing gate; there is
  no visualization database or service, and no Visualize section since
  2026-10-08.
- The latest recorded database migration is 030 (market watch, above);
  029 is the model refresh and 028 the research extension. Migration 020 adds Sonnet
  5.5, updates untouched shipped Sonnet roles, and applies fresh space
  defaults without moving used spaces. Migration 021 wires the four
  deterministic tools and corrected goals into untouched pipeline rows, gives
  fresh installs the three-host list, and preserves used installs' saved
  behavior. Migration 022 repairs exact old shipped pipeline prompts and
  allowlists whose timestamps changed only because their model was edited.
  Migration 023 gives the theses stage the session's files instead of the
  movers file alone, and has bull and bear always write their dated file,
  empty when nothing is supported; exact shipped text only. Migration 024
  dates the chain by the market session rather than "today", drops the
  never-written `raw/social-*` input, and fixes the calendar's `as_of` and
  auction descriptions. Migration 025 has portfolio-review leave `as_of` to
  `compute_portfolio`, which computes the newest saved session. Migration 026
  has Daily decision read its date from the theses file names and the
  calendar request four auction fields. Migration 027 gives the decision a
  SOURCES section and reasoning for every row.
  Before those, 017 strips policy yeses for high risk, 018 pins
  upgraded installs to their old approval answers, and 019 ships the pipeline
  as disabled schedules. Existing workspace files are
  adopted into the default space once; new spaces get their own folders. Each
  space folder is also an Obsidian-compatible Markdown vault. The Knowledge
  section provides notes, properties, tags, links, backlinks, unresolved links,
  pins, filters, move with link rewriting, folder import, templates, daily
  notes, search, a graph and a retrieval evaluation. Local BM25 and
  hashed-vector RAG augments goals and handoffs with cited, untrusted excerpts
  that the Home preview and the run view show and the user can exclude.
  In the default **Automatic** mode, a bounded call to the space model audits
  generated run summaries and `propose_memory` notes after a successful run,
  keeping, archiving, or merging clear cases and sending uncertainty,
  conflicts, sensitive content, and consequential changes to **Needs
  attention**. **Review every item** preserves the manual flow and **Off**
  stops generated saved context. Management reasons, models, provenance, and
  backups remain visible; only available or pinned context is retrieved. The
  practical vault limit is 10,000 notes.
- OpenAI access can use either an API key or the user's ChatGPT subscription.
  Both remain the `openai` provider and share the same AgentBase behavior;
  Codex App Server is a credential and single-decision inference transport,
  never the agent orchestrator. Direct Claude subscription login is not
  supported because Anthropic does not permit third-party Claude.ai login or
  routing of Free, Pro or Max credentials. Its separate unmodified-Claude-Code
  embedding exception is not an interchangeable provider credential transport.

See [Verification](docs/verification.md) for executed checks, outstanding live
checks and release status. Keep that document current instead of growing a
second chronological log here.

## Working rules

- Follow BUILD_SPEC constraints and record agreed deviations there. Report
  what actually ran and what remains unverified.
- Use `just` for project tasks. Do not add `.sh`, `.bat`, `.cmd` or `.ps1`
  wrappers. Recipes must work with the configured host shell, including
  Windows PowerShell 5.1.
- Write a test before changes to the event store, budget ledger or sandbox.
  For other changes, choose checks that can detect a real behavioral failure.
- Commit logical units with descriptive messages. Keep a documentation move
  and its link updates together. Preserve existing uncommitted user work.
- No em dashes in repository prose, source or config; the hygiene test enforces
  this. Comments explain reasons and boundaries rather than restating code.

## Boundaries to preserve

- The orchestrator is hand-written. No agent framework and no new service
  infrastructure in the shipped app. Every bind is hardcoded to `127.0.0.1`.
- The append-only event log is the authority within a run. Live and replay
  use one reducer over an event prefix. Adding an event type updates the Python
  contract, generated TypeScript and reducer together. Model summaries are
  claims; executed tool calls are separate evidence.
- Every agent's system prompt states the run's recorded start in local time
  and UTC (`orchestrator/clock.py`); models have no clock of their own.
- A model's history keeps each assistant turn's `Message.tool_calls`, and
  every provider adapter resends them in its own shape with each result linked
  to its call. Without them, results looked unrequested and models repeated
  calls already answered until the stuck guard stopped them (2026-10-01).
- API keys, ChatGPT OAuth tokens and the Discord token live in the OS keychain.
  API keys reach the sidecar over stdin at launch; ChatGPT OAuth is owned by the
  pinned Codex runtime, which is fetched from the wheel `uv.lock` pins on the
  first sign-in (never frozen into the sidecar), and only safe account status
  reaches the local API. Never
  put secrets in SQLite, files, logs or argv. The webview can set/delete keys,
  not read them; API key changes require an app restart, which Settings offers
  through the shell's `restart_app` (stop the sidecar, then relaunch), never by
  re-reading keys into a running sidecar.
- Spawn-time key reads use the native `keyring` crate directly so a macOS
  access denial remains an error. Do not route these reads through the plugin's
  `get_password`, which discards the error. Ad-hoc builds can prompt again
  after a rebuild or upgrade.
- Tools validate and resolve in `prepare`, pass the approval gate, then run
  `execute`. Enforce the definition's allowlist independently of the tool list
  offered to the model. Filesystem tools use the run's space folder; writes
  resolve through `Sandbox.resolve_write_path`, and a network tool names its
  `host` in the prepared payload so the host list can bound it.
- Autonomy is the gate answering by policy, never the gate skipped. Only
  `POLICY_LEVELS` (low, medium) can be answered without a person. The
  scheduler never answers an approval. Changing a `DEFAULT_*` setting needs a
  migration that pins used databases, because unsaved keys read the constant.
- `run_shell` has a timeout and process-tree termination, but no OS filesystem
  or network isolation. Do not describe approval as a containment guarantee.
  `http_get` and `read_feed` check public addresses and connect to the checked
  address; redirects require a new checked request. `read_feed` accepts at
  most 2 MB of untrusted XML and returns no more than 20 complete entries.
- `RunLauncher` is shared by UI and Discord. It snapshots roster, rules and
  limits at run start. Worker delegation is sequential. A definition edited
  mid-run does not change that run.
- Approval rules can only narrow app-wide permission. Space `null` inherits;
  space `[]` asks for everything. Definition `[]` inherits. A denial of the
  same tool and original arguments persists for that run. Per-tool answers
  (`tool_policies`: ask, allow, deny) are read before the risk level; a space
  can only make one stricter, and a definition that names levels turns an
  allow outside them back into a question. A yes given "for this run"
  (`approvals.scope = 'run'`) answers every later call to that tool in the
  run, except for high risk, whose yes is always for one call; a no is never
  for a run.
- Budget arithmetic uses integer micros. Check before a call; persist spend
  before yielding its streamed completion. Deleting a finished run keeps its
  spend with `run_id` cleared, preserving the app-wide budget total.
- Spaces own rosters and app-managed folders. The default space cannot be
  archived or deleted; a space with runs must be archived or have those runs
  deleted first. Deleting a run leaves the files it wrote alone.
- Markdown is the knowledge source of truth. Retrieval rebuilds from the space
  folder on use, reparsing only changed files, and excludes hidden paths and
  symlinks. It never edits `.obsidian`, calls a remote embedding service, runs
  a background index job or treats retrieved prose as instructions. Automatic
  run memories use unique app-owned paths and are named in `run.completed`;
  a memory is retrieved only once approved or pinned. Merges and moves back up
  the files they change under `.agentbase/backups/`.
- Agents' outputs stay one dated file per session; the Journal only reads
  them. Do not make a model append to a growing file: `write_file` rewrites
  the whole file, `read_file` shows its first 20,000 characters, and a scored
  thesis must never change. Growing ledgers are written by deterministic
  tools (`scores/predictions.jsonl`, the price CSVs).
- Discord accepts explicit commands/mentions from allowed senders only. Its
  supervised adapter runs in-process and uses the same approval gate as the UI.
  Its one outbound path is `ChannelService.announce`, which posts market
  alerts to the configured channel with mentions disabled and reads nothing.
- The market watch's quote reads are app infrastructure, not tool calls: no
  agent chooses them, they hit one fixed Yahoo endpoint at a checked public
  address for symbols from the space's own files, and nothing fetched is
  followed. Anything an agent does about an alert happens in an ordinary run
  through the gate. The watch never answers an approval or edits a schedule,
  and tests get an offline quote client (`conftest.py`).

## Commands and release checks

```text
just setup             # install backend and frontend dependencies
just check             # lint, formatting check, Python/TypeScript typechecks
just ci                # check plus backend and frontend tests
just test-backend-cov   # backend statement coverage, not branch coverage
just schemas           # regenerate committed OpenAPI and TypeScript
just build-installer   # freeze sidecar, then build NSIS or macOS .app
just verify-build      # require built artifacts and verify their contents
just check-tauri        # Rust clippy; run after a sidecar exists
just paths             # cache, dependency and development data locations
```

`just typecheck` checks Python on the host and the opposite target platform.
`tauri-build` checks `externalBin` during clippy too, so Rust checks need the
frozen sidecar first. Never restore a cached Rust `target/` in release CI:
stale sidecars have previously survived bundling.

Windows smoke tests install the downloaded installer on a fresh CI runner
and launch its sidecar with Python removed from the environment. This is the
recorded substitute for a second Windows machine, not a GUI launch test or a
runner with Python uninstalled. Tag-triggered release publication must remain
gated on both build verification and the Windows install smoke test.

## Find details

- [Developer guide](docs/developer_guide/README.md): architecture, setup,
  debugging, testing, change checklists and packaging.
- [User guide](docs/user_guide/README.md): installation and the current UI.
- [Verification](docs/verification.md): current evidence and open checks.
- [Historical record](docs/history/README.md): phase reports and original
  decision reasoning, including superseded findings.

Code lives in `apps/backend` and `apps/desktop`; generated API contracts live
in `packages/schemas`. Development caches and runtime data stay under `.dev/`
through justfile exports. Installed apps use the OS local application-data
directory, not the repository. Tool installations and some Tauri tool caches
remain in their system locations.
