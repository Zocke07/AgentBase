# BUILD_SPEC.md: Autonomous Agent Co-Working Space

Build this project from an empty repository. Read this document before coding
and at every session start.

---

## 0. What we are building

A **local-first desktop application** where AI agents collaborate while the user
watches a live graph. Discord can also reach it.
*(Telegram was a second channel until 2026-09-11; see the note under Phase 8.)*

It ships as a single installer. The end user is not a developer.

### Primary success criterion

A user double-clicks, types a task, and watches every spawn, tool call, handoff,
and completion, with no terminal, Docker, or config files.

*(2026-09-29, at the maintainer's request: autonomous workflows are the primary
way a space runs, and typing a task is **Run once**. The criterion still holds
through Run once; Phase 16 records the change.)*

---

## 1. Hard constraints: do not violate these

These settled decisions are not interchangeable. Do not "improve," substitute,
or restore them; if one is wrong, **stop before implementing differently.**

| # | Constraint | Why |
|---|---|---|
| 1 | **No agent framework.** No LangChain, LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, OpenClaw. Write the orchestration loop by hand. | The visualization only works if we own the event stream. Frameworks emit their own event shapes and we would have to adapt them anyway. |
| 2 | **No Docker, no Postgres, no Redis, no LiteLLM proxy in the shipped product** (the Tauri app and the headless instance). | Single user, single machine. These systems solve multi-user fleet problems this application does not have. |
| 3 | **Everything binds `127.0.0.1` only.** Hardcode it. Do not make the bind address configurable. | Nothing reachable off-machine means nothing to accidentally expose. |
| 4 | **Model credentials go in the OS keychain.** API keys and OAuth tokens never go in `.env`, SQLite, config files, logs or argv. | The credentials sit on a personal laptop. |
| 5 | **Every filesystem/shell/network tool call passes an approval gate** before execution. No exceptions, no privileged paths for any channel. | This is the exact failure mode that produced dozens of CVEs in comparable projects. |
| 6 | **Chat channels trigger on explicit commands/mentions only.** Never ingest ambient channel messages into agent context. | Indirect prompt injection. A slash command has a schema; a channel firehose does not. |
| 7 | **Windows is the primary target.** macOS builds in CI and ships an ad-hoc signed, unnotarized Apple Silicon app on a disk image. | Windows-first; macOS release added at the maintainer's request on 2026-09-13; the zip became a disk image on 2026-09-18. |
| 8 | **Python 3.12 backend, TypeScript frontend.** No other languages except the Rust that Tauri requires. | |

---

## 2. Architecture

```
┌─────────────────────────────── Local machine ────────────────────────────────┐
│                                                                              │
│  ┌────────────────────────┐        ┌──────────────────────────────────────┐  │
│  │  Tauri shell (Rust)    │        │  FastAPI sidecar (PyInstaller bin)   │  │
│  │  ─ spawns sidecar      │───────▶│  ─ 127.0.0.1:8787                    │  │
│  │  ─ hosts React webview │  HTTP  │  ─ orchestrator + tools + channels   │  │
│  │  ─ keychain access     │◀───────│  ─ SSE event stream to UI            │  │
│  └────────────────────────┘  SSE   └───────────────┬──────────────────────┘  │
│                                                    │                         │
│                                    ┌───────────────▼──────────────────────┐  │
│                                    │  SQLite  (events, runs, spend)       │  │
│                                    └──────────────────────────────────────┘  │
│                                                    │                         │
│              ┌─────────────────────────────────────┼───────────────┐         │
│              │                                     │               │         │
│     ┌────────▼────────┐                  ┌─────────▼──────┐        │         │
│     │ Discord adapter │                  │ (a second chat │        │         │
│     │ (outbound WS)   │                  │  adapter slot) │        │         │
│     └─────────────────┘                  └────────────────┘        │         │
└────────────────────────────────────────────────────────────────────┼─────────┘
                                                                     │ HTTPS
                                                          ┌──────────▼─────────┐
                                                          │ Model provider API │
                                                          └────────────────────┘
```

**Only model inference leaves the machine.** Orchestration, tool execution, and
state stay local.

### The one idea everything hangs off

**Every agent action is an append-only event.** The UI purely projects that log;
live and replay share code, and reconnects resume by sequence number.

Never send an ad-hoc non-event websocket message. Fix the event contract instead.

---

## 3. Repository layout

```
agent-workspace/
├── CLAUDE.md                     # short pointer to this file + current phase
├── BUILD_SPEC.md                 # this document
├── .gitattributes                # * text=auto eol=lf
├── justfile                      # all dev commands (no .sh / .bat)
├── apps/
│   ├── backend/
│   │   ├── pyproject.toml        # uv-managed
│   │   ├── src/agentbase/
│   │   │   ├── main.py           # FastAPI app + lifespan
│   │   │   ├── config.py
│   │   │   ├── events/
│   │   │   │   ├── types.py      # event type enum + payload models
│   │   │   │   ├── store.py      # append / read / subscribe
│   │   │   │   └── bus.py        # in-process asyncio fan-out
│   │   │   ├── store/
│   │   │   │   ├── db.py         # SQLite connection + migrations
│   │   │   │   └── schema.sql
│   │   │   ├── providers/
│   │   │   │   ├── base.py       # Provider protocol
│   │   │   │   ├── anthropic.py
│   │   │   │   ├── openai.py
│   │   │   │   ├── ollama.py     # optional, local
│   │   │   │   └── pricing.py    # per-model token costs
│   │   │   ├── budget/
│   │   │   │   └── ledger.py     # monthly cap enforcement
│   │   │   ├── orchestrator/
│   │   │   │   ├── run.py        # Run lifecycle
│   │   │   │   ├── supervisor.py # planning + delegation
│   │   │   │   ├── agent.py      # worker agent loop
│   │   │   │   └── registry.py   # loads agent defs from DB, seeds built-ins
│   │   │   ├── tools/
│   │   │   │   ├── base.py       # Tool protocol + risk level
│   │   │   │   ├── approval.py   # human-in-the-loop gate
│   │   │   │   ├── sandbox.py    # path/exec restrictions
│   │   │   │   └── builtin/      # files, knowledge, network, shell
│   │   │   ├── channels/
│   │   │   │   ├── base.py       # ChannelAdapter protocol
│   │   │   │   └── discord_adapter.py   # telegram_adapter.py removed 2026-09-11
│   │   │   └── api/
│   │   │       ├── runs.py       # POST /runs, GET /runs/{id}
│   │   │       ├── stream.py     # GET /runs/{id}/events  (SSE)
│   │   │       ├── approvals.py  # POST /approvals/{id}
│   │   │       ├── agents.py     # CRUD on agent definitions
│   │   │       └── settings.py   # provider/key/budget config
│   │   └── tests/
│   └── desktop/
│       ├── package.json
│       ├── src/                  # React + Vite + TS
│       │   ├── App.tsx
│       │   ├── lib/
│       │   │   ├── events.ts     # SSE client, reconnect w/ Last-Event-ID
│       │   │   └── api.ts        # generated from OpenAPI
│       │   ├── state/            # Zustand run store
│       │   └── components/
│       │       ├── RunGraph.tsx  # React Flow canvas
│       │       ├── EventLog.tsx
│       │       ├── ApprovalDialog.tsx
│       │       ├── AgentList.tsx   # roster of defined agents
│       │       ├── AgentEditor.tsx # create/edit an agent definition
│       │       └── BudgetMeter.tsx
│       └── src-tauri/
│           ├── tauri.conf.json
│           ├── binaries/         # PyInstaller output lands here
│           └── src/main.rs       # sidecar spawn/kill + keychain cmds
├── packages/schemas/             # generated TS types from Pydantic
└── .github/workflows/build.yml   # macos-latest + windows-latest matrix
```

---

## 4. Data model

```sql
CREATE TABLE runs (
  id           TEXT PRIMARY KEY,        -- uuid4
  goal         TEXT NOT NULL,
  status       TEXT NOT NULL,           -- pending|running|paused|completed|failed|cancelled
  origin       TEXT NOT NULL,           -- ui|discord   (telegram until 2026-09-11)
  origin_ref   TEXT,                    -- channel/thread id for replies
  created_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id    TEXT NOT NULL REFERENCES runs(id),
  seq       INTEGER NOT NULL,
  agent_id  TEXT,
  type      TEXT NOT NULL,
  payload   TEXT NOT NULL,              -- JSON
  ts        TEXT NOT NULL,
  UNIQUE(run_id, seq)
);
CREATE INDEX idx_events_run_seq ON events(run_id, seq);

CREATE TABLE spend (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT REFERENCES runs(id),
  period       TEXT NOT NULL,           -- 'YYYY-MM'
  provider     TEXT NOT NULL,
  model        TEXT NOT NULL,
  input_tokens  INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_micros  INTEGER NOT NULL,        -- integer math only, never float money
  ts           TEXT NOT NULL
);
CREATE INDEX idx_spend_period ON spend(period);

CREATE TABLE agent_defs (
  id            TEXT PRIMARY KEY,        -- uuid4
  name          TEXT NOT NULL UNIQUE,    -- display name, referenced in handoffs
  role          TEXT NOT NULL,           -- one-line description shown in the UI
  system_prompt TEXT NOT NULL,
  provider      TEXT,                    -- NULL = inherit workspace default
  model         TEXT,                    -- NULL = inherit workspace default
  allowed_tools TEXT NOT NULL,           -- JSON array of tool names
  max_steps     INTEGER NOT NULL DEFAULT 20,
  auto_approve  TEXT NOT NULL DEFAULT '[]',  -- JSON array of risk levels, see §5 Phase 6
  is_builtin    INTEGER NOT NULL DEFAULT 0,  -- seeded defaults, editable but not deletable
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE approvals (
  id         TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL REFERENCES runs(id),
  tool       TEXT NOT NULL,
  args       TEXT NOT NULL,             -- JSON
  risk       TEXT NOT NULL,             -- low|medium|high
  status     TEXT NOT NULL,             -- pending|approved|denied|expired
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
```

*Phase 11 adds a `spaces` table and a `space_id` on `runs` and `agent_defs`, and changes
`agent_defs`' uniqueness to `(space_id, name)`. The SQL is in that phase, beside the
migration that introduces it.*

### Event types: this list is the contract

```
run.started        run.completed      run.failed        run.paused      run.cancelled
agent.spawned      agent.thinking     agent.message     agent.handoff   agent.completed
llm.request        llm.token          llm.response      llm.error
tool.requested     tool.approved      tool.denied       tool.called
tool.result        tool.error
approval.requested approval.resolved
budget.warning     budget.exceeded
channel.inbound    channel.outbound
```

New event types update `events/types.py`, generated TS types, and the `RunGraph`
reducer in one commit.

---

## 5. Build phases

Work **in order**; do not start before prior acceptance passes or build ahead.
Later additions retain original phase numbers for historical references.

### Phase 0: Scaffold and cross-platform hygiene

- `just` recipes for every dev task. No `.sh` or `.bat` files anywhere.
- `.gitattributes` with `* text=auto eol=lf`.
- `uv` for Python pinning, `.nvmrc` for Node.
- ESLint rule enforcing case-sensitive import paths (macOS/Windows filesystems are
  case-insensitive, Linux CI is not; this bug is invisible until CI).
- All paths via `pathlib` / `path.join`. Zero string concatenation of paths.
- `ruff` + `mypy --strict` on backend, `tsc --noEmit` on frontend, both wired into `just check`.

**Accept when:** `just check` passes on a clean clone.

### Phase 1: Packaging spike (do this early, not last)

Before feature work, prove packaging:

- A trivial FastAPI app returning `{"ok": true}`, compiled with `pyinstaller --onefile`.
- Tauri v2 `externalBin` pointing at it, a React page that fetches from it and renders the result.
- Build an actual installer on Windows (NSIS via `tauri build`) and launch it from a normal
  per-user install location.

Handle these traps now:
- `externalBin` requires the `-x86_64-pc-windows-msvc` suffix on the binary filename (target
  triple, not just `-windows` or `.exe`).
- Tauri caches the resolved sidecar under `target/release/`. A rebuilt binary can silently
  fail to make it into the bundle: verify actual bundle contents, don't trust the build log.
- With `--onefile`, Tauri only knows the PyInstaller *bootloader* PID, not the real child
  process. `process.kill()` will orphan the server. Implement graceful shutdown over
  stdin/HTTP and verify no stray `python`/sidecar process survives app quit (check Task
  Manager, not just that the window closed).
- The NSIS installer has a known issue where a stale cached sidecar binary is reused on
  reinstall/upgrade even after a clean rebuild: confirm the sidecar's file size/hash inside
  the produced installer matches the freshly built one before trusting a release.
- Tauri's webview on Windows requires the WebView2 runtime. Most Windows 11 machines have it
  preinstalled; Windows 10 machines may not. Bundle the WebView2 bootstrapper in the NSIS
  config so first install doesn't silently fail on an old machine.
- Build for `x86_64-pc-windows-msvc` only in v1. Windows-on-ARM exists but is niche enough
  to skip; treat it the same as local-model support: the abstraction shouldn't assume x64,
  but don't spend time building or testing it now.

**Accept when:** a built installer runs and serves on a machine with no Python
installed, then leaves no Task Manager orphan after close.

### Phase 2: Event spine

The core: get it right first.

- SQLite schema + migrations, DB file in the OS app-data dir (via Tauri's path API).
- `EventStore.append()`: assigns `seq` atomically per run.
- `EventBus`: in-process `asyncio` fan-out to subscribers.
- `GET /runs/{id}/events` as SSE, honouring `Last-Event-ID` to replay from a sequence number.
- A `fake_run` debug endpoint that emits a scripted sequence of ~20 events over 10 seconds.

**Accept when:** the debug run streams to `curl`; killing and reconnecting
mid-stream resumes with no gaps or duplicates.

### Phase 3: Providers, budget, keychain

- `Provider` protocol: `complete(messages, tools) -> Response` with normalized token usage.
- Implement Anthropic and OpenAI. Add an Ollama implementation behind the same protocol
  (local model support is optional at runtime but the abstraction must not assume cloud).
- `pricing.py`: per-model input/output cost. All money as **integer micros**, never floats.
- `budget/ledger.py`: monthly cap. Check *before* each call, record *after*. Emit
  `budget.warning` at 80%, `budget.exceeded` and refuse at 100%.
- Keys read from OS keychain via `tauri-plugin-keyring`, passed to the sidecar at spawn
  time over stdin, never as a command-line argument (argv is world-readable via `ps`).

**Approved addition, 2026-09-14:** app-wide OpenAI access is `api_key` or
`chatgpt`. Both build provider `openai` with the selected model ID and same
normalized response, orchestrator, catalogue, gate, events, ledger, and limits.
ChatGPT uses pinned Codex App Server only for credentials/inference. Since
2026-09-18, first sign-in fetches its `uv.lock`-pinned wheel to data storage,
checks size/SHA-256, and does not freeze it into the sidecar. Each call gets one
structured decision in an empty read-only directory with tools disabled; App
Server never owns the loop or executes AgentBase tools. OAuth stays in OS
credential storage and never reaches the local API. Subscription tokens use
selected-model API-equivalent pricing for the same local safety cap, not an
OpenAI API charge.

ChatGPT/API accounts can differ in entitlement and allowance. Preserve the
requested model and surface access errors; never substitute. *(2026-09-29:
a signed-in account's Codex `model/list` marks which priced models its plan
includes. Pickers, new-space defaults and tier mappings keep to them, the
space's pre-flight check names a model the plan lacks, and Space settings of
an OpenAI space offers the closest included models for it and its OpenAI
agents. A space on GPT-6 Sol, which stood in for the strong tier GPT-6 lacks,
is offered the plan's strong model, GPT-5.6 Sol; agents keep their own tier
(maintainer's choice, 2026-09-29). The app-wide check leaves the backing model to each space's check. A
run still never substitutes; an unknown, partial or unreadable list blocks
nothing.)* Direct Claude
subscription login is excluded because [Anthropic's authentication terms](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
forbid third-party Claude.ai/Free/Pro/Max credential routing. Anthropic uses an
API key; embedding unmodified Claude Code is a separate mode, not a transport.

**Accept when:** provider switching needs no code change, and over-cap runs fail
clearly before API calls.

### Phase 4: Orchestrator

- `Run` owns lifecycle and the event sequence.
- `Supervisor`: given a goal, decomposes into subtasks and spawns worker agents.
- `Agent`: the worker loop (think, call tool, observe, repeat) until done or budget/step limit.
- Agents communicate via `agent.message` events, never direct function calls. Handoffs are
  `agent.handoff` events.
- Hard limits: max steps per agent, max agents per run, max wall-clock per run. All configurable,
  all enforced, all emit a terminal event when hit.

**Accept when:** a two-worker run completes end to end, and its log alone
reconstructs exactly what happened without other state.

### Phase 5: Agent registry (user-defined agents)

Agents become editable data, not hardcoded classes.

- `agent_defs` table (see §4) plus CRUD endpoints in `api/agents.py`.
- `registry.py` loads definitions from the DB at run start. It no longer imports agent
  classes; it constructs workers from rows.
- Seed 3–4 built-in definitions on first launch (e.g. `researcher`, `writer`, `reviewer`)
  so a fresh install is usable immediately. Built-ins are editable but not deletable -
  `is_builtin = 1` guards the delete path only. *(2026-09-19, at the maintainer's
  request: the default space's built-ins are the ten definitions of an investment
  research pipeline, seeded by migration 010 with explicit Anthropic models and
  narrowed approval lists; the three generic roles remain as the starter roles a new
  space is seeded from. The security note below still holds: no seeded definition can
  run a shell, and only the three collectors can fetch.)*
- `allowed_tools` is an **allowlist, never a denylist.** An agent can only call tools named
  in its own row. An empty array means the agent can reason and hand off but touches nothing.
- A definition edited mid-run does not affect the in-flight run. Runs snapshot the
  definitions they started with; changing an agent is not a way to mutate a running agent.
- Validation on write: name uniqueness, non-empty system prompt, every entry in
  `allowed_tools` must resolve to a registered tool, `max_steps` within the global cap.
  Reject at the API layer with a readable message, not a 500.

**Security note.** User prompts never widen security. The next-phase gate runs at
*tool execution*, so even adversarial prompts cannot reach filesystem/shell
without it. Definition `auto_approve` only *narrows* workspace policy; code
that lets definitions escalate must stop.

**Accept when:** an API-created agent runs, while one omitting `write_file` is
blocked even if its prompt demands it.

### Phase 6: Tools and the approval gate

- `Tool` protocol with a declared `risk` level.
- Built-ins: `read_file`, `write_file`, `list_dir`, `search_knowledge`,
  `propose_memory`, `http_get`, `read_feed`, `run_shell`.
- **Sandbox**: a configured workspace root. Path traversal outside it is rejected before
  the approval prompt is even shown. `run_shell` has a hard timeout and process-tree
  termination. **2026-09-10 deviation:** the shared cross-platform build does not claim
  network or OS filesystem isolation for shell commands; the container addendum below is
  the optional stronger boundary for the maintainer's own instance.
- **Approval gate**: any `medium`/`high` risk call emits `approval.requested` and blocks
  until resolved. `low` risk (read within workspace) may be auto-approved by policy.
- Approval prompts must be **human-legible**, not raw JSON:
  `Agent "researcher" wants to delete report.docx: Allow / Deny`.
- A policy setting for unattended operation: pre-authorize a named risk subset so overnight
  runs can progress. Default is manual-approve-everything. *(2026-09-19, at the maintainer's
  request: beside the risk subset, an answer per tool by name, ask / always allow / never
  allow, read before the level; a space can only make one stricter and a definition that
  names levels narrows an allow outside them. The dialog gained **Allow for this run**, a yes
  recorded with scope `run` that answers every later call to that tool in the run. A no is
  never for a run: "never allow" is a Settings decision. Default is still ask-everything.)*
  *(2026-09-29, an agreed deviation, Phase 16: the default is **Autonomous**,
  low and medium answered by policy on fresh installs, and migration 018 keeps
  upgraded installs on the answers they had. High risk is never answered by
  policy nor kept as a yes for the run.)*

**Accept when:** an agent instructed to write outside the workspace root is
blocked at the sandbox layer, with `tool.denied` visible in the event log.

**Addendum: container-sandboxed `run_shell` (your instance only; not part of
the shared build).** The app sandbox does not prevent injected/misbehaving
shells from using your account.
On an always-on instance, wrap only `run_shell` in short-lived, network-disabled,
read-only (except workspace), CPU/memory-capped containers killed on timeout.
Do not containerize the rest of the app.

### Phase 7: Dashboard

- React Flow canvas: supervisor and workers as nodes, handoffs as edges, live status colour.
- Event log panel, filterable by agent and event type.
- Approval dialogs surfaced modally with the human-legible text from Phase 6.
- Budget meter: month-to-date spend against cap.
- Replay: scrub any past run from the event log using the identical rendering path as live.
- **Agent roster** (`AgentList.tsx`): every defined agent, its role, model, and tool count.
  Enable/disable toggle. Create and delete.
- **Agent editor** (`AgentEditor.tsx`): name, role, system prompt (textarea), provider/model
  dropdowns, tool allowlist as checkboxes, max steps. Surface the API's validation errors
  inline on the offending field, never a toast that loses which field was wrong.
  Tool checkboxes show each tool's risk level next to it, so the consequence of ticking
  `run_shell` is visible at the moment of ticking it.
- Generate TS types from the FastAPI OpenAPI schema; never hand-write the API types.

**Accept when:** replaying a completed run is pixel-identical to live, and the
app can create, edit, and run an agent.

### Phase 8: Channel adapters

- `ChannelAdapter` protocol. Both adapters normalize to
  `{channel, external_user_id, text, thread_ref, ts}` and emit `channel.inbound`.
- **Discord**: `discord.py`, own process. Slash commands and @mentions only. Do **not**
  request the `MessageContent` privileged intent: the non-privileged baseline is sufficient
  and keeps the review requirement and the attack surface off the table. Defer the
  interaction immediately (3s ack limit) and edit the deferred reply as events stream.
  Throttle outbound through the adapter; Discord's global cap is 50 req/s with tighter
  per-channel limits.
- ~~**Telegram**: `python-telegram-bot`, long polling (not webhooks; no inbound port). Leave
  privacy mode on. Respect 30 msg/s per chat.~~ **Removed 2026-09-11**, a §6 deviation
  agreed with the maintainer: the adapter was built and never held a session (no bot token
  ever existed), and its library was one of the two largest in the frozen sidecar. The
  `ChannelAdapter` protocol stays so a second channel can return; CLAUDE.md's decisions
  list has the reasoning.
- Map external user IDs to an internal identity so budget and permissions apply uniformly
  regardless of origin.
- A run started from Discord must appear live in the dashboard, and vice versa. Same event
  log, no special-casing.

*(2026-09-29, Phase 16: a fresh install lets the chat user who started a run
answer its questions (`originator`); migration 018 keeps `dashboard_only` for
upgraded installs. Chat offers a yes for the run for low and medium risk only.
Triggers are unchanged: explicit commands and mentions only.)*

**Accept when:** dashboard and originating chat observe the same run
simultaneously, and channel-originated calls hit the approval gate.

### Phase 9: CI and release

- **Tests gate builds.** Run backend `pytest` (at least event store, budget,
  sandbox, registry) and frontend `vitest` reducers (`RunGraph`, `EventLog`)
  first; red tests block build.
- Matrix: `windows-latest` and `macos-latest`. Build the non-cross-compilable
  PyInstaller sidecar on each, then Tauri bundle.
- Publish the Windows installer and, under the **approved 2026-09-13
  deviation** from the build-only macOS scope (constraint 7 and §7), an
  unnotarized Apple Silicon macOS archive. Developer ID, notarization, and
  Intel remain deferred. The **approved 2026-09-18 deviation** replaces the
  0.2.0 zip handoff with a Tauri `.dmg`: raw artifact uploads strip executable
  modes, while the image preserves the app and adds an `/Applications` link;
  it also avoids the Downloads/Gatekeeper translocation caused by zips. Build
  with `CI=true` to skip Tauri Finder AppleScript. Before publishing, mount and
  verify bundle version, shell/sidecar hashes, modes, DB startup, and shutdown.
- **Keep the repo public.** Private Actions use 2x Windows and 10x macOS
  minutes; macOS build is the cost to watch.
- Keep Windows unsigned. Document SmartScreen **More info → Run anyway**;
  an optional EV certificate removes it.
- Document macOS **Privacy & Security > Open Anyway**, scoped
  `xattr -dr com.apple.quarantine /Applications/AgentBase.app`, and update
  keychain prompt. 0.2.0's corrected archive uses Tauri ad-hoc signing with
  strict verification; hardened runtime remains disabled because it breaks
  re-signed PyInstaller library loading. Revisit runtime and entitlements with
  Developer ID/notarization; do not add permissions this release does not use.

**Accept when:** green CI produces a downloadable installer that runs on a
second Windows machine without Python.

### Phase 11: Spaces, and the redesign around them

*Added 2026-09-11 at the maintainer's request; review this §4-changing design
before coding (§6, "ask before deviating").*

*Built 2026-09-12. Requested redesign first ran (4)–(7) against one workspace,
then (1)–(3), (6), and (8), so switcher/settings could drop in. Dated inline
notes resolve open or incorrect design questions.*

**The idea:** users define a *coworking space*, then assign agents. Runs use
that space's agents, rules, and folder.

**What a space is.** A named **roster** (each definition has one space),
**folder** (run-tool sandbox root), and **rules** (model, approvals, limits,
inherited or overridden). Runs belong to their starting space. API/bot
credentials, monthly cap, Discord connection, and allowlist stay app-wide.

**What a space is not.** A tenant, account, or user-selected project directory.
§7 applies. In v1 the app creates its folder, limiting approval-misclick blast
radius. *(2026-09-12: Settings shows/opens, never changes, that path.)*

#### Data model (§4 additions)

```sql
CREATE TABLE spaces (
  id            TEXT PRIMARY KEY,        -- uuid4; the default space's is a fixed literal
  name          TEXT NOT NULL UNIQUE,
  description   TEXT NOT NULL DEFAULT '',
  provider      TEXT,                    -- NULL only before migration 016; see below
  model         TEXT,                    -- NULL only for an untyped Ollama model
  auto_approve  TEXT,                    -- NULL = inherit; else JSON array, narrows only
  max_steps_per_agent INTEGER,           -- NULL = inherit; a space may set these either way
  max_agents_per_run  INTEGER,
  max_run_seconds     INTEGER,
  archived      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
-- agent_defs gains  space_id TEXT NOT NULL REFERENCES spaces(id)
--   and its UNIQUE(name) becomes UNIQUE(space_id, name): a name is unique in its roster,
--   which is the only place the supervisor ever resolves one.
-- runs gains        space_id TEXT NOT NULL REFERENCES spaces(id)
-- spend, approvals, events are unchanged: they hang off runs, and a run knows its space.
```

The folder is derived, not stored: `<data dir>/spaces/<id>/`; rows cannot name
external paths and renames do not move files.

- **Migration 006** creates `spaces`, inserts the default space (fixed id, name `Main`,
  every rule NULL, so it behaves exactly as the single workspace does today), and moves the
  existing workspace folder to become its folder. Then `agent_defs` and `runs` gain
  `space_id`, backfilled to the default space. **Trap, known in advance:** SQLite will not
  `ADD COLUMN ... REFERENCES` with a non-NULL default while foreign keys are on, and cannot
  add `NOT NULL` without one, so both columns arrive by table rebuild (create, copy, drop,
  rename), and the runner needs a way to run one migration with the FK check deferred. Write
  the upgrade test first, against a populated v5 database, and assert every run, event,
  definition, approval and spend row is still there afterwards, with a space.
- **The default space cannot be archived or deleted.** Something has to receive a run whose
  space was not named.
- **A space with runs cannot be deleted; it can be archived.** Runs are history and history
  is the product (§2). Archived spaces leave the switcher and keep their runs viewable.
  Deleting a space with no runs deletes its agents.

#### Rules resolve in layers; approvals only narrow

For `auto_approve`, `effective = definition ∩ space ∩ app-wide`; neither
definition nor space grants absent app policy. A space's NULL inherits, while
`[]` asks for everything; nullable storage preserves that difference.
The definition column remains non-NULL `[]`, retaining its Phase 6 behavior.
Models/limits override rather than narrow, so spaces can run longer while app
budget still bounds cost. `run.started` records effective rules and
`space: {id, name}` for replay.
**No new event types** are required.

#### API

- `GET /spaces`, `POST /spaces`, `GET /spaces/{id}`, `PATCH /spaces/{id}`, `DELETE /spaces/{id}`
  (409 while it has runs; 409 for the default). `POST /spaces` takes
  `seed: "empty" | "builtins" | {"copy_from": "<space id>"}`: a new space starts empty,
  with fresh copies of the three seeded roles, or with copies of another space's roster.
  Copies are new rows with new ids and `is_builtin = 0`.
- `GET /agents?space_id=`, `POST /agents` takes `space_id` *(2026-09-12: optional, the
  default space when omitted: the same reading as `POST /runs`, and for the same reason;
  the window always names the space it is showing)*, `PATCH /agents/{id}` may set
  `space_id` (a **move**; an in-flight run's roster is a snapshot, per Phase 5, so a move
  mid-run leaves that run alone), `POST /agents/{id}/copy {space_id}`.
  `POST /spaces/{id}/seed` adds the built-in roles an existing roster lacks.
- `GET /runs?space_id=`; `POST /runs {goal, space_id?}`: omitted means the default space,
  which is what keeps `POST /debug/fake_run` and today's Discord path working unchanged.
- `GET /budget?space_id=` adds this space's spend for the period beside the app-wide cap.
  Derived by joining `spend` to `runs`; no new column.
- `WorkspaceSettings.channel_space_id` (NULL = default): where `/agent` from Discord runs.
  *May:* an optional `space` option on the slash command, autocompleted from names.
  *(2026-09-12: not built. One setting is the whole of it; a stored id for a space since
  deleted falls back to the default at launch rather than turning every command into an
  error nobody in the channel can fix.)*
- Every filesystem tool resolves against the run's space folder. `Sandbox` is constructed
  per run from the space, not once per process, and a `write_file` from a run in space A
  to a path under space B's folder is `tool.denied` with `blocked_by: "sandbox"`, exactly as
  a path outside the old single root is today.

#### The redesign

This space-shaped redesign replaces dashboard chrome, not run projection:
graph, log, and summary remain one pure `run-projection` fold, protected by
`replayIdentity.test.tsx` throughout.

- **Sidebar, not tabs.** Persistent rail: top **space switcher** (current,
  switch, **New space…**); current *Home*, *Runs*, *Agents*, *Space settings*;
  bottom app-wide *Settings* (keys, budget, Discord). Header retains global
  monthly budget, selected-space provider/model, and all-space approval badge
  that opens its run.
- **Home per space.** Goal + Start; **Now** cards for active runs/approvals;
  **Recent runs** cards (status, goal, start, duration, cost); roster roles/
  toggles with add/seed controls. First-launch cards handle missing key,
  agents, or runs, including Settings/demo-run paths.
- **Plain language, raw types retained.** Event rows, cards, and statuses have
  reducer-derived sentences, alongside muted `llm.request` / `tool.called`
  mono chips for diagnosis. Identity tests cover the pure mapping.
- **Fold-derived "Now" line.** It summarizes current cursor activity identically
  in live/replay.
- **Type and colour.** System prose font (Segoe UI/SF), monospace only for IDs,
  payloads/code; 15px, 1.5-line prose, no uppercase micro-labels. Tokenized
  light/dark themes follow OS with Settings override; use one accent, existing
  risk meanings, five status colors, neutral card elevation, no decorative color.
- **Runs are cards; events remain rows.** The picker uses cards, while the
  graph-checking event table adds sentence column.
- **Approval stays docked** with risk edge, sentence question, collapsed history,
  and focused Deny.
- **Separate space/app settings.** Space page: name, description, shown folder
  and Rust-only **Open folder** restricted to data root, model, approval/limits
  with **Inherit** first, and archive/delete. The command grants no general
  JavaScript opener to the webview. App settings provide inherited limits/
  approval defaults, theme, and `channel_space_id`. Since 2026-09-19, Settings
  selects provider, each space names a non-inherited model (migration 012
  filled prior values), and agents may override it. Since 2026-09-27 a space
  also names its provider (migration 016 filled prior values): the app-wide
  provider is only where a new space starts, a provider switch maps the model
  by tier (`providers/catalog.py`), and Space settings offers to move the
  agents that name the old provider's models.
- **Windowed log.** Long runs render visible rows only; deferred until >291
  event measurement, but redesign touches rows and Home no longer opens log.
- *(2026-09-29, Phase 16: an **Automations** section follows Home in the rail
  and holds the schedules; Home leads with what runs on its own, then Now,
  then **Run once**. Space settings no longer holds schedules.)*

**Order:** (1) test-first migration 006/store; (2) `space_id` through launcher,
per-run sandbox/roster, verified in two real-model spaces; (3) API/types;
(4) rail/switcher/Home; (5) run restyle; (6) settings; (7) log windowing;
(8) Discord `channel_space_id`. Commit each small step and record live results.

**Accept when:**

1. A real local-model run in space A cannot spawn a named B agent; `agent.spawned`
   lists only A and log records refusal.
2. A writes land under A; A writing B produces `tool.denied` with
   `blocked_by: "sandbox"`.
3. Populated v5 opens as v6 preserving every run, event, definition, approval,
   and spend row, with all runs, definitions, and workspace files under the
   default space.
4. From fresh data entirely in-window: create/seed space, set key, run/approve,
   replay identically in both themes.
5. `GET /budget` enforces app cap across spaces and reports each spend.
6. Re-run all Phase 6–8 criteria in new UI.

### Phase 12: Markdown knowledge vault and retrieval-augmented memory

*Added 2026-09-15 at the maintainer's request, replacing v1's no-vector-memory/
RAG non-goal.*

Each space folder is an Obsidian-compatible vault. Markdown stays canonical
across AgentBase/Obsidian/other editors; no proprietary copy or Obsidian install.

- Add **Knowledge**: browser, source, safe preview, YAML/tags, wikilinks/
  backlinks, local search, and note graph.
- **Open in Obsidian** is a narrow Rust command for existing data-root dirs;
  it constructs `obsidian://open?path=` and grants no webview URL opener. Offer
  it only at installer-default Obsidian locations; its picker still opens vaults.
- Index live folders on use, so next list/search/run sees external edits without
  watcher, reindex task, or stale database.
- Local retrieval combines deterministic hashed vectors with term/title/tag
  overlap; return heading chunks with stable `[[path#heading]]`, never remote
  embeddings.
- Retrieve cited, untrusted context for goals and handoffs. `run.started`
  preserves supervisor excerpts; workers retain them in `llm.request`.
- Before `run.completed`, successful runs write goal/outcome to the unique
  app-owned `memory/runs/<run-id>.md` and record `memory_path` for retrieval/
  replay.
- Add low-risk approval-gated `search_knowledge`. Migration 007 changes seeded
  roles only when their allowlist remains shipped; user edits stay unchanged.
- Exclude/uneditable hidden paths (especially `.obsidian`); note paths stay in
  per-run sandbox and end `.md`.

**Accept when:**

1. A Markdown file edited outside AgentBase appears with its YAML properties,
   tags, outgoing links and backlinks, and the graph carries the same edges.
2. Retrieval ranks a relevant heading above unrelated notes and returns a
   stable citation without making a network call.
3. A run receives cited goal context, completes, writes a run-memory note and a
   later retrieval can find that outcome.
4. Traversal, absolute paths, non-Markdown paths and `.obsidian` writes are
   refused before touching a file.
5. The native Knowledge section can create, edit, preview, search, link, graph
   and delete notes, and the Rust shell still grants the webview no opener
   permission.

**0.3.0 additions, agreed 2026-09-17.** Run memories and medium-risk,
approval-gated `propose_memory` notes start `proposed`; they are retrieved only
after approval or pinning, and migration 008 changes only unedited seeded roles.
Inbox supports archive, forgetting, and merging that archives and backs up
originals, alongside source/time/confidence/citations. Ranking adds BM25,
folder/tag/type/date/pin/status filters, two chunks/note, and English-function-
word removal. Parse once and scan without resolving every path for 10,000 real-
file timing-tested notes, still rebuilt on use. Home previews citations, scores,
matches, token cost, and provider/model, and lets users exclude citations;
`run.started` preserves excerpts and exclusions for **Retrieved context**. Vault adds
move/rename link rewrite, import, pin, unresolved/orphan counts,
templates/daily notes, **Save as note** from an event, and MRR/recall
evaluation. Defer local embeddings, attachments, PDFs, and web clipping.

### Phase 13: Scheduled runs, usage, and the first-run tour

*Added 2026-09-19 at the maintainer's request.*

- **Schedules.** Spaces run daily or on chosen local days at a local time, or
  every N hours, through the same `RunLauncher` as window/Discord, inheriting
  roster, rules, folder, gate, and shared cap; scheduler never approves. Store
  `next_run_at` UTC and recompute it from the clock, never the previous time.
  With app closed (no headless/tray/service), next launch runs once or skips by
  missed policy, never one catch-up per occurrence.
- **Usage.** Monthly spend-ledger totals by model/space/day and costliest runs
  with peak/mean input context; show no estimates or non-ledger figures.
- **Tour/About.** Point to real UI then demo run once by `onboarding_completed`;
  About replays it and shows sidecar version/data folder.
- **Memory near run.** Summary shows memory status, approves in place, opens
  beside inbox, and folds long text to keep canvas/log visible.

*(2026-09-29, Phase 16: a schedule may start **after** another schedule's run
completes, forming a chain in one space of at most four stages; a run the app
closed on is run again once or noted, by `missed`; Run now goes through the
scheduler. The scheduler still never answers an approval; a question in a
scheduled run expires after `unattended_question_seconds`.)*

*(Maintainer choice of 2026-10-01: a timed or catch-up launch keeps origin
`schedule`; the Automations **Run now** button records origin `automation` and
the schedule id in `origin_ref`. Both remain unattended and may start the next
stage in a chain.)*

**Accept when:**

1. A daily schedule created the evening before a DST switch fires at the
   named wall-clock time the next morning, and a schedule due while the app
   was closed runs once at launch or is skipped, per its policy, with the
   following time computed from the clock.
2. A scheduled run appears in Runs with origin `schedule`, and a space that
   asks for everything is told so beside its schedules.
3. The Usage totals for a month equal the budget meter's figure for the same
   month, and a run's peak context equals the largest `input_tokens` among its
   ledger rows.
4. The tour opens exactly once per fresh data directory and never on a
   settings document without the flag.

### Phase 14: Local visualization files, dashboards and diagrams

*Added 2026-09-24 at the maintainer's request for release 0.4.5.*

Visualization uses ordinary space files: no chart DB, remote renderer, or new
agent tool. Agents use approval-gated `write_file`; people edit the same files
in Knowledge.

- **Visualize** parses CSV/TSV/JSON/JSONL/NDJSON locally into bar, line, area,
  scatter, pie, metric, or table charts with category/values/series/aggregate/
  sort/bounded rows; all offer accessible source table and SVG/prepared-CSV export.
- Charts use validated, versioned relative-source `.viz.json`
  (`agentbase://visualization/v1`); dashboards use validated one/two/three-
  column `.dashboard.json` (`agentbase://dashboard/v1`) listing saved chart
  paths. Validate both before rendering; both stay small enough for direct
  model writing.
- Editable `.mmd`/`.mermaid` render with strict Mermaid and disabled HTML
  labels; parse returned SVG and strip scripts, objects, event attributes, and
  external links before insertion; export SVG.
- Add decision-relevant relevance, MRR/recall, and memory-trust visuals while
  retaining authoritative run/knowledge/Usage projections.
- Bound parsing at 10,000 and rendering at 2,000 rows. Invalid/missing data or
  contracts are readable errors, never code execution. Nothing in a
  visualization is an agent instruction.

**Accept when:**

1. A CSV and a nested JSON file can be opened, configured as every chart type,
   inspected as a table and exported without a network call.
2. An agent-compatible `.viz.json` can be saved, reopened and composed into a
   persistent dashboard whose charts reread their source files.
3. A Mermaid file renders locally, and a returned SVG containing a script,
   event handler, embedded object or external link loses all four before DOM
   insertion.
4. Retrieval, evaluation and memory metrics retain their textual values and
   add accessible visual equivalents.
5. The existing approval gate, sandbox, event contract, replay and budget
   ledger are unchanged.

### Phase 15: Complete, bounded RSS and Atom ingestion

*Added 2026-09-26 after the first live Google News RSS scan exposed a response
cut through an XML item.*

The generic HTTP tool deliberately returns only 20,000 characters to a model.
Feeds can be much larger, so raising that model-facing limit would spend more
context while still making completeness depend on feed size. Feed structure is
handled locally instead.

- Add `read_feed`, a medium-risk network tool that uses the same public-address
  check, pinned address, host header, TLS name and no-redirect rule as
  `http_get`.
- Stream at most 2 MB, parse untrusted RSS or Atom with entity expansion and
  external entities disabled, discard markup and return at most 20 complete
  entries. Titles and summaries are bounded before entering model context.
- Normalize publication timestamps and publisher domains. Generate each
  entry's ID as SHA-1 of the returned URL plus title and a separate normalized
  title key for cross-feed deduplication. Locally collapse the same ID, or the
  same title within 24 hours, keeping the earliest publication.
- Migration 015 changes the built-in `news-scanner` only when both its prompt
  and allowlist are still the shipped values. Customized definitions remain
  byte-for-byte unchanged.

**Accept when:**

1. A Google News-sized feed returns bounded, complete records rather than a
   truncated XML prefix, and the identifier for each record is reproducible.
2. RSS and Atom dates, links, publisher domains and summaries are normalized,
   while malformed XML, entity declarations, private addresses, redirects and
   an input over 2 MB are refused.
3. A version-14 database migrates the untouched scanner to `read_feed`, while
   an edited prompt or allowlist is preserved.
4. The approval UI and run graph identify a `read_feed` call as a feed read,
   with the same medium-risk approval semantics as other network access.

### Phase 16: Autonomy first

*Added 2026-09-29 at the maintainer's request: "autonomous agent workflows are
the primary architecture, with manual execution an optional fallback or debug
mode", with the shipped examples showing automated execution, after the
patterns of Hermes Agent and Grok's mention-driven bot. Deviations from Phase 6
and Phase 11 agreed the same day.*

Autonomy here means the gate answers by policy; it never means the gate is
skipped (§1 constraint 5). The maintainer chose (asked 2026-09-29):

1. **Fresh installs start Autonomous**: low and medium risk are answered by
   policy. Upgraded installs keep their answers (migration 018 pins them).
2. **Memories keep the inbox**: one is retrieved only once approved or pinned,
   including from unattended runs.
3. **The seeded pipeline ships switched off**; Home turns it on in one click.
4. **Automation runs only while the app is open**; §7's headless/service
   non-goal stands.

**Saved-context management, maintainer choice of 2026-10-01.** This supersedes
item 2's requirement for a person to approve every generated memory and the
deferred automatic-memory note below.

- Saved context starts in **Automatic** mode for fresh and existing installs
  that have not selected a mode. The selected model for the space audits new
  generated context and previously approved context after each successful run.
- It may keep or dismiss new context, or combine clearly overlapping context.
  It may not silently dismiss approved context. Conflict, uncertainty,
  sensitive material, and consequential changes return to **Needs attention**.
- Model output is untrusted data and must validate against the exact offered
  paths before any write. Invalid output or provider failure leaves generated
  context in **Needs attention** and does not turn a successful run into a
  failed run.
- Every automatic change records the model, action, reason, and time in the
  Markdown note. The original file is backed up under `.agentbase/backups/`.
  Automatic management never permanently deletes a memory.
- **Review every item** retains the earlier manual queue. **Off** creates no
  run summary and policy-denies `propose_memory`. Approved or pinned context
  remains retrievable until a person changes it.

What makes a policy answer safe, all below or inside the gate:

- **High risk is never answered by policy.** Settings, spaces, migration 017
  and the gate refuse a policy yes or a run-scoped yes for `run_shell`.
- **App-owned paths are refused to agent writes**: `memory/`, hidden folders
  and memory-typed notes, before the gate (sandbox).
- **Fetches by policy reach listed hosts only** (`auto_approve_hosts`; `*` for
  any public host, pinned for upgraded installs); any other host asks.
- **The per-run cost ceiling is projected** with the next call's pessimistic
  cost, as the monthly cap is.
- **A question nobody is there to answer expires**: in a scheduled run after
  `unattended_question_seconds` (120), and the run carries on without the call;
  the identical call is not asked again in that run.
- **`run.started` records the policy** the run acted under, and every
  automatic answer names its rule, so the log explains what no person saw.

Manual execution remains as **Run once** with **Step through**
(`POST /runs {supervised: true}`: every call asks, refusals stay), and a
space's own empty policy (**Supervised**). Schedules gain the `after` cadence,
Run now through the scheduler and the interrupted re-run (Phase 13 note);
Discord answers default to the originator (Phase 8 note); an Automations
section leads the window (Phase 11 note). Migration 019 widens five untouched
roster agents from low to low and medium, corrects the news scanner's role,
and seeds the pipeline as five disabled schedules in the default space.

Not built, by the constraints: skipping the gate, auto-approving `run_shell`,
triggers from ambient chat or webhooks, and agent-authored schedules or runs.
Left for later: an outbound Discord notice channel
for scheduled outcomes; a cap on scheduled runs going at once (each schedule
still never overlaps itself, each run has its time and cost ceilings, and the
monthly cap holds; deferring a due run safely needs a queue the scheduler does
not have); forwarding the waiting-question count to the native window title.

**Accept when:**

1. A fresh install runs a scheduled chain of stages that read, write and fetch
   from listed hosts with no person answering, and every automatic answer is
   in the log with its rule; an upgraded install still asks before each call.
2. No setting, space, definition, migration or button can make `run_shell`
   run without a person's yes for that call.
3. A policy-approved write to `memory/`, a hidden folder or a memory-typed note
   is `tool.denied` with `blocked_by: "sandbox"`, and a fetch to an unlisted
   host asks.
4. A scheduled run's unanswered question expires after the configured wait,
   the run continues, and the same call is not asked again.
5. A run stops before a model call that could cross its cost ceiling.
6. Run once with Step through asks before every call, and a replay of a run
   recorded before this phase is unchanged.

### Phase 17: The investment pipeline runs end to end

*Designed 2026-09-30 at the maintainer's request, after an audit of the
shipped roster against the maintainer's plan; **not built**. It adapts and
replaces the maintainer's standalone roster design (`agentspace-investment-agents.md`,
the source of migration 010's prompts), which was removed from the repository
root once its content lived here and in the user guide. It adds built-in tools
to Phase 6's list: settle the decisions below with the maintainer before
coding (§6, "ask before deviating"). Its first unit, added the same day,
brings in Claude Sonnet 5.5 and changes the model a new space starts on
(**Models**, migration 020).*

**The plan.** The maintainer's pipeline: collect news and trends (1a, also
Reddit and past events), study concepts and companies (1b), read stock
movement and the top gainers and losers (1c), and upcoming events, earnings
and government releases (1d); review the portfolio (2a), argue bull and bear
cases over 1, 3, 5 and 7 days with measured accuracy (2b), and manage risk for
the book and the recommendations (2c); give a decision with a table (3a) and
review the analysts for performance and learning (3b). Migration 010 ships one
agent per step (2b as `bull-architect` and `bear-architect`), and 019 chains
them as five schedules, switched off.

**Why it does not run end to end yet** (audit and source probes, 2026-09-30):

- The prompts depend on five scripts that are neither shipped nor runnable:
  no seeded agent has a shell, and nothing runs outside a run. So nothing
  writes `portfolio/computed.json` (2a), `risk/rule-checks-{date}.json` (2c),
  `scores/predictions.jsonl` or a scorecard (2b's accuracy, 3b), or the
  movers' derived figures (1c). There is no `portfolio/positions.csv` template.
- The template's only price source stopped answering programs: `stooq.com`
  returned HTTP 200 with a JavaScript browser check instead of CSV, so
  `market-movers` gets no prices.
- `http_get` shows a model at most 20,000 characters, so the Fed's 165 KB
  FOMC calendar page never reaches its dates, and `bls.gov` refused a program
  that sent no identifying header (403). Hosts off the list ask, and in a
  scheduled run the question expires after 120 s, so 1d stays mostly empty.
- Reddit (1a) needs a registered OAuth app, per the design (not probed); SEC
  filings (1b) need an identifying `User-Agent` that `http_get` cannot send.
  Market-wide gainers and losers, and earnings dates, have no verified
  keyless source.
- The design's route for keyed sources (Finnhub, Alpha Vantage, FRED and
  others), a key in the URL's query string, would put a secret in a space
  file, the model's context and the event log (§1 constraint 4).
- A shipped agent moved between providers loses its level: `decision` (Opus)
  became GPT-6 Sol, then GPT-5.6 Terra on a ChatGPT plan, because GPT-6 Sol
  stands in for both Opus and Sonnet and agents keep its own tier.
- Home says any missing data file is created from its template; only the
  three config files are.

**Principles kept from the design**, for every stage:

1. Models never do arithmetic. Every figure a stage states comes from a
   deterministic tool's output; a figure not in that output is not stated.
2. Fetched text is untrusted. Collectors flatten it to fixed schemas and
   ignore instructions inside it; nothing that reads `raw/` has a shell.
3. Confidence is stated before the outcome and scored after it by a tool,
   never self-reported. `scores/predictions.jsonl` is an append-only ledger.
4. Every output ends at a person: a decision is a recommendation, nothing
   executes, and no broker is connected (positions are a CSV the person keeps).
5. One- and three-day calls from news are close to a coin flip; a clearly
   measured negative result is a successful output.

**Built-in tools.** Each is medium risk (it fetches or writes), so a policy may
answer it; each writes through `Sandbox.resolve_write_path`; none has a shell.

- `read_prices` (network): for up to 50 watchlist symbols, fetch a year of
  daily history from one fixed endpoint, recommended
  `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d`,
  keyless, which answered for `AAPL` and `2330.TW` (251 sessions, about 28 KB).
  Use `http_get`'s public-address check, pinned address, TLS name and
  no-redirect rule, with at most 1 MB read per symbol, and put the endpoint's
  host in `Prepared.payload["host"]`. It writes:
  - `raw/prices/{SYMBOL}.csv` (`date,open,high,low,close,volume`,
    exchange-local dates, oldest first);
  - `raw/movers-{session date}.json` in the roster prompt's schema, plus
    `change_pct`, `rel_volume`, `microcap` and a rank among the watchlist
    (1c's gainers and losers among the tickers followed);
  - `raw/prices/summary.csv`, the latest session per symbol, for charts.
  It returns that summary, any failure per symbol, and whether the session is
  newer than the last movers file.
- `compute_portfolio` (local): reads `portfolio/positions.csv` and the price
  files; writes `portfolio/computed.json` and `portfolio/weights.csv`.
- `check_limits` (local): reads `computed.json`, `config/limits.json` and the
  day's theses; writes `risk/rule-checks-{date}.json`, the file the risk
  manager's prompt already names.
- `score_predictions` (local): reads every `theses/bull-*.jsonl` and
  `theses/bear-*.jsonl` and the price files. It appends each newly resolved
  prediction once to `scores/predictions.jsonl`, and writes
  `scores/scorecard-{YYYY-MM}.json`, `scores/accuracy.csv` and
  `scores/calibration.csv`.

**File contracts.** The prompts' paths are kept. Arithmetic is `Decimal` and
is rounded only when written.

- `portfolio/positions.csv`:
  - Required columns: `ticker,shares,cost_per_share,opened,sector,currency`;
    `currency` is an uppercase ISO 4217 code such as `USD`.
  - Cash: a `CASH` row holds it, in `shares`.
  - Currency: one per book; a mix is refused, and the refusal names the
    currencies.
  - Template: the header and a `CASH` row denominated in `USD`, never an
    invented holding. A missing or invalid `currency` value is refused with
    actionable validation rather than silently defaulted.
- `portfolio/computed.json`:
  - Freshness: `as_of`; the positions file's date, with `stale` after 3
    days; each ticker's price date; `currency`.
  - Book totals: `total_value`, `cash`, `invested`, `day_change` and
    `day_change_pct` (from the previous close), `unrealised` and
    `unrealised_pct`.
  - Positions: `weight_pct`, `cost_per_share`, `close`, `value`,
    `unrealised_pct`, `days_held`, `sector`.
  - Concentration: `largest_weight_pct`, `top3_weight_pct`, sector weights,
    and `limit_crossings` against `config/limits.json`.
  - Realised and period P&L are `null`, with the reason: a snapshot cannot
    give them.
- `risk/rule-checks-{date}.json`: for each held position and each thesis
  ticker, `max_position_pct`, `max_sector_pct` and `max_daily_loss_pct` as
  `PASS` or `FAIL` with value and threshold, and the headroom a new position
  has under each.
- `scores/predictions.jsonl`: one line per resolved prediction, never
  rewritten. Each line holds:
  - the thesis fields;
  - `entry_date` and `entry_close`: the last session on or before the
    prediction's UTC date;
  - `exit_date` and `exit_close`: `horizon_days` sessions later, so weekends
    and holidays do not count;
  - `return_pct`; `hit` (an unchanged close is a miss); `band_hit`;
  - `brier`: (confidence minus hit) squared; `scored_at`.
  A malformed thesis line is counted and reported, never guessed.
- Scorecard and chart files:
  - Hit rate and mean Brier by agent and horizon, against a constant 0.5
    (Brier 0.25) and against the share of windows that rose.
  - Calibration buckets from 0.50 in steps of 0.10, stated against observed.
  - The count still unresolved.

**Migration 021** gives the roster its tools and updates the schedules and
starters. It is guarded like 015: an edited prompt, allowlist or goal stays
byte for byte. (Migration 020 is the models unit below.)

- **Tools on the roster.** `market-movers` gets `read_prices`,
  `portfolio-review` gets `compute_portfolio`, `risk-manager` gets
  `check_limits` and `review-analyst` gets `score_predictions`. Each untouched
  prompt calls its tool first, states only its output, and reports and stops
  when an input is missing. `market-movers` stops fetching prices through
  `http_get`.
- **The 019 goals, where untouched.**
  - The morning collection stops, and says so, when `read_prices` reports no
    new session (a holiday).
  - The theses stage writes nothing without that session's movers file.
  - The weekly knowledge stage writes concept notes from the space's own
    knowledge, and company notes only where `raw/filings/{TICKER}/` holds
    filing text a person put there.
- **Starter files.** **Turn on the daily pipeline** also creates, where
  missing:
  - `portfolio/positions.csv`;
  - a `config/sources.json` naming the price endpoint and the Treasury's
    keyless auctions API (`api.fiscaldata.treasury.gov`, which answered on
    2026-09-30), not Stooq;
  - the dashboard below.
- **Home's copy** says what it creates, what the person supplies (the
  watchlist and positions) and what the pipeline does not cover.

**Hosts.** A fresh install lists `news.google.com`, the price endpoint's host
and `api.fiscaldata.treasury.gov`; Stooq leaves the list. 021 writes the old
list into used databases that never saved one ("A default setting" in the
developer guide's checklists).

**Trap:** 018 counts any schedule row as use, but 019 seeds five into every
database, so every install created since would count as used. Count only
runs, saved settings, spaces other than the default, and schedules other than
019's five.

**Models (migration 020, built first).** This unit is independent of the
pipeline tools.

- **Claude Sonnet 5.5 joins the catalog.**
  - The facts: released 2026-09-28 as `claude-sonnet-5-5`, at $2 in and $10
    out per million tokens, the same as Sonnet 5. It has a 1M-token context,
    128K output, and retirement not before 2027-09-28. Checked against
    platform.claude.com on 2026-09-30.
  - Add its price row in `providers/pricing.py`.
  - In `providers/catalog.py`, make it Anthropic's current balanced model.
    `claude-sonnet-5` moves to the older models; it stays sold and
    selectable, active until at least 2027-06-30.
  - A switch from OpenAI then lands on Sonnet 5.5.
  - No provider change is needed. The app sends no sampling parameters, which
    Claude 4.7 and later refuse, and no thinking settings. `modelLabel`
    already reads "Claude Sonnet 5.5".
- **The shipped Sonnet agents move.** 020 moves `research-librarian`,
  `bull-architect`, `bear-architect`, `risk-manager` and `review-analyst`
  from Sonnet 5 to Sonnet 5.5, but only while never edited
  (`updated_at = created_at`, as 016 did for Opus). It leaves `updated_at`
  alone, so the guards of later migrations still read them as never edited.
- **Where spaces start.** The maintainer's answer (2026-09-30): "the best
  model for overall result and efficiency".
  - Where tokens are billed, that means the balanced level: Claude Sonnet
    5.5, or GPT-6 Sol.
  - On a ChatGPT plan it means the plan's strong model, GPT-5.6 Sol. Plan
    calls are not billed per token, and OpenAI describes GPT-5.6 Terra as for
    straightforward work.
  - This replaces `DEFAULT_TIER`'s single strong level for new spaces
    (`api/settings.py` `_new_space_model`, `api/spaces.py` `_with_model`).
    Decide separately where a model with no tier maps, which `DEFAULT_TIER`
    also governs today.
  - `DEFAULT_MODEL` and `DEFAULT_MODELS` (`store/settings.py`) follow, and a
    test holds them to the catalog. Used databases get the old value pinned
    ("A default setting").
  - 020 moves the default space from Opus 5.5 to Sonnet 5.5 only on an unused
    database, with the corrected check under **Hosts**. Existing spaces keep
    their models.
- **The shipped roster keeps its intended level**, keyed by the agents'
  fixed IDs:

  | Agents | Level |
  |---|---|
  | The collectors, `portfolio-review` | fast |
  | The analysts, `risk-manager`, `review-analyst` | balanced |
  | `decision` | strong |

  GPT-6 Sol is the one model that stands in for two levels. Where a shipped
  agent is on it, the provider-switch preview and the plan repair map that
  agent by its intended level. Any model a person chose maps by its own
  level, as it does today.
- **`decision` stays on Opus 5.5.** Whether Sonnet 5.5 is close enough for the
  one daily arbitration is a later, measured question.
- **Watch Claude Haiku 4.5.** The fast shipped agents use it. It is active and
  no deprecation has been announced: retirement is not before 2026-10-15,
  with at least 60 days' notice, and no newer Haiku exists. Watch the
  deprecations page; nothing moves until one is announced.

**Visualize.** The starters add `visualizations/pipeline.dashboard.json` and
four charts over the stable files the tools write, so no chart names a dated
source and Phase 14's contract is unchanged:

- the day's `change_pct` by ticker, from `raw/prices/summary.csv`;
- portfolio weights, from `portfolio/weights.csv`;
- hit rate by horizon and agent, from `scores/accuracy.csv`;
- calibration, from `scores/calibration.csv`.

**Out of scope:**

- Reddit and other social sources: OAuth, and their terms.
- SEC filings: they need an identifying header.
- Keyed data APIs. These wait for a keychain-held data-source key that the
  tool adds at execute time, outside the model's context and the log.
- Market-wide screeners and earnings dates: no keyless source was verified.
- FOMC and BLS calendars. A person may keep such dates in a
  `config/calendar.json` that the calendar agent reads.
- A Taiwan chain, and per-schedule time zones: schedules keep local
  wall-clock time (Phase 13).
- A market-holiday calendar beyond the new-session check.

**Decisions to confirm with the maintainer before coding:**

*Maintainer choices, 2026-09-30: all six decisions below are accepted. Use
Yahoo's keyless, unofficial chart endpoint; give fresh installs the three-host
list while preserving saved lists on used installs; ship `read_prices`,
`compute_portfolio`, `check_limits` and `score_predictions` as medium-risk
tools; preserve `decision` at the strong level across GPT-6 Sol; keep stable
chart files and the Phase 14 visualization contract; and run weekly knowledge
without filings as described above. Where spaces start remains Claude Sonnet
5.5, GPT-6 Sol, or GPT-5.6 Sol on a ChatGPT plan. An untiered model maps to
the target provider's space default rather than to one shared tier.*

*Additional maintainer choice, 2026-09-30: `portfolio/positions.csv` requires
the `currency` column described in the file contract. The starter uses `USD`,
and missing or invalid values fail with actionable validation; the tool never
assumes a currency.*

*Additional maintainer choice, 2026-09-30: every entry in
`config/watchlist.json` requires a non-empty `sector`. `check_limits` fails
with actionable validation when a thesis ticker has no configured sector. An
unheld thesis ticker has a current position weight of 0%; the tool reports its
remaining position headroom and the remaining headroom in its configured
sector.*

1. **Price source.** Yahoo's chart endpoint is keyless and unofficial, and it
   can change or refuse. The alternative is waiting for keyed sources.
2. **Hosts.** The fresh-install host list above.
3. **Tools.** The four tools' names, and medium risk for all four.
4. **Models.** The shipped-level rule for `decision`. (Where spaces start was
   answered on 2026-09-30, above.)
5. **Charts.** Stable chart files, rather than a dated-source pattern in
   Phase 14's contract.
6. **Weekly knowledge.** The weekly knowledge stage without filings.

**Order:**

1. Settle the six decisions.
2. Build the models unit and migration 020, test-first:
   - Sonnet 5.5's price and catalog place;
   - the starting model per provider, with its settings pin;
   - the shipped Sonnet agents moving, and the default space moving on an
     unused database;
   - the shipped-level rule in `providers/catalog.py` and `api/spaces.py`.
   The upgrade tests cover four databases: fresh, used, created since 019
   but unused, and with edited rows.
3. Build `read_prices` test-first, against recorded responses; no test may
   use the network. Then add its sentence in `state/describe.ts`, its label
   in `RunGraph.tsx`, and its place in the fetch detection in `describe.ts`
   and `Schedules.tsx`.
4. Build `compute_portfolio`, then `check_limits`, then `score_predictions`,
   each test-first.
5. Write migration 021, with upgrade tests for the same four databases.
6. Add the starters, dashboard and Home copy in `lib/pipeline.ts` and
   `PipelineOffer.tsx`, then check them in a browser.
7. Update the user guide (`1_getting_started.md` for models, `3_agents.md`,
   `7_visualizations.md`), `CLAUDE.md` and `docs/verification.md`.
8. The maintainer runs the chain live on a real model.

Follow the developer guide's "A tool", "A migration" and "A default setting"
checklists, and commit each unit.

**Accept when:**

1. On a fresh data directory, with the pipeline on and a watchlist and
   positions filled in, **Run now** on the morning collection runs the chain
   unattended to `decisions/{date}.md`, writing the movers, price, portfolio
   and rule-check files. Every figure in them traces to a `tool.result`, none
   to a model's text.
2. Given recorded prices, `score_predictions` appends each resolvable
   prediction exactly once, a second run adds nothing, and its scorecard,
   accuracy and calibration files match values computed by hand.
3. The pipeline dashboard opens in Visualize with its four charts.
4. A fresh install fetches prices and Treasury data by policy, a used install
   keeps its old host list, and an install created after 019 but never used
   gets the new list.
5. An edited roster agent and an edited goal are unchanged by 020 and 021.
6. Moving the default space from Anthropic to OpenAI, then onto a ChatGPT plan
   without GPT-6 Sol, leaves `decision` on GPT-5.6 Sol.
7. Claude Sonnet 5.5 is priced and offered as Anthropic's balanced model.
   After 020:
   - a never-edited shipped Sonnet 5 agent is on Sonnet 5.5, and an edited
     one is not;
   - a fresh install's default space, and a new Anthropic space, start on
     Sonnet 5.5;
   - a new OpenAI space starts on GPT-6 Sol, and on a ChatGPT plan on
     GPT-5.6 Sol;
   - a used install's spaces keep their models.
8. The event contract, gate, sandbox, cost ceiling and replay are unchanged.
   Each new tool is medium risk and passes the gate, and a supervised run asks
   before each call.

---

## 6. How you should work

- **One phase per session.** At the end of each phase, stop. Report what you built, what
  you actually ran, and what you did not verify.
- **Do not claim something works unless you executed it.** "Should work" and "works" are
  different words. If you did not run it, say you did not run it.
- **Write the test before the feature** for anything in the event store, budget ledger, or
  sandbox. These three are where silent bugs become expensive.
- **Negative results are useful.** If an approach fails, report the failure and why rather
  than quietly substituting a different approach.
- **Ask before deviating.** If a constraint in §1 blocks you, stop and explain the conflict.
  Do not route around it.
- Keep `CLAUDE.md` updated with the current phase and any decisions made mid-build.
- Commit per logical unit with a real message. No `wip`, no `fixes`.

---

## 7. Explicit non-goals for v1

Do not build these. Do not scaffold placeholders for these.

- Multi-user accounts, remote application auth, or tenancy. Local model-provider
  sign-in for the single user is allowed as described in the Phase 3 addition.
- Any network-exposed surface beyond `127.0.0.1`
- Cloud-hosted knowledge databases or separate embedding services
- Executing Obsidian community plugins inside AgentBase
- Agent marketplaces or plugin systems
- Intel macOS release artifacts (Apple Silicon `.app.zip` added for 0.2.0 on 2026-09-13,
  replaced by a `.dmg` on 2026-09-18; see constraint #7 and the Phase 9 deviation)
- Developer ID code signing or notarization
- Auto-update
- Mobile
- Headless / server mode (a future option, not now)
- Local model support as a *requirement*: the abstraction exists, the implementation is
  optional and untested in v1

---

## 8. Start here

Confirm you have read this document. State which phase you are starting and what you plan
to do in it. Then begin Phase 0.
