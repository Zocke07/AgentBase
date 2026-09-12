# AgentSpace — Developer Guide

How to get a clone of this repository to a green gate, run it three different
ways, debug each half, write tests the way the existing ones are written, and
extend it without tripping the traps earlier phases already fell into.

Three other documents matter, and this one does not repeat them:

- **[BUILD_SPEC.md](../BUILD_SPEC.md)** is the design and the constraints. Read
  it before changing anything. Its §1 constraints are not negotiable, and §6
  says how work is expected to proceed.
- **[CLAUDE.md](../CLAUDE.md)** is the running log: what each phase built, what
  it verified, which bugs it found, and every mid-build decision with its
  reasoning. When you are about to change something and wonder *why is it like
  this*, the answer is almost always there. Search it before re-deciding.
- **[USER_GUIDE.md](USER_GUIDE.md)** is how the product behaves from the outside.
  Read it once so you know what the thing you are debugging is supposed to do.

---

## Contents

1. [Toolchain](#1-toolchain)
2. [From clone to green](#2-from-clone-to-green)
3. [Repository map](#3-repository-map)
4. [Running it](#4-running-it)
5. [The dev data directory](#5-the-dev-data-directory)
6. [Debugging the backend](#6-debugging-the-backend)
7. [Debugging the frontend](#7-debugging-the-frontend)
8. [Debugging the Tauri shell](#8-debugging-the-tauri-shell)
9. [Tests](#9-tests)
10. [Adding things — the checklists](#10-adding-things--the-checklists)
11. [Building and verifying the installer](#11-building-and-verifying-the-installer)
12. [CI](#12-ci)
13. [Conventions](#13-conventions)
14. [Gotchas](#14-gotchas)

---

## 1. Toolchain

Everything is driven through [`just`](https://just.systems). There are no `.sh`
or `.bat` files in the repository and a test fails if one appears.

| Tool | Version | Needed for | Notes |
|---|---|---|---|
| `just` | any recent | everything | |
| [`uv`](https://docs.astral.sh/uv/) | any recent | backend | Fetches Python 3.12 itself; do not install Python for this. |
| Node | `26.x` (see [`.nvmrc`](../.nvmrc)) | frontend | `nvm use` reads the file. |
| Rust (MSVC) via `rustup` | stable, ≥ 1.77 | `just dev-app`, `just build-installer`, `just check-tauri` | Not needed for the backend, the browser dev loop, `just check` or `just test`. |
| Visual Studio Build Tools, *Desktop development with C++* | | Rust on Windows | The MSVC linker. |
| WebView2 runtime | | running the app | Preinstalled on Windows 11. |
| [7-Zip](https://7-zip.org) | | `just verify-build` | Unpacks the NSIS installer to compare the sidecar inside it. Without it those tests skip (or fail under `--require-build-checks`). |

`just versions` prints what it finds. Python is **3.12 exactly** — `discord.py`
imports `audioop`, which 3.13 removes.

**Everything the toolchain generates stays inside the repository.** The
justfile exports `CARGO_HOME`, `UV_CACHE_DIR`, `npm_config_cache`,
`PYINSTALLER_CONFIG_DIR` and `AGENTSPACE_DATA_DIR` into a git-ignored `.dev/`,
so a clone on a roomy drive does not fill the system drive. `just paths` prints
the resolved locations. This applies **only inside `just` recipes** — a command
you run by hand does not get these exports, which matters in §4 and §5.

---

## 2. From clone to green

```
git clone https://github.com/Zocke07/AgentBase
cd AgentBase
just setup     # uv sync + npm install
just check     # ruff, ruff format --check, mypy --strict (twice), eslint, tsc
just test      # pytest + vitest
```

`just ci` is `check` + `test` and is exactly what CI runs. It has to pass on a
clean clone — `check` depends on `setup` for that reason — and it must pass
before you push.

`just check` typechecks the backend **twice**: once natively and once with
`mypy --platform darwin`. mypy narrows `sys.platform` to the host and silently
prunes the losing branch, so a `warn_unreachable` error in a macOS-only branch
is invisible on Windows. That is how CI run #2 failed; the second pass
reproduces it locally in twenty seconds.

`just fmt` applies `ruff format`, `ruff --fix` and `eslint --fix`.

---

## 3. Repository map

```
apps/backend/src/agentspace/    Python 3.12 FastAPI sidecar
  main.py                       app factory, lifespan, stdin watchdog, run()
  config.py                     BIND_HOST (hardcoded), ports, data paths
  secrets.py                    API keys in memory; the stdin handshake
  events/                       EventType, EventStore.append, EventBus
  store/                        SQLite + migrations (*.sql), settings, agent_defs
  providers/                    Provider protocol, Anthropic/OpenAI/Ollama, pricing, factory
  budget/ledger.py              the monthly cap, checked before every call
  orchestrator/                 run lifecycle, supervisor, agent loop, limits,
                                control tools, registry, launcher
  tools/                        catalogue, Tool protocol, sandbox, approval gate,
                                runtime, builtin/{filesystem,network,shell}.py
  channels/                     Discord + Telegram adapters, identity allowlist,
                                the chat renderer, throttle, service
  api/                          runs, stream (SSE), approvals, agents, settings, channels
  openapi.py                    builds the OpenAPI doc and emits the TS types
apps/backend/tests/             pytest; support.py holds the shared doubles
apps/desktop/src/               React 19 + Vite + TypeScript
  lib/                          api.ts (typed calls), events.ts (SSE client), sidecar.ts
  state/                        reducer.ts — THE fold; runStore, graph, hooks
  components/                   RunGraph, EventLog, ApprovalDialog, AgentList,
                                AgentEditor, BudgetMeter, RunPanel, RunSummary, views
apps/desktop/src-tauri/         Rust shell: spawns the sidecar, reads the keychain
  binaries/                     the frozen sidecar lands here (git-ignored)
packages/schemas/               openapi.json + src/api.ts, GENERATED and committed
.github/                        workflows/build.yml + actions/toolchain
.dev/                           git-ignored: caches and dev runtime data
```

CLAUDE.md's "Layout" section explains every module §3 of the spec does not
name and why it exists.

### The one idea

Every agent action is an append-only row in `events`. The UI is
`reduceAll(events.slice(0, cursor))` and nothing else; live is that fold with
the cursor at the head, replay is the same fold with a smaller cursor. The
chat reply is a second pure fold of the same log. If you are about to send the
frontend something that is not an event row, or keep UI state that is not
derived from the log, stop — that is the bug.

---

## 4. Running it

There are three ways, and which one you want depends on what you are changing.

### 4.1 Backend + UI in a browser — the fast loop

No Rust, no freeze step, instant reloads. Two terminals.

**Terminal 1 — the sidecar from source.** There is no `just` recipe for this
yet, so set the data directory by hand or the sidecar writes to the *real*
app-data directory in `%LOCALAPPDATA%\dev.agentspace.desktop`:

```powershell
cd apps\backend
$env:AGENTSPACE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run python -m agentspace
```

It binds `127.0.0.1:8787`, applies migrations, and logs to the terminal.
**The terminal is its stdin, and stdin is the control channel:**

- The **first line** you type is the API-key handshake. To give it a key
  without touching the keychain, type a JSON object and press Enter:

  ```
  {"anthropic_api_key": "<your key>"}
  ```

  The log says `received 1 secret(s): anthropic_api_key` — the name, never
  the value. `{}` is a valid empty handshake. This is how the Tauri shell
  delivers keys too, so you are exercising the real path.
- Typing `shutdown` and Enter stops it cleanly. So does **Ctrl+C**, and so
  does **EOF** — which means `< NUL`, `< /dev/null` or a closed pipe stops it
  immediately. If you script it, keep stdin open.
- `AGENTSPACE_PORT=8790` moves the port (1024–65535). The Tauri shell does not
  read this — it pins 8787 — so it is only useful for a second, source-run
  sidecar.

**Terminal 2 — the frontend:**

```
just dev-desktop
```

Vite serves on `127.0.0.1:5173` (strict port). Open it in **Edge** — that is
WebView2's engine, so what you see is what the packaged app sees, including
CORS. Outside Tauri the page falls back to `http://127.0.0.1:8787` for the
sidecar, and both `127.0.0.1:5173` and `localhost:5173` are in
`ALLOWED_ORIGINS`.

<details>
<summary>Hot reload for the backend</summary>

`run()` does not use uvicorn's reloader, but `create_app` is a factory, so:

```powershell
cd apps\backend
$env:AGENTSPACE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run uvicorn agentspace.main:create_app --factory --host 127.0.0.1 --port 8787 --reload --reload-dir src
```

You lose the stdin handshake (no keys — fine for Ollama) and the watchdog.
**Stop it with Ctrl+C in that terminal.** The reloader is a parent process
with a spawned worker holding the socket; killing the parent from Task Manager
or `taskkill` leaves the worker alive and 8787 taken. See §14.
</details>

### 4.2 The whole app — `just dev-app`

```
just dev-app
```

This runs `just build-sidecar` (PyInstaller, a minute or two) and then
`tauri dev`, which starts Vite, compiles the Rust shell in debug, opens the
window, and spawns **the frozen sidecar** from `src-tauri/binaries/`. Use this
when you are working on anything the shell owns: the keychain handshake, the
data-directory injection, startup/shutdown, the `tauri.localhost` origin.

Consequences of "the frozen sidecar":

- A backend change needs `just build-sidecar` again (or re-run `dev-app`).
  Vite hot-reloads the frontend as usual.
- The shell reads **your real Credential Manager** — entries under service
  `dev.agentspace.desktop`. A dev run with a key stored there uses it. The
  terminal shows `[keychain] sending N key(s): [...]`.
- The data directory is `.dev/data`, because `just` exports
  `AGENTSPACE_DATA_DIR` and the shell defers to an inherited value.
- The debug build keeps a console: every sidecar line arrives prefixed
  `[sidecar]`. Right-click → **Inspect** in the window opens WebView2 devtools.

### 4.3 The installed app

`just build-installer`, then run the `.exe` from
`apps/desktop/src-tauri/target/release/bundle/nsis/`. See §11. This is the only
way to exercise the real data directory, the real origin, and the
uninstall/upgrade path. Several of this project's bugs were found *only* by
installing and looking — CLAUDE.md has the list.

**Only one thing can hold 8787.** The installed app, `dev-app`, and a
source-run sidecar all bind it. Close the installed app before developing.

---

## 5. The dev data directory

`.dev/data/` is what every `just` recipe — and the Tauri shell under
`dev-app` — uses:

```
.dev/data/
  agentspace.sqlite3      runs, events, spend, settings, agent_defs, approvals
  agentspace.sqlite3-wal  (WAL mode — readers never block the writer)
  workspace/              the sandbox root: the only place agents may read/write
  logs/                   created, currently unused
```

Delete it to start from a fresh install: migrations re-run and the three
built-ins are re-seeded. `just clean-dev` deletes it along with the package
caches; `just clean` deletes every git-ignored file including `.venv`,
`node_modules` and `target/`.

Reading the database while the app runs is safe (WAL). There is no `sqlite3`
CLI dependency; use the interpreter:

```powershell
cd apps\backend
uv run python -c "import sqlite3; c = sqlite3.connect('../../.dev/data/agentspace.sqlite3'); print(c.execute('PRAGMA user_version').fetchone()); [print(r) for r in c.execute('SELECT seq, agent_id, type FROM events WHERE run_id = (SELECT id FROM runs ORDER BY created_at DESC LIMIT 1) ORDER BY seq')]"
```

The `settings` table is key/value with JSON values; the `secrets` are **not**
in it and never will be.

---

## 6. Debugging the backend

### The API is self-describing

With any sidecar running, `http://127.0.0.1:8787/docs` is Swagger UI over the
live OpenAPI document. Every route is callable from there. Useful ones:

| Route | What it tells you |
|---|---|
| `GET /settings` | effective settings, **which** secrets arrived, whether the model is priced |
| `POST /settings/verify` | can a provider actually be built from the current settings + secrets |
| `GET /channels` | is Discord/Telegram connected, `last_error`, who was refused |
| `GET /runs/{id}/events/history` | the whole event log of a run as a JSON array |
| `GET /approvals` | what is pending right now |
| `POST /debug/fake_run?step_ms=500` | a scripted 20-event run, no model needed |

### Reading the event stream

The stream is plain SSE with **unnamed** frames — the event type is inside the
JSON body, deliberately (a named frame never fires `EventSource.onmessage`;
Phase 2 lost 20 of 20 events to that). So `curl` shows exactly what the browser
gets:

```powershell
curl -N http://127.0.0.1:8787/runs/<run-id>/events
curl -N -H "Last-Event-ID: 12" http://127.0.0.1:8787/runs/<run-id>/events   # resume
```

The stream closes itself on a terminal event (`run.completed`, `run.failed`,
`run.cancelled`). Anything appended *after* a terminal event is invisible to a
live watcher and visible to a replay — that was a real Phase 8 bug, and it is
the first thing to suspect when live and replay disagree by one event.

### A run with no model

`POST /debug/fake_run` plays a fixed script of 20 events over 10 seconds
(`step_ms=0` for tests). It exercises the store, the bus, SSE, the reducer and
the graph without a provider or a key. It is what the Phase 7 pixel comparison
used, because it is reproducible.

### A run with a free model

Install Ollama, `ollama pull qwen3:4b`, and `PATCH /settings` with
`{"provider": "ollama", "model": "qwen3:4b"}`. Runs cost $0, need no key, and
`qwen3:4b` reliably reaches `run.completed`. It is slow (a two-agent task is a
few minutes) and its plans are weak; CLAUDE.md's "Which local model actually
drives the loop" has the measurements. `gemma4:e4b` does not converge — do not
spend time on it.

### Logging

`logging.basicConfig(level=INFO)` to stderr; nothing writes to `logs/`. Under
`dev-app` the shell relays it as `[sidecar] ...`. Loggers are per package
(`agentspace.store`, `agentspace.secrets`, `agentspace.channels.discord`, …).
`ruff`'s `T20` rule bans `print` in `src/` — the event log is the output
channel, and stderr is for operational messages only.

**Nothing may log a secret.** `SecretStore.__repr__` is value-free on purpose;
`parse_secrets_line` reports counts, not content. If you add a log line near a
credential, log its *name*.

### When a run fails

Every failure path ends in a `run.failed` event whose `reason` is written for a
user. Read it from the history endpoint or the UI before reading code:

- *"No API key for anthropic…"* — the handshake did not carry it. Check
  `configured_secrets` in `GET /settings`.
- *"This call would exceed the monthly budget…"* — the ledger refused before
  the call. `GET /budget`.
- *"no price is registered for model…"* — add it to `PRICES` (§10).
- *"This run hit its time limit…"* — `max_run_seconds`, which also expires any
  pending approval.
- *"supervisor stopped after N steps with no result"* — it never called
  `finish`. Usually a model-capability problem, not an orchestrator one.
- *"The run stopped unexpectedly: …"* — an unhandled exception; the traceback
  is in the sidecar log under `run <id> failed`.

### Two settings you can set that the UI cannot

`auto_approve: ["low", "medium", "high"]` makes every gate answer itself, so a
scripted or local-model run proceeds with nobody clicking. Auto-approved calls
still write their `approvals` row and both events, marked `automatic`. Set it
back afterwards. Also `max_run_seconds` — raise it when debugging with a slow
local model, or you will be chasing deadline failures that are not bugs.

---

## 7. Debugging the frontend

`just dev-desktop`, open `http://127.0.0.1:5173` in Edge, and keep the console
open. Phase 7's missing-handoff-edges bug was visible **only** as a React Flow
warning in the console while every test passed.

### Where state lives

- **`state/reducer.ts`** is the single fold. `RunView` is derived from events
  and nothing else. An event type it does not recognise lands in
  `view.unrecognised` rather than being dropped, so a server newer than the
  build shows up as a list of names, not as silence.
- **`state/runStore.ts`** (Zustand) holds `events`, `cursor` and `connection`.
  `view === reduceAll(events.slice(0, cursor))`, always. Scrubbing backwards
  refolds from zero because the reducer has no inverse — that is by design and
  a test fails if you "optimise" it.
- **`state/graph.ts`** turns a `RunView` into nodes, edges and a camera,
  arithmetically. The camera is *not* `fitView`: fitting depends on when nodes
  were measured, which made live and replay differ by 10% of the pixels.
- **`lib/events.ts`** is the `EventSource` client. It closes itself on a
  terminal event; without that the browser re-requests a finished run every
  second forever.

Component-local state is only for facts about the *viewer* — log filters, the
selected agent. If two people looking at the same log could see different
state, it belongs in the component; if not, it belongs in the reducer.

### Rules the UI follows that look like bugs

- `llm.token` events never change an agent's activity. Only `agent.thinking`
  and `llm.request` do, because a model can stream nothing at all.
- The terminal summary is rendered under *"The supervisor's account of the
  run"* beside a count of actual tool calls. They disagree routinely; the UI
  must not pretend otherwise.
- No relative timestamps anywhere. "3 seconds ago" would make the same event
  render differently on every fold.
- Replay and live must render identically **except** the scrubber. `RunPanel`
  is the boundary: `run-projection` is pure, the scrubber is not.

### Tests

`just test-desktop` runs vitest once; `npm run test:watch` in `apps/desktop`
watches. `src/test/setup.ts` stubs `ResizeObserver` and gives React Flow nodes a
fixed non-zero size — jsdom has no layout, and with zero-sized nodes React Flow
silently draws no edges, which is precisely the bug the test needs to be able
to see.

---

## 8. Debugging the Tauri shell

`apps/desktop/src-tauri/src/lib.rs` is small and does three things: resolve the
data directory and spawn the frozen sidecar with it in the environment; read
the four `SECRET_NAMES` from the keychain and write them as one JSON line to
the sidecar's stdin; and on exit write `shutdown`, wait up to five seconds for
port 8787 to close, then kill as a last resort.

- Run it with `just dev-app`. The debug build keeps the console; output is
  `eprintln!`, no `RUST_LOG`.
- Lint it with `just check-tauri` — **after** `just build-sidecar`.
  `tauri-build` validates `externalBin` on every cargo invocation, clippy
  included, so with an empty `binaries/` it fails on a missing resource before
  linting a line. This order looks wrong and is pinned by a test.
- The keychain entry is looked up as Windows generic credential
  `<name>.dev.agentspace.desktop` (the `keyring` crate's `{user}.{service}`
  rule). To test the handshake end to end, add one in Credential Manager and
  watch for `[keychain] sending 1 key(s)` followed by the sidecar's
  `received 1 secret(s)`.
- Orphan check after any shutdown change: close the window, then confirm no
  `agentspace-sidecar` process survives and 8787 is released. With
  `--onefile` there are *two* sidecar processes while running (bootloader +
  interpreter) and the PID the shell holds is the bootloader's.
- `SECRET_NAMES` in `lib.rs` and `SECRET_KEYS` in `secrets.py` are one list in
  two languages; `test_secrets.py` reads the Rust source and compares.

---

## 9. Tests

```
just test                                   # both suites
just test-backend                           # pytest
just test-backend tests/test_sandbox.py -k symlink -v
just test-backend-cov                       # with --cov=agentspace term-missing
just test-desktop                           # vitest run
just test-desktop src/state/reducer.test.ts
```

Backend tests are async on **anyio's** pytest plugin (asyncio backend only),
with a **60-second per-test timeout** — a stream that never terminates fails
instead of hanging CI. An autouse fixture points `AGENTSPACE_DATA_DIR` at
`tmp_path`, so no test can touch a real data directory even if it forgets to
pass paths.

### The doubles — `tests/support.py`

| Name | What it is for |
|---|---|
| `ScriptedProvider([...])` | A `Provider` that returns a fixed list of completions, on both `complete` and `stream`. Raises if asked for more than scripted. Records every request, system prompt and offered tool list. |
| `says(text, *calls)` | Builds one scripted `Completion`; `call("write_file", path=..., content=...)` builds a `ToolCall`. |
| `StandingAnswer(service, approve=…)` | Answers every approval the instant it is raised, **through the real gate** — the row is written and both events fire. Not a fake service. |
| `FakeClock` | Deterministic deadlines for the wall-clock limit. |
| `tool_runtime(...)` | A `ToolRuntime` rooted at a temp sandbox. |
| `reconstruct(events)` | The Python event-log reducer. Reads **only** event rows. Every assertion about a run goes through it. |

`RunLauncher.provider` is the override hook: a test passes a
`ScriptedProvider` and every agent in the run uses it — still wrapped in
`BudgetedProvider`, so a test cannot prove the cap holds on a path that
bypasses it.

The pattern for a run test is: script the model's turns, launch, let
`StandingAnswer` handle the gate, then assert on `reconstruct(store.read(...))`.
`test_orchestrator.py`, `test_agent_registry.py` and `test_approval_gate.py`
are full of examples.

### Write tests first for three modules

§6 of the spec: the event store, the budget ledger and the sandbox. "These three
are where silent bugs become expensive."

### Mutation-check your tests

This project's habit, and worth keeping: after writing a test for a guarantee,
**break the guarantee** and confirm the test fails. CLAUDE.md records a dozen of
these, including one where the first mutation was too small and the suite
stayed green while the thing supposedly under test had not been removed. A
mutation that does not fail is not evidence the code is right.

### Tests that skip, and why

`test_sidecar_binary.py` and `test_installer_bundle.py` inspect *built*
artefacts and skip when there are none — right for `just test`, wrong for a
release. `just verify-build` passes `--require-build-checks`, which turns each
skip into a failure naming what was missing. `test_installed_app.py` **installs
software** and only runs under `--install-smoke` (`just verify-installed`); it
is never part of `just test`.

The symlink-escape sandbox test runs on Windows rather than skipping — it falls
back to a directory junction, which needs no privilege and which
`Path.resolve` follows identically. A test that skips on the primary platform
is not coverage of it.

---

## 10. Adding things — the checklists

Each of these is a set of places that must agree. In every case a test already
exists that fails when they do not — read the failure, it names the other place.

### An event type

1. `events/types.py` — add to `EventType`; add to `TERMINAL_RUN_EVENTS` if it
   ends a run.
2. `just schemas` — regenerate `packages/schemas`. `test_openapi_snapshot.py`
   fails byte-for-byte until you do.
3. `apps/desktop/src/state/reducer.ts` — a `case` for it. Also `EventLog.tsx`
   if it needs rendering.
4. `channels/render.py` — a `case` in `fold`. The `case _: assert_never(...)`
   arm makes this a **mypy error**, not a runtime surprise;
   `test_every_event_type_in_the_contract_is_handled_by_the_fold` also checks.
5. Same commit for all of it (BUILD_SPEC §4).

### A workspace setting

1. `store/settings.py` — a field on `WorkspaceSettings` with its default.
2. `api/settings.py` — the same field on `UpdateSettingsRequest`.
   `test_every_workspace_setting_can_be_patched` compares the two field sets;
   `extra="forbid"` already makes a missing one a loud 422.
3. `just schemas`.
4. If a run depends on it, **snapshot it at run start** (see `RunLimits`) — a
   run must not be held to different rules at step 1 and step 12.
5. If a service depends on it (channels), make the `PATCH` handler reconcile
   immediately — this product has no restart button.

**Never default a value elsewhere that duplicates a setting the user can
change.** That was the Phase 5 `max_steps` bug; the rule is in CLAUDE.md.

### A secret

1. `secrets.py` — `SECRET_KEYS`.
2. `src-tauri/src/lib.rs` — `SECRET_NAMES`. `test_secrets.py` compares them.
3. If it is a provider key, `providers/factory.py` — `SUPPORTED_PROVIDERS`.

Secrets go in the keychain and travel over stdin. Never in `settings`, never in
a file, never in `argv`, never in a log. `test_no_api_keys_in_tracked_files`
scans for key-shaped prefixes, including in Markdown.

### A migration

1. `store/NNN_name.sql` — additive if at all possible. Guard any `UPDATE` to a
   seeded row on it still holding its seeded value (see 004).
2. `store/db.py` — append to `MIGRATION_FILES`.
3. Nothing else: the PyInstaller `--add-data` glob is `*.sql`, and
   `test_every_migration_file_is_bundled_by_the_packaging_glob` confirms it.
4. Run `test_upgrade_preserves_an_existing_populated_database`, then delete
   `.dev/data` and start the sidecar to watch it apply.

Built-ins are seeded by migration 003, **not** by startup code — a migration
runs exactly once, so "never seeded" and "seeded and since edited" never have
to be told apart.

### A tool

1. `tools/catalogue.py` — a `ToolDeclaration` with a name, description and
   `RiskLevel`. This is what `allowed_tools` validates against and what the
   editor's checkboxes render. Policy is a *set* of levels, not a threshold.
2. `tools/builtin/<module>.py` — implement `Tool`: **`prepare`** resolves and
   validates while touching nothing (the sandbox check lives here, so an
   out-of-bounds call is refused before anyone is asked), **`execute`** carries
   out an already-approved call. `Prepared.summary` is the sentence the user
   reads; build it from the *resolved* call.
3. `tools/builtin/__init__.py` — add to `BUILTIN_TOOLS`. `GET /tools` then
   reports it `available: true`.

Every tool goes through the gate. There is no flag to skip it and there must
not be one (§1 constraint 5).

### A model or a provider

- **Model:** a row in `providers/pricing.py` `PRICES`, as dollar *strings*
  (`_usd("2.50", "10.00")`) — never a float near money. It appears in
  `GET /settings/providers` and the editor dropdown automatically. An unpriced
  model is refused, not charged at zero; that is the point.
- **Provider:** a class implementing `Provider` (both `complete` and
  `stream`) in `providers/`, an entry in `factory.SUPPORTED_PROVIDERS`, and
  `qualified_model` if it namespaces model ids the way Ollama does.
  `test_qualified_model_is_what_the_built_provider_reports` covers every
  provider.

### An API route

1. A router in `api/`, included in `main.create_app`.
2. `just schemas`. The emitter **raises** on any OpenAPI keyword it does not
   understand rather than emitting `unknown` — fix the model or extend
   `openapi.py`, do not weaken the emitter.
3. If the dashboard calls it, `lib/api.ts` — using only generated types.
   `test_the_schema_covers_every_route_the_dashboard_calls` checks.
4. Validation failures are `400`/`409`/`422` with a readable message and, where
   possible, the `field` they blame. Never a 500.

---

## 11. Building and verifying the installer

```
just build-sidecar      # PyInstaller --onefile → src-tauri/binaries/agentspace-sidecar-x86_64-pc-windows-msvc.exe
just build-installer    # setup + build-sidecar + tauri build --bundles nsis
just verify-build       # AFTER a build: launches the frozen binary, unpacks the installer, compares hashes
just verify-installed   # installs it on THIS machine and runs it with Python scrubbed from PATH
```

The installer lands in `apps/desktop/src-tauri/target/release/bundle/nsis/`.
Silent install: `AgentSpace_0.1.0_x64-setup.exe /S`.

Things that will bite:

- **The filename must carry the target triple** or Tauri never finds it — and
  Tauri then *strips* the triple when staging, so the shipped file is
  `agentspace-sidecar.exe`. Looking for the built name inside the installer
  finds nothing and looks like a bundling failure.
- **`verify-build` exists because the bundle can carry a stale sidecar.**
  It compares the SHA-256 of the sidecar inside the installer against the one
  just built. Run it after every `build-installer`, never before.
- **The bundle target is a justfile variable**, `nsis` on Windows and `app` on
  macOS. Do not put `"targets": "all"` in `tauri.conf.json`; it also builds a
  per-machine MSI, which contradicts the per-user install Phase 1 verified.
- **Never cache or restore `src-tauri/target/` across machines.** That is how a
  stale `externalBin` gets bundled.
- The sidecar's `--add-data` uses `;` on Windows and `:` elsewhere; the
  justfile handles it. A wrong separator is not an error — it is a binary that
  starts and then cannot create its database.

---

## 12. CI

[`.github/workflows/build.yml`](../.github/workflows/build.yml), on push to
`main`, on pull requests, and on `v*` tags:

```
test (windows, macos)  →  build (windows, macos)  →  smoke (windows)  →  release (tag only)
     just ci                just build-installer       just verify-installed   gh release create
                            just verify-build
                            just check-tauri
                            upload installer
```

- **`build` has `needs: test`.** That one line is §5 Phase 9's requirement — a
  red test blocks the build — and `test_ci_workflow.py` asserts it, because
  deleting it breaks nothing visible.
- **The workflow runs `just` recipes only.** A step that inlines `pytest` is a
  second build system; a test asserts the test job is exactly `just ci`.
- Both jobs share `.github/actions/toolchain`. Every action ref there was
  confirmed to *exist* via `GET /repos/{o}/{r}/git/ref/tags/{tag}` — a tag
  listing produced `setup-uv@v10`, which does not exist and failed run #1.
- macOS is built and never published. It is there to catch cross-platform
  breakage, and it did on its first run.
- Every green run leaves the Windows installer as a workflow artefact. Only a
  `v*` tag creates a GitHub release.
- `.dev/cache` is cached; `target/` deliberately is not.

To reproduce CI locally: `just ci`, then `just build-installer && just
verify-build && just check-tauri`.

---

## 13. Conventions

**From BUILD_SPEC §6.** One phase per session. Do not claim something works
unless you executed it — "should work" and "works" are different words.
Negative results are useful; report them. Ask before deviating from a §1
constraint; do not route around it. Commit per logical unit with a real
message. Keep CLAUDE.md updated: the current phase, what was verified, what was
not, and every decision with its reasoning under "Decisions made mid-build".

**The recurring bug, stated as a rule.** Nine times in this project something
was correct everywhere except where the product actually used it, and every
test was green: CORS headers, named SSE frames, a `*.sql` glob, silently
dropped settings fields, a duplicated default, an unsettable policy, a
mispriced model id, a setting that did nothing until restart, a recipe that
could never have run. **Every one was found by running the thing.** Install it,
open it in the browser, type the command in Discord, read the console. A green
suite is where verification starts, not where it ends.

**Lint rules that encode decisions.** `PTH` (pathlib only, zero string path
concatenation), `DTZ` (no naive datetimes in an event log), `T20` (no `print`),
`S` (bandit), `TID` (no relative imports), `ARG` (unused arguments — exempted
only for `ARG002` on protocol-conforming doubles and adapters). `mypy --strict`
with `warn_unreachable` and `disallow_any_unimported`. ESLint enforces
case-sensitive import paths, because the CI Linux filesystem is case-sensitive
and this one is not.

**Line endings are LF, and it is enforced.** `.gitattributes` has
`* text=auto eol=lf`, `ruff format` is pinned to `lf`, and `ruff format
--check` is in the gate. If you write source from a Python helper, pass
`newline="\n"` — `Path.write_text` on Windows writes CRLF and only the format
check notices.

**Two lists that must agree get a test, not a comment.** Settings model vs.
patch model, `SECRET_KEYS` vs. `SECRET_NAMES`, migrations vs. the packaging
glob, the justfile vs. the workflow. When you find yourself writing "keep in
sync with X", write the test instead.

**Hardcoded on purpose:** `BIND_HOST = "127.0.0.1"`, guarded by
`assert_loopback_only` at every bind and by a test that fails if it becomes
configurable. `ALLOWED_ORIGINS` is an explicit allowlist, never a wildcard.

---

## 14. Gotchas

**The sidecar stops on stdin EOF.** `python -m agentspace < NUL`, or a subprocess
with a closed stdin, exits at once with `stdin reached EOF; shutting down`. Hold
stdin open. This is the shutdown mechanism, not a bug.

**Port 8787 is taken and nothing is listening.** Check for an orphaned uvicorn
reload worker: `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine
-like '*multiprocessing*' }` and `taskkill /PID <id> /T /F`. Or a stray
`agentspace-sidecar` from an installed app or a crashed `dev-app`. `netstat
-ano | findstr :8787` names the PID; note it can report the *creator* of the
socket rather than the process now holding it.

**`Invoke-WebRequest` and `curl` do not enforce CORS; a webview does.** A green
HTTP smoke test proves the server answered, not that the page was allowed to
read the answer. Test UI-facing changes in a browser.

**`httpx2`, not `httpx`.** The distribution and the module are both `httpx2`.

**`&&` is a parser error in Windows PowerShell 5.1**, which is `just`'s shell
here. Every recipe body is a single command with `[working-directory(...)]`
instead of `cd &&`.

**Vite's watcher ignores `src-tauri/**`.** Under `tauri dev` cargo writes
`target/` while Vite watches; on Windows the resulting EBUSY kills the dev
server. Do not remove the ignore.

**An open SQLite handle locks the file on Windows.** Tests close the database
before `tmp_path` teardown; the lifespan closes it before exit so the installer
can replace it. One connection behind a lock, not one per thread, for the same
reason.

**`Get-Content`/`json.load` on a pipe decodes as cp1252 in Git Bash.** A
`—` read back as `â€"` is your pipe, not your data. Check with `ord()` before
reporting mojibake.

**Anthropic coalesces streaming deltas unpredictably** — the same prompt
produced 1, 2 and 10 `text_delta` frames on four requests. Never build timing
around delta size, and never treat `llm.token` as a liveness signal.

**Small local models confabulate.** Four live runs have announced work
(`finish("saved to notes.txt")`) that the log shows never happened. When
debugging a run, believe `tool.called`, not the summary.

**`@mention` on Discord is almost certainly dead code.** `INTENTS` is `guilds`
only — no `guild_messages` — so `on_message` never fires. `/agent` is the
verified trigger. Recorded in CLAUDE.md as unexercised; if you fix it, adding an
intent is the change, and `test_channel_adapters.py` pins the intent set on
purpose, so update the test's reasoning too.
