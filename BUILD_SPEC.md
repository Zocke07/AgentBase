# BUILD_SPEC.md: Autonomous Agent Co-Working Space

You are building this project from scratch in an empty repository. Read this entire
document before writing any code. Re-read it at the start of every session.

---

## 0. What we are building

A **local-first desktop application** where multiple AI agents collaborate on tasks, and
the user watches them work in real time on a live graph. Optionally reachable from Discord.
*(Telegram was a second channel until 2026-09-11; see the note under Phase 8.)*

It ships as a single installer. The end user is not a developer.

### Primary success criterion

A user double-clicks an app icon, types a task, and watches agents spawn, call tools, hand
off to each other, and finish, with every step visible as it happens. No terminal, no
Docker, no config files.

---

## 1. Hard constraints: do not violate these

These are decisions already made after long deliberation. Do not "improve" them, do not
substitute equivalents, do not add the thing they replaced. If you believe one is wrong,
**stop and say so before implementing anything different.**

| # | Constraint | Why |
|---|---|---|
| 1 | **No agent framework.** No LangChain, LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, OpenClaw. Write the orchestration loop by hand. | The visualization only works if we own the event stream. Frameworks emit their own event shapes and we would have to adapt them anyway. |
| 2 | **No Docker, no Postgres, no Redis, no LiteLLM proxy in the shipped product** (the Tauri app and the headless instance). | Single user, single machine. These systems solve multi-user fleet problems this application does not have. |
| 3 | **Everything binds `127.0.0.1` only.** Hardcode it. Do not make the bind address configurable. | Nothing reachable off-machine means nothing to accidentally expose. |
| 4 | **Model credentials go in the OS keychain.** API keys and OAuth tokens never go in `.env`, SQLite, config files, logs or argv. | The credentials sit on a personal laptop. |
| 5 | **Every filesystem/shell/network tool call passes an approval gate** before execution. No exceptions, no privileged paths for any channel. | This is the exact failure mode that produced dozens of CVEs in comparable projects. |
| 6 | **Chat channels trigger on explicit commands/mentions only.** Never ingest ambient channel messages into agent context. | Indirect prompt injection. A slash command has a schema; a channel firehose does not. |
| 7 | **Windows is the primary target.** macOS builds in CI and ships an ad-hoc signed, unnotarized Apple Silicon app archive. | Windows-first; macOS release added at the maintainer's request on 2026-09-13. |
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

**Only model inference leaves the machine.** Orchestration, tool execution, and state are
all local.

### The one idea everything hangs off

**Every agent action is an append-only event.** The UI is a pure projection of the event
log. Live view and replay use the same code path. Reconnect resumes from a sequence number.

If you find yourself sending an ad-hoc websocket message that is not an event row, you
have made a mistake. Fix it rather than working around it.

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
│   │   ├── src/agentspace/
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
│   │   │   │   └── builtin/      # read_file, write_file, http_get, shell
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

Adding an event type means updating: `events/types.py`, the generated TS types, and the
`RunGraph` reducer. Do all three in the same commit.

---

## 5. Build phases

Work through these **in order**. Do not start a phase before the previous phase's
acceptance criteria pass. Do not build ahead. Later additions retain their original
phase numbers so historical references remain valid.

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

Before writing any real feature code, prove the hardest packaging problem works:

- A trivial FastAPI app returning `{"ok": true}`, compiled with `pyinstaller --onefile`.
- Tauri v2 `externalBin` pointing at it, a React page that fetches from it and renders the result.
- Build an actual installer on Windows (NSIS via `tauri build`) and launch it from a normal
  per-user install location.

Known traps to handle here, not later:
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

**Accept when:** a built installer on a machine with no Python installed runs, serves, and
leaves zero orphan processes in Task Manager after the app is closed.

### Phase 2: Event spine

The core. Get this right and everything else is straightforward.

- SQLite schema + migrations, DB file in the OS app-data dir (via Tauri's path API).
- `EventStore.append()`: assigns `seq` atomically per run.
- `EventBus`: in-process `asyncio` fan-out to subscribers.
- `GET /runs/{id}/events` as SSE, honouring `Last-Event-ID` to replay from a sequence number.
- A `fake_run` debug endpoint that emits a scripted sequence of ~20 events over 10 seconds.

**Accept when:** the debug run streams to a `curl` client, and killing/reconnecting mid-stream
resumes with zero gaps and zero duplicates.

### Phase 3: Providers, budget, keychain

- `Provider` protocol: `complete(messages, tools) -> Response` with normalized token usage.
- Implement Anthropic and OpenAI. Add an Ollama implementation behind the same protocol
  (local model support is optional at runtime but the abstraction must not assume cloud).
- `pricing.py`: per-model input/output cost. All money as **integer micros**, never floats.
- `budget/ledger.py`: monthly cap. Check *before* each call, record *after*. Emit
  `budget.warning` at 80%, `budget.exceeded` and refuse at 100%.
- Keys read from OS keychain via `tauri-plugin-keyring`, passed to the sidecar at spawn
  time over stdin, never as a command-line argument (argv is world-readable via `ps`).

**Approved addition, 2026-09-14:** OpenAI has an app-wide access mode,
`api_key` or `chatgpt`. Both construct a provider named `openai` and use the
same selected model id, normalized response contract, AgentSpace orchestrator,
tool catalogue, approval gate, event log, usage ledger and run limits. ChatGPT
access uses the pinned Codex App Server as a credential and inference transport
only. It receives one structured model decision per provider call, runs in an
empty read-only directory with its own tools disabled, and never owns the agent
loop or executes an AgentSpace tool. OAuth tokens stay in the OS credential
store and are not returned by the local API. AgentSpace applies the selected
model's API-equivalent price to subscription token usage so the existing local
safety cap behaves the same; this estimate is not an OpenAI API charge.

ChatGPT and API accounts can have different model entitlements and usage
allowances. AgentSpace preserves the requested model and surfaces an access
error rather than silently substituting another model. Direct Claude
subscription login is not included because Anthropic's current
[authentication terms](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use)
do not permit a third-party product to offer Claude.ai login or route Free,
Pro or Max credentials. Anthropic continues to use an API key. The documented
exception for embedding the unmodified Claude Code binary is a separate
product mode, not an interchangeable provider credential transport.

**Accept when:** switching provider is a settings change with no code change, and a run
that would exceed the monthly cap is refused with a clear reason before any API call fires.

### Phase 4: Orchestrator

- `Run` owns lifecycle and the event sequence.
- `Supervisor`: given a goal, decomposes into subtasks and spawns worker agents.
- `Agent`: the worker loop (think, call tool, observe, repeat) until done or budget/step limit.
- Agents communicate via `agent.message` events, never direct function calls. Handoffs are
  `agent.handoff` events.
- Hard limits: max steps per agent, max agents per run, max wall-clock per run. All configurable,
  all enforced, all emit a terminal event when hit.

**Accept when:** a two-worker run completes end to end, and the full event log alone is
sufficient to reconstruct exactly what happened without reading any other state.

### Phase 5: Agent registry (user-defined agents)

Agents stop being hardcoded Python classes and become editable data.

- `agent_defs` table (see §4) plus CRUD endpoints in `api/agents.py`.
- `registry.py` loads definitions from the DB at run start. It no longer imports agent
  classes; it constructs workers from rows.
- Seed 3–4 built-in definitions on first launch (e.g. `researcher`, `writer`, `reviewer`)
  so a fresh install is usable immediately. Built-ins are editable but not deletable -
  `is_builtin = 1` guards the delete path only.
- `allowed_tools` is an **allowlist, never a denylist.** An agent can only call tools named
  in its own row. An empty array means the agent can reason and hand off but touches nothing.
- A definition edited mid-run does not affect the in-flight run. Runs snapshot the
  definitions they started with; changing an agent is not a way to mutate a running agent.
- Validation on write: name uniqueness, non-empty system prompt, every entry in
  `allowed_tools` must resolve to a registered tool, `max_steps` within the global cap.
  Reject at the API layer with a readable message, not a 500.

**Security note: read this before implementing.** User-authored prompts do **not** widen
the security model, and must not be allowed to. The approval gate (next phase) lives at the
*tool execution* layer. A sloppy, over-permissive, or actively adversarial system prompt
still cannot reach the filesystem or shell without passing the same gate as everything else.
`auto_approve` on an agent definition may only *narrow* what the global policy already
permits; it can never grant a risk level the workspace policy has not enabled. If you find
yourself writing code where an agent definition escalates its own privileges, stop.

**Accept when:** an agent created entirely through the API (never touching Python) can be
spawned into a run, and an agent whose `allowed_tools` omits `write_file` is blocked from
calling it even when its system prompt explicitly instructs it to.

### Phase 6: Tools and the approval gate

- `Tool` protocol with a declared `risk` level.
- Built-ins: `read_file`, `write_file`, `list_dir`, `http_get`, `run_shell`.
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
  runs can progress. Default is manual-approve-everything.

**Accept when:** an agent instructed to write outside the workspace root is blocked at the
sandbox layer, and this is visible in the event log as `tool.denied`.

**Addendum: container-sandboxed `run_shell` (your instance only, not part of the shared
build).** The app-level sandbox above is a real but limited boundary: a successfully
prompt-injected or misbehaving shell command still runs as your actual user account. On your
own always-on instance, wrap `run_shell` specifically in a short-lived container: network
disabled, read-only mount except the workspace root, CPU/memory capped, killed on timeout.
This is the one place Docker earns its way into this project on genuine merit rather than as
a resume line: it's real OS-level isolation for the one tool that can do the most damage, not
containerization for its own sake. Keep it scoped to this single tool call; do not
containerize the rest of the app to justify it.

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

**Accept when:** replaying a completed run produces pixel-identical UI state to what was
shown live, and a new agent can be created, edited, and run without leaving the app.

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

**Accept when:** the same run is observable simultaneously from the dashboard and the
originating chat channel, and a channel-originated tool call still hits the approval gate.

### Phase 9: CI and release

- **Test job runs before the build job and gates it.** `pytest` on the backend (event store,
  budget ledger, sandbox, agent registry validation at minimum), `vitest` on the frontend
  reducers (`RunGraph`, `EventLog`). A red test blocks the build job entirely: CI that only
  builds and never tests is not CI, it's a compiler check with extra steps.
- GitHub Actions matrix: `windows-latest` and `macos-latest`. Build the PyInstaller sidecar
  on each (it does not cross-compile), then the Tauri bundle.
- Publish the Windows installer and, from 0.2.0, the macOS Apple Silicon app archive.
  **2026-09-13 deviation from the original build-only macOS scope**, requested in the
  maintainer's release handoff: constraint 7 and §7 now permit this archive. macOS remains
  without a trusted Developer ID signature and unnotarized; Developer ID signing,
  notarization and an Intel release are deferred.
  Zip the `.app` with `ditto --keepParent` before upload, because artifact upload strips
  executable modes from raw files. Verify the extracted archive's bundle version, shell
  and sidecar hashes, executable modes, database startup and shutdown before publishing.
- **Keep the repo public.** Private-repo Actions minutes drain at a 2x multiplier on Windows
  runners and 10x on macOS: the macOS build job is the expensive one to watch.
- Keep the Windows installer unsigned for now. Windows does not hard-block an unsigned app: the
  installer triggers a SmartScreen "Windows protected your PC" prompt, and the user clicks
  "More info" → "Run anyway" once. No terminal command, no equivalent of `xattr` needed.
  Document this one click in the `README` so it doesn't read as broken. An EV code-signing
  cert, optional and not required to ship, removes the warning entirely if it's ever worth the
  cost.
- Document macOS Gatekeeper's **Privacy & Security > Open Anyway** path and the scoped
  `xattr -dr com.apple.quarantine /Applications/AgentSpace.app` fallback, plus the keychain
  access prompt after an app update. The first 0.2.0 archive omitted a complete app-bundle
  signature and Gatekeeper reported it as damaged. The corrected 0.2.0 release uses Tauri's
  ad-hoc identity and a strict signature check. Hardened runtime stays disabled because
  re-signing the PyInstaller one-file sidecar with it enabled prevents the extracted Python
  library from loading. Revisit the runtime and entitlements with Developer ID signing and
  notarization instead of adding permissions this release does not use.

**Accept when:** a green CI run produces a downloadable installer that runs on a second
Windows machine with no Python installed.

### Phase 11: Spaces, and the redesign around them

*Added 2026-09-11 at the maintainer's request. Design first: this section is reviewed by the
maintainer before any of it is coded (§6, "ask before deviating," and this changes §4).*

*Built 2026-09-12. The maintainer asked for the redesign first, so the order of work below
ran (4)–(7) against the single workspace and then (1)–(3), (6) and (8): the redesign was
laid out so the switcher and the space settings page dropped in. Where the build settled a
question the design left open, or found the design wrong, the note is inline below,
dated.*

**The idea, in the maintainer's words:** instead of creating standalone agents, let the user
define a *coworking space* first, and assign agents to live in that space. A run happens in
a space, with that space's agents, that space's rules, in that space's folder.

**What a space is.** A named container that owns three things: a **roster** (agent
definitions belong to exactly one space), a **folder** (the sandbox root for every tool call
in its runs), and **rules** (model, approval policy, run limits, each either inherited from
the app-wide default or set here). Runs belong to the space they were started in. Everything
that is the *user's* rather than a space's stays app-wide: API keys and bot tokens (the
keychain is process-wide by construction, §1 constraint 4), the monthly budget cap (one
wallet), the Discord connection and its allowlist.

**What a space is not.** Not a tenant, not an account, not a project directory the user
points at their home folder. §7's non-goals stand. The blast radius of an approval misclick
is the space's folder, and in v1 that folder is always one this application created.
*(2026-09-12: settled as written, with no user-picked folder. The space settings page shows the
path and opens it; it cannot change it.)*

#### Data model (§4 additions)

```sql
CREATE TABLE spaces (
  id            TEXT PRIMARY KEY,        -- uuid4; the default space's is a fixed literal
  name          TEXT NOT NULL UNIQUE,
  description   TEXT NOT NULL DEFAULT '',
  provider      TEXT,                    -- NULL = inherit the app-wide default
  model         TEXT,                    -- NULL = inherit
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

The folder is **not a column**: it is `<data dir>/spaces/<id>/`, derived, so a row cannot
name a path outside the place the application owns. Renaming a space does not move files.

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

#### Rules resolve in layers, and the approval layer only narrows

`effective = definition ∩ space ∩ app-wide` for `auto_approve`, extending §5 Phase 5's rule:
a definition "can never grant a risk level the workspace policy has not enabled", and now
neither can a space. The Phase 6 reading holds at each layer: an empty/NULL list means
*inherit*, not *none*. *(2026-09-12: for a **space**, NULL means inherit and the empty list
means "ask for everything". The column is nullable precisely so the two can differ, and a
space stricter than the app-wide policy (a sensitive one that asks about every read)
is a legitimate thing a nullable column can express and a NOT NULL `'[]'` cannot. A
definition's column is NOT NULL `'[]'`, so the Phase 6 reading stands there.)* Model and limits are overrides, not narrowings: a space wanting longer
runs than the default is a legitimate thing, and the wall clock is a cost control that the
app-wide budget cap still bounds. `run.started` records the effective rules and the space
(`space: {id, name}`) so a replay can say which rules a run ran under. **No new event
types**: the §4 list is unchanged, so no three-way update is needed.

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

This is the visual redesign the maintainer asked for, shaped around spaces so it is done
once. It replaces the developer dashboard's chrome; it does **not** replace the run
projection's structure: the graph, the log and the summary stay one pure fold of the log,
inside the same `run-projection` boundary, and `replayIdentity.test.tsx` keeps passing at
every step.

- **A sidebar, not tabs.** A persistent left rail: the **space switcher** at the top (current
  space's name, a list to switch, "New space…"), then the current space's sections
  (*Home*, *Runs*, *Agents*, *Space settings*), and, pinned to the bottom, the app-wide *Settings*
  (keys, budget, Discord). The header keeps what is global: the budget meter with the
  month's spend, the provider · model in use for *this space*, and the "N approvals waiting"
  badge, which is global and opens the run it names in whatever space it is in.
- **A Home screen per space.** What a person sees when nothing is open: a large goal box
  ("What should this space work on?") with a Start button; a **Now** strip: runs in progress
  and approvals waiting, each a card that opens the run; **Recent runs** as cards (status,
  goal, started, duration, cost) rather than a dense list; and the **roster**: the space's
  agents with role and an enable toggle, with "Add an agent" and, for an empty space, "Start
  from the built-in roles". First-launch guidance lives here too: no key configured → one
  card saying so with a button to Settings and a button for the demo run; no agents → the
  seed button; no runs → the goal box is the whole screen.
- **Plain language first, raw types second.** Every event row gets a sentence: *supervisor
  asked the model*, *writer wants to write hello.txt (waiting for you)*, *writer wrote
  hello.txt (24 bytes)*, with the raw `llm.request` / `tool.called` kept as a muted mono
  chip beside it, because the raw type is what a bug report needs and the sentence is what a
  person reads. Same for the agent card labels and the run status. The sentences are a pure
  function of the event, so they live in the reducer's module and are covered by the
  identity test.
- **A "Now" line above the graph.** One sentence about the run at this cursor: *writer is
  waiting for your approval*, *3 agents finished; the supervisor is writing the summary*,
  derived from the fold, so it is identical live and on replay.
- **Type and colour.** A system UI stack for prose (Segoe UI on Windows, SF on macOS);
  monospace only for ids, payloads and code. Base size 14 → 15px, 1.5 line height; the
  uppercase micro-labels go. **Light theme and dark theme**, following the OS
  (`prefers-color-scheme`) with an override in Settings; both defined as tokens on `:root`
  so no colour has a single definition. A softer palette: one accent, the three risk colours
  (unchanged in meaning; they match the gate), status colours for the five run states,
  and neutral surfaces with one level of elevation for cards. Nothing on screen is coloured
  for decoration.
- **Cards for runs, rows for events.** A run is something to pick; an event is something to
  scan. The event log keeps its table shape (it is the thing you check the graph against)
  and gains the sentence column; the picker becomes cards.
- **The approval panel stays docked** (CLAUDE.md, 2026-09-11) and gets the same restyle:
  risk-coloured edge, the question in a sentence, the decision history collapsed by default,
  Deny still focused.
- **Space settings are one page; app settings are another.** *Space settings*: name,
  description, the folder (shown as a path, with **Open folder** via the Tauri opener plugin
  - a new, single-purpose dependency, replacing nothing), model, approval policy, limits,
  each with "Inherit" as the first choice, and a danger zone (archive; delete when
  allowed). *Settings*: what the current tab holds minus what moved to spaces, plus theme
  and `channel_space_id`. *(2026-09-12: nothing "moved": model, limits and the approval
  policy stay on the app page as the defaults every space inherits, since Inherit has to
  inherit from somewhere the user can see. The opener plugin is used from Rust only, behind
  one command that refuses any path outside the data directory; none of its JavaScript
  commands are granted to the webview.)*
- **Windowed event log.** Long runs render only the rows in view. Deferred from the frontend
  pass as "nothing larger than 291 events has been measured"; the redesign touches every row
  anyway, and the Home screen's cards mean the log is no longer the first thing loaded.

**Order of work, so the gate stays green throughout:** (1) migration 006 and the `spaces`
store, test first; (2) `space_id` through the launcher, the sandbox-per-run and the roster
snapshot, verified with two spaces against a real model; (3) the API and regenerated types;
(4) the sidebar, switcher and Home screen against the existing panels; (5) the run view
restyle: sentences, the Now line, theme tokens; (6) space and app settings pages; (7) the
log windowing; (8) Discord's `channel_space_id`. Each step is its own commit or small group,
and CLAUDE.md records what the live runs showed.

**Accept when:**

1. Two spaces with different rosters; a run started in space A, against a real local model,
   with a goal that names one of space B's agents by name, never spawns it: the supervisor's
   roster in `agent.spawned` lists only A's agents, and the log shows the refusal.
2. A `write_file` in a run in space A lands under A's folder; a `write_file` from the same
   run to a path under B's folder is `tool.denied` with `blocked_by: "sandbox"`.
3. A populated v5 database opens as v6 with every run, event, definition, approval and spend
   row intact and every run and definition in the default space, and the old workspace
   folder's files are in the default space's folder.
4. From a fresh data directory, entirely in the window: create a space, seed its roster,
   set a key, start a run, answer its approval, replay it. Replay is pixel-identical to
   live in both themes.
5. `GET /budget` still refuses a run over the app-wide cap regardless of which space it is
   in, and each space reports its own spend.
6. Every acceptance criterion from Phases 6, 7 and 8 still holds, run again, in the new UI.

### Phase 12: Markdown knowledge vault and retrieval-augmented memory

*Added 2026-09-15 at the maintainer's request. This explicitly replaces the v1
non-goal that excluded vector memory and RAG.*

Each space's existing folder is also an Obsidian-compatible vault. Markdown is
the canonical data, whether a note is edited in AgentSpace, Obsidian or another
text editor. AgentSpace must not create a proprietary second copy of note
content or require Obsidian to be installed.

- Add a **Knowledge** section per space with a note browser, Markdown source
  editor, safe preview, YAML properties and tags, wikilinks, backlinks, local
  search and a linked-note graph.
- Add **Open in Obsidian** through a narrow Rust command. It accepts only an
  existing directory under AgentSpace's data root, constructs the documented
  `obsidian://open?path=` URI itself, and does not grant a general URL opener to
  the webview.
- Rebuild the index from the live folder when it is used. An edit made outside
  AgentSpace is visible on the next list, search or run without a watcher,
  reindex job or stale database.
- Retrieval stays local and combines deterministic hashed term vectors with
  term overlap, title and tag relevance. Return heading-sized chunks with
  stable `[[path#heading]]` citations. Do not send notes to a separate embedding
  service.
- Retrieve context for the run goal and again for each worker handoff. Mark
  excerpts as untrusted reference data, never instructions. The exact excerpts
  sent to the supervisor are recorded in `run.started`; worker excerpts remain
  visible in that worker's `llm.request` message.
- A successful run writes its goal and outcome to the unique app-owned path
  `memory/runs/<run-id>.md` before `run.completed`. That terminal event records
  `memory_path`, so later runs can retrieve the memory and a replay can locate it.
- Add the low-risk, approval-gated `search_knowledge` tool for agents that need
  to refine retrieval while working. Existing user-edited allowlists remain
  unchanged; seeded roles receive it through migration 007 only while their
  allowlist still matches a shipped default.
- Hidden paths, especially `.obsidian`, never appear in the index and cannot be
  edited through the Knowledge API. Note paths remain inside the per-run space
  sandbox and must end in `.md`.

**Accept when:**

1. A Markdown file edited outside AgentSpace appears with its YAML properties,
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

**0.3.0 additions, agreed 2026-09-17.** The memory inbox: a run memory or an
agent's `propose_memory` note (medium risk, approval-gated, migration 008 for
unedited seeded roles) starts as `proposed` and is retrieved only once the user
approves or pins it; the inbox also archives, merges (originals archived and
backed up) and forgets memories, and shows the source run, creation date,
confidence and supporting citations. Ranking adds BM25 to the hashed vector,
filters by folder, tag, note type, date, pinned state and memory status, caps
each note at two chunks, and ignores English function words. Each note's
chunk signals are computed once at parse time and a scan walks the folder
without resolving every path, so the practical limit rises to 10,000 notes
with a timing-bounded test against real files; the index is still rebuilt on
use, with no watcher or background job, per the paragraph above. The Home
preview shows what a goal retrieves (citation, score, matched terms, token
cost and the provider and model the excerpts go to) and lets the user exclude
citations; `run.started` records the excerpts and exclusions, and the run view
folds them into a "Retrieved context" section. The vault gains move or rename
with link rewriting, folder import, pinning, unresolved-link and orphan
counts, templates, daily notes, "Save as note" from an event, and a retrieval
evaluation screen (MRR and recall at k). Deferred past 0.3.0: local embedding
models, attachments, PDFs and web clipping.

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
- Executing Obsidian community plugins inside AgentSpace
- Agent marketplaces or plugin systems
- Intel macOS release artifacts (Apple Silicon `.app.zip` added for 0.2.0 on 2026-09-13;
  see constraint #7 and the Phase 9 deviation)
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
