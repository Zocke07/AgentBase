# BUILD_SPEC.md — Autonomous Agent Co-Working Space

You are building this project from scratch in an empty repository. Read this entire
document before writing any code. Re-read it at the start of every session.

---

## 0. What we are building

A **local-first desktop application** where multiple AI agents collaborate on tasks, and
the user watches them work in real time on a live graph. Optionally reachable from Discord
and Telegram.

It ships as a single installer. The end user is not a developer.

### Primary success criterion

A user double-clicks an app icon, types a task, and watches agents spawn, call tools, hand
off to each other, and finish — with every step visible as it happens. No terminal, no
Docker, no config files.

---

## 1. Hard constraints — do not violate these

These are decisions already made after long deliberation. Do not "improve" them, do not
substitute equivalents, do not add the thing they replaced. If you believe one is wrong,
**stop and say so before implementing anything different.**

| # | Constraint | Why |
|---|---|---|
| 1 | **No agent framework.** No LangChain, LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, OpenClaw. Write the orchestration loop by hand. | The visualization is the product. It only works if we own the event stream. Frameworks emit their own event shapes and we'd adapt anyway. It's also the stronger portfolio signal — wiring up LangGraph is a weekend tutorial; an event-sourced orchestration loop with SSE streaming and a human-in-the-loop gate demonstrates the engineering. |
| 2 | **No Docker, no Postgres, no Redis, no LiteLLM proxy in the shipped product** (the Tauri app and the headless instance). | Single user, single machine. All of these exist to solve multi-user fleet problems we do not have — and a mismatched-scale stack (Kafka for a single-user desktop app) reads as a portfolio red flag, not a strength. A separate, optional demo path exists in Phase 10 for reviewers; it does not change what actually ships. |
| 3 | **Everything binds `127.0.0.1` only.** Hardcode it. Do not make the bind address configurable. | Nothing reachable off-machine means nothing to accidentally expose. |
| 4 | **API keys go in the OS keychain.** Never `.env`, never SQLite, never a config file, never logged. | The key sits on a personal laptop. |
| 5 | **Every filesystem/shell/network tool call passes an approval gate** before execution. No exceptions, no privileged paths for any channel. | This is the exact failure mode that produced dozens of CVEs in comparable projects. |
| 6 | **Chat channels trigger on explicit commands/mentions only.** Never ingest ambient channel messages into agent context. | Indirect prompt injection. A slash command has a schema; a channel firehose does not. |
| 7 | **Windows is the primary target.** macOS must build in CI from day one but is not released yet. | Windows-first, Mac later. |
| 8 | **Python 3.12 backend, TypeScript frontend.** No other languages except the Rust that Tauri requires. | |

> **On constraint #2**: this project is also a portfolio piece, so Phase 10 adds a second,
> optional way to run it — `docker compose up`, for a reviewer with no Rust/Python/Node
> toolchain who wants to see it working in one command. That path is scaffolding around the
> same backend code, not a second implementation, and it is not the "headless / server mode"
> excluded in §7 — it has no auth, no remote-reach story, and isn't meant to run unattended.
> What actually ships to your friend and what runs on your own machine stay exactly as
> constraint #2 describes.

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
│     │ Discord adapter │                  │ Telegram adapt │        │         │
│     │ (outbound WS)   │                  │ (long polling) │        │         │
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
│   │   │   │   ├── discord_adapter.py
│   │   │   │   └── telegram_adapter.py
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
  origin       TEXT NOT NULL,           -- ui|discord|telegram
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

### Event types — this list is the contract

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
acceptance criteria pass. Do not build ahead.

### Phase 0 — Scaffold and cross-platform hygiene

- `just` recipes for every dev task. No `.sh` or `.bat` files anywhere.
- `.gitattributes` with `* text=auto eol=lf`.
- `uv` for Python pinning, `.nvmrc` for Node.
- ESLint rule enforcing case-sensitive import paths (macOS/Windows filesystems are
  case-insensitive, Linux CI is not — this bug is invisible until CI).
- All paths via `pathlib` / `path.join`. Zero string concatenation of paths.
- `ruff` + `mypy --strict` on backend, `tsc --noEmit` on frontend, both wired into `just check`.

**Accept when:** `just check` passes on a clean clone.

### Phase 1 — Packaging spike (do this early, not last)

Before writing any real feature code, prove the hardest packaging problem works:

- A trivial FastAPI app returning `{"ok": true}`, compiled with `pyinstaller --onefile`.
- Tauri v2 `externalBin` pointing at it, a React page that fetches from it and renders the result.
- Build an actual installer on Windows (NSIS via `tauri build`) and launch it from a normal
  per-user install location.

Known traps to handle here, not later:
- `externalBin` requires the `-x86_64-pc-windows-msvc` suffix on the binary filename (target
  triple, not just `-windows` or `.exe`).
- Tauri caches the resolved sidecar under `target/release/`. A rebuilt binary can silently
  fail to make it into the bundle — verify actual bundle contents, don't trust the build log.
- With `--onefile`, Tauri only knows the PyInstaller *bootloader* PID, not the real child
  process. `process.kill()` will orphan the server. Implement graceful shutdown over
  stdin/HTTP and verify no stray `python`/sidecar process survives app quit (check Task
  Manager, not just that the window closed).
- The NSIS installer has a known issue where a stale cached sidecar binary is reused on
  reinstall/upgrade even after a clean rebuild — confirm the sidecar's file size/hash inside
  the produced installer matches the freshly built one before trusting a release.
- Tauri's webview on Windows requires the WebView2 runtime. Most Windows 11 machines have it
  preinstalled; Windows 10 machines may not. Bundle the WebView2 bootstrapper in the NSIS
  config so first install doesn't silently fail on an old machine.
- Build for `x86_64-pc-windows-msvc` only in v1. Windows-on-ARM exists but is niche enough
  to skip — treat it the same as local-model support: the abstraction shouldn't assume x64,
  but don't spend time building or testing it now.

**Accept when:** a built installer on a machine with no Python installed runs, serves, and
leaves zero orphan processes in Task Manager after the app is closed.

### Phase 2 — Event spine

The core. Get this right and everything else is straightforward.

- SQLite schema + migrations, DB file in the OS app-data dir (via Tauri's path API).
- `EventStore.append()` — assigns `seq` atomically per run.
- `EventBus` — in-process `asyncio` fan-out to subscribers.
- `GET /runs/{id}/events` as SSE, honouring `Last-Event-ID` to replay from a sequence number.
- A `fake_run` debug endpoint that emits a scripted sequence of ~20 events over 10 seconds.

**Accept when:** the debug run streams to a `curl` client, and killing/reconnecting mid-stream
resumes with zero gaps and zero duplicates.

### Phase 3 — Providers, budget, keychain

- `Provider` protocol: `complete(messages, tools) -> Response` with normalized token usage.
- Implement Anthropic and OpenAI. Add an Ollama implementation behind the same protocol
  (local model support is optional at runtime but the abstraction must not assume cloud).
- `pricing.py`: per-model input/output cost. All money as **integer micros**, never floats.
- `budget/ledger.py`: monthly cap. Check *before* each call, record *after*. Emit
  `budget.warning` at 80%, `budget.exceeded` and refuse at 100%.
- Keys read from OS keychain via `tauri-plugin-keyring`, passed to the sidecar at spawn
  time over stdin — never as a command-line argument (argv is world-readable via `ps`).

**Accept when:** switching provider is a settings change with no code change, and a run
that would exceed the monthly cap is refused with a clear reason before any API call fires.

### Phase 4 — Orchestrator

- `Run` owns lifecycle and the event sequence.
- `Supervisor`: given a goal, decomposes into subtasks and spawns worker agents.
- `Agent`: the worker loop — think, call tool, observe, repeat, until done or budget/step limit.
- Agents communicate via `agent.message` events, never direct function calls. Handoffs are
  `agent.handoff` events.
- Hard limits: max steps per agent, max agents per run, max wall-clock per run. All configurable,
  all enforced, all emit a terminal event when hit.

**Accept when:** a two-worker run completes end to end, and the full event log alone is
sufficient to reconstruct exactly what happened without reading any other state.

### Phase 5 — Agent registry (user-defined agents)

Agents stop being hardcoded Python classes and become editable data.

- `agent_defs` table (see §4) plus CRUD endpoints in `api/agents.py`.
- `registry.py` loads definitions from the DB at run start. It no longer imports agent
  classes; it constructs workers from rows.
- Seed 3–4 built-in definitions on first launch (e.g. `researcher`, `writer`, `reviewer`)
  so a fresh install is usable immediately. Built-ins are editable but not deletable —
  `is_builtin = 1` guards the delete path only.
- `allowed_tools` is an **allowlist, never a denylist.** An agent can only call tools named
  in its own row. An empty array means the agent can reason and hand off but touches nothing.
- A definition edited mid-run does not affect the in-flight run. Runs snapshot the
  definitions they started with; changing an agent is not a way to mutate a running agent.
- Validation on write: name uniqueness, non-empty system prompt, every entry in
  `allowed_tools` must resolve to a registered tool, `max_steps` within the global cap.
  Reject at the API layer with a readable message, not a 500.

**Security note — read this before implementing.** User-authored prompts do **not** widen
the security model, and must not be allowed to. The approval gate (next phase) lives at the
*tool execution* layer. A sloppy, over-permissive, or actively adversarial system prompt
still cannot reach the filesystem or shell without passing the same gate as everything else.
`auto_approve` on an agent definition may only *narrow* what the global policy already
permits — it can never grant a risk level the workspace policy has not enabled. If you find
yourself writing code where an agent definition escalates its own privileges, stop.

**Accept when:** an agent created entirely through the API — never touching Python — can be
spawned into a run, and an agent whose `allowed_tools` omits `write_file` is blocked from
calling it even when its system prompt explicitly instructs it to.

### Phase 6 — Tools and the approval gate

- `Tool` protocol with a declared `risk` level.
- Built-ins: `read_file`, `write_file`, `list_dir`, `http_get`, `run_shell`.
- **Sandbox**: a configured workspace root. Path traversal outside it is rejected before
  the approval prompt is even shown. `run_shell` has no network and a hard timeout.
- **Approval gate**: any `medium`/`high` risk call emits `approval.requested` and blocks
  until resolved. `low` risk (read within workspace) may be auto-approved by policy.
- Approval prompts must be **human-legible**, not raw JSON:
  `Agent "researcher" wants to delete report.docx — Allow / Deny`.
- A policy setting for unattended operation: pre-authorize a named risk subset so overnight
  runs can progress. Default is manual-approve-everything.

**Accept when:** an agent instructed to write outside the workspace root is blocked at the
sandbox layer, and this is visible in the event log as `tool.denied`.

**Addendum — container-sandboxed `run_shell` (your instance only, not part of the shared
build).** The app-level sandbox above is a real but limited boundary: a successfully
prompt-injected or misbehaving shell command still runs as your actual user account. On your
own always-on instance, wrap `run_shell` specifically in a short-lived container — network
disabled, read-only mount except the workspace root, CPU/memory capped, killed on timeout.
This is the one place Docker earns its way into this project on genuine merit rather than as
a resume line: it's real OS-level isolation for the one tool that can do the most damage, not
containerization for its own sake. Keep it scoped to this single tool call — do not
containerize the rest of the app to justify it.

### Phase 7 — Dashboard

- React Flow canvas: supervisor and workers as nodes, handoffs as edges, live status colour.
- Event log panel, filterable by agent and event type.
- Approval dialogs surfaced modally with the human-legible text from Phase 6.
- Budget meter: month-to-date spend against cap.
- Replay: scrub any past run from the event log using the identical rendering path as live.
- **Agent roster** (`AgentList.tsx`): every defined agent, its role, model, and tool count.
  Enable/disable toggle. Create and delete.
- **Agent editor** (`AgentEditor.tsx`): name, role, system prompt (textarea), provider/model
  dropdowns, tool allowlist as checkboxes, max steps. Surface the API's validation errors
  inline on the offending field — never a toast that loses which field was wrong.
  Tool checkboxes show each tool's risk level next to it, so the consequence of ticking
  `run_shell` is visible at the moment of ticking it.
- Generate TS types from the FastAPI OpenAPI schema; never hand-write the API types.

**Accept when:** replaying a completed run produces pixel-identical UI state to what was
shown live, and a new agent can be created, edited, and run without leaving the app.

### Phase 8 — Channel adapters

- `ChannelAdapter` protocol. Both adapters normalize to
  `{channel, external_user_id, text, thread_ref, ts}` and emit `channel.inbound`.
- **Discord**: `discord.py`, own process. Slash commands and @mentions only. Do **not**
  request the `MessageContent` privileged intent — the non-privileged baseline is sufficient
  and keeps the review requirement and the attack surface off the table. Defer the
  interaction immediately (3s ack limit) and edit the deferred reply as events stream.
  Throttle outbound through the adapter; Discord's global cap is 50 req/s with tighter
  per-channel limits.
- **Telegram**: `python-telegram-bot`, long polling (not webhooks — no inbound port). Leave
  privacy mode on. Respect 30 msg/s per chat.
- Map external user IDs to an internal identity so budget and permissions apply uniformly
  regardless of origin.
- A run started from Discord must appear live in the dashboard, and vice versa. Same event
  log, no special-casing.

**Accept when:** the same run is observable simultaneously from the dashboard and the
originating chat channel, and a channel-originated tool call still hits the approval gate.

### Phase 9 — CI and release

- **Test job runs before the build job and gates it.** `pytest` on the backend (event store,
  budget ledger, sandbox, agent registry validation at minimum), `vitest` on the frontend
  reducers (`RunGraph`, `EventLog`). A red test blocks the build job entirely — CI that only
  builds and never tests is not CI, it's a compiler check with extra steps.
- GitHub Actions matrix: `windows-latest` and `macos-latest`. Build the PyInstaller sidecar
  on each (it does not cross-compile), then the Tauri bundle.
- Publish the Windows artifact. Build but do not publish macOS — it exists to catch
  cross-platform breakage continuously, so the eventual Mac release is a flag flip rather
  than a port.
- **Keep the repo public.** Private-repo Actions minutes drain at a 2x multiplier on Windows
  runners and 10x on macOS — the macOS build-only-in-CI job is the expensive one to watch.
- Ship unsigned for now. Unlike macOS, Windows does not hard-block an unsigned app — the
  installer triggers a SmartScreen "Windows protected your PC" prompt, and the user clicks
  "More info" → "Run anyway" once. No terminal command, no equivalent of `xattr` needed.
  Document this one click in the `README` so it doesn't read as broken. An EV code-signing
  cert removes the warning entirely if it's ever worth the cost — optional, not required to
  ship.
- No entitlements file needed on this platform. When macOS moves from build-only to
  released, that's the point to write its entitlements
  (`allow-unsigned-executable-memory`, `disable-library-validation`) — not before.

**Accept when:** a green CI run produces a downloadable installer that runs on a second
Windows machine with no Python installed.

### Phase 10 — Portfolio artifacts

This phase exists because the project is being evaluated by people who will spend under a
minute deciding whether to look closer. Optimize for that.

- **`docker compose up` demo path.** A `docker-compose.yml` at repo root running the FastAPI
  backend (SQLite, same code as the shipped product — no Postgres migration required, that's
  a real scope increase for a benefit that's mostly cosmetic here) plus the Vite dev server,
  reachable at `localhost:5173` with zero local Python/Node/Rust install. This is the one-line
  proof that the project runs, for someone who is not going to install a Windows toolchain to
  check.
- **README** with, in this order: a 15-second GIF or screenshot of the live agent graph, the
  one-command demo instructions above, the architecture diagram from §2, and a short
  "why no LangChain / why no Kubernetes" note — reviewers who know the ecosystem will ask
  that question in their head anyway; answer it before they do.
- **Test coverage visible, not just present.** A coverage badge or a one-line summary in the
  README (`pytest --cov`) — the existence of tests matters less to a reviewer than being able
  to see the number in five seconds.
- Link the OpenAPI docs (`/docs`, free from FastAPI) from the README. It costs nothing and is
  the kind of detail that signals the API was designed, not improvised.

**Accept when:** someone with none of this project's toolchain installed can go from `git
clone` to a running agent graph in under five minutes using only the README.

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

- Multi-user accounts, auth, or tenancy
- Any network-exposed surface beyond `127.0.0.1`
- Vector memory / RAG
- Agent marketplaces or plugin systems
- macOS release artifacts (builds in CI, not published yet — see constraint #7)
- Code signing or notarization
- Auto-update
- Mobile
- Headless / server mode (a future option, not now)
- Local model support as a *requirement* — the abstraction exists, the implementation is
  optional and untested in v1

---

## 8. Start here

Confirm you have read this document. State which phase you are starting and what you plan
to do in it. Then begin Phase 0.
