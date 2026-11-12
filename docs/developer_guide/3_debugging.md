# Debugging

## Debugging the backend

### The API is self-describing

With a running sidecar, `http://127.0.0.1:8787/docs` serves Swagger UI for the
live OpenAPI document. Call every route there. Useful routes:

| Route | What it tells you |
|---|---|
| `GET /settings` | Effective settings, received secret names, and whether the model is priced. |
| `POST /settings/verify?space_id=<id>` | Whether the space's effective settings and startup secrets build a priced provider; no remote call. |
| `GET /auth/chatgpt` | ChatGPT state and safe account metadata; never tokens. |
| `GET /channels` | Discord connection, `last_error`, and refused users. |
| `GET /spaces/{id}` | Stored rule overrides, folder, and default-space flag. |
| `GET /runs?space_id=<id>` | runs belonging to that space |
| `GET /budget?space_id=<id>` | App-wide spend/cap and the space's share. |
| `GET /runs/{id}/events/history` | Full run event log as JSON. |
| `GET /approvals` | Pending approvals. |
| `POST /debug/fake_run?step_ms=500` | Scripted 20-event run; no model. |

### Reading the event stream

The stream uses **unnamed** SSE frames; event type is deliberately in the JSON
body. Named frames never fire `EventSource.onmessage` (Phase 2 lost all 20
events), so `curl` shows what the browser receives:

```bash
curl -N 'http://127.0.0.1:8787/runs/<run-id>/events'
curl -N -H 'Last-Event-ID: 12' 'http://127.0.0.1:8787/runs/<run-id>/events'
```

In Windows PowerShell 5.1, use `curl.exe` because `curl` can alias
`Invoke-WebRequest`. Substitute a real run ID. First browser connections may
resume with `?after_seq=12`; reconnects also accept `Last-Event-ID`.

The stream closes on `run.completed`, `run.failed`, or `run.cancelled`. A later
event appears in replay but not live; check this first when they differ by one
event (a Phase 8 bug).

### A run with no model

`POST /debug/fake_run` emits a fixed 20-event, 10-second script (`step_ms=0`
for tests). It exercises store, bus, SSE, reducer, and graph without a provider
or key; Phase 7's pixel comparison used it for reproducibility. It always uses
Main and accepts no `space_id`.

### A run with a free model

Install Ollama, run `ollama pull qwen3:4b`, then `PATCH /settings` with
`{"provider": "ollama", "model": "qwen3:4b"}`. It costs $0, needs no key, and
previous live checks reached `run.completed`. They were slow with weak plans;
[project history](../history/README.md) records measurements and failed
`gemma4:e4b` attempts. That is observed behavior, not a guarantee. Update a
space-level provider/model override or restore inheritance.

### Logging

`logging.basicConfig(level=INFO)` writes to stderr, not `logs/`; `dev-app`
relays it as `[sidecar] ...`. Loggers are per package (`agentbase.store`,
`agentbase.secrets`, `agentbase.channels.discord`, …). Ruff `T20` bans
`print` in `src/`: use the event log for output and stderr for operations.

**Never log a secret.** `SecretStore.__repr__` omits values and
`parse_secrets_line` reports counts. Near credentials, log only their *names*.

### When a run fails

Every failure emits user-facing `run.failed.reason`. Read it in history or the
UI before reading code:

- *"No API key for anthropic…"*: the handshake did not carry it. Check
  `configured_secrets` in `GET /settings`.
- *"ChatGPT is not signed in…"*: inspect `GET /auth/chatgpt`, then connect the
  account from **Settings > Model**. An `error` state usually names the missing
  credential-store or runtime problem.
- *"This call would exceed the monthly budget…"*: the ledger refused before
  the call. `GET /budget`.
- *"no price is registered for model…"*: follow the
  [model checklist](5_checklists.md#a-model-or-a-provider).
- *"This run hit its time limit…"*: `max_run_seconds`, which also expires any
  pending approval.
- *"supervisor stopped after N steps with no result"*: it never called
  `finish`. Usually a model-capability problem, not an orchestrator one.
- *"The run stopped unexpectedly: …"*: an unhandled exception; the traceback
  is in the sidecar log under `run <id> failed`.

### Limits and approvals while debugging

`auto_approve: ["low", "medium", "high"]` answers every gate so scripted or
local runs need no click. Calls still write the `approvals` row and both events
as `automatic`; reset it afterward. Raise `max_run_seconds` for slow local
runs. Both settings are under **Settings > Limits and approvals** and can be
overridden in **Space settings**. Space or agent policy can narrow the app-wide
set, so an app-default change may not auto-approve a run.

---

## Debugging the frontend

Run `just dev-desktop`, open `http://127.0.0.1:5173`, and keep the console
open. Phase 7's missing-handoff-edge bug appeared only as a React Flow warning
while every test passed.

### Where state lives

- **`state/reducer.ts`** is the sole fold: `RunView` derives only from events.
  Unknown types enter `view.unrecognised`, so a newer server shows names rather
  than silently dropping events.
- **`state/runStore.ts`** (Zustand) holds `events`, `cursor`, and `connection`:
  `view === reduceAll(events.slice(0, cursor))`. Backward scrubbing refolds
  from zero because the reducer has no inverse; tests protect this design.
- **`state/graph.ts`** arithmetically derives workflow nodes (goal, supervisor,
  workers, outcome, and per-tool counts), edges (return handoffs use bottom
  ports), and camera. It never uses `fitView`, whose measurement timing caused
  10% live/replay pixel drift.
- **`lib/markdown.ts`** parses the Obsidian dialect into a tree and
  **`components/Markdown.tsx`** renders it; strings never become HTML. Blocks
  retain source lines so ticking a vault-preview task rewrites the right line.
- **`lib/events.ts`** is the `EventSource` client. It closes on terminal events
  so the browser does not re-request a finished run every second.

Run-projection state holds viewer facts such as log filters and selected agent.
Navigation, space selection, editable settings, and fetched rosters use other
stores/API state.

### Rules the UI follows that look like bugs

- `llm.token` events never change an agent's activity. Only `agent.thinking`
  and `llm.request` do, because a model can stream nothing at all.
- The terminal summary reports the supervisor's account and actual tool calls
  separately. They can disagree; do not mask it.
- No relative timestamps anywhere. "3 seconds ago" would make the same event
  render differently on every fold.
- Replay and live must render identically **except** the scrubber. `RunPanel`
  is the boundary: `run-projection` is pure, the scrubber is not.

### Tests

`just test-desktop` runs Vitest once; `npm run test:watch` in `apps/desktop`
watches. `src/test/setup.ts` stubs `ResizeObserver` and gives React Flow nodes
a fixed non-zero size: jsdom has no layout, and zero-sized nodes silently lose
edges; the test must catch that condition.

jsdom lays nothing out and computes no colour. To see a component, use
`just workbench`; to see the app, `just ui-shots`; to hold a look in place,
the visual tests ([Testing and CI](4_testing_and_ci.md)).

---

## Debugging the Tauri shell

`apps/desktop/src-tauri/src/lib.rs` resolves the data directory; starts the
frozen sidecar with it in the environment; reads `SECRET_NAMES` from the OS
keychain and sends one JSON line to stdin; then sends `shutdown` on exit,
waits up to five seconds for port 8787, and kills only as a last resort. It
also creates a per-launch `/health` instance tag so the webview rejects another
process on 8787, and restricts its folder opener to the app data directory.

- Run it with `just dev-app`. The debug build keeps the console; output is
  `eprintln!`, no `RUST_LOG`.
- Lint with `just check-tauri` **after** `just build-sidecar`. `tauri-build`
  validates `externalBin` on every Cargo invocation, including Clippy; empty
  `binaries/` fails before linting. A test pins this order.
- Set a key in the desktop app's **Settings > Keys**, then quit and reopen.
  This section is unavailable in a browser. The keychain service is
  `dev.agentbase.desktop`; Windows Credential Manager uses an address like
  `<name>.dev.agentbase.desktop`, and macOS uses the service plus the key
  name as account. Do not place key values in command arguments.
- On macOS, rebuilt ad-hoc-signed apps can prompt again. **Always Allow**
  trusts the current binary. **Deny** omits the key and logs
  `[keychain] could not read <name>: ...`; only a missing entry is silently
  treated as unset.
- Verify the handshake with `[keychain] sending 1 key(s)`, then
  `received 1 secret(s)`. Logs contain names/counts, not values. Rust stderr
  reveals keychain denial; Settings sees only a missing key.
- After shutdown changes, close the window and confirm no `agentbase-sidecar`
  survives and 8787 is free.
  - **Windows:** `Get-Process agentbase-sidecar` and
    `netstat -ano | findstr :8787`.
  - **macOS:** `pgrep -f agentbase-sidecar` and `lsof -ti tcp:8787`.
  - `--onefile` runs two sidecar processes (bootloader + interpreter); the
    shell holds the bootloader PID.
- `SECRET_NAMES` in `lib.rs` and `SECRET_KEYS` in `secrets.py` must match;
  `test_secrets.py` compares them.

---
