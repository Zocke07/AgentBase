# Debugging

## Debugging the backend

### The API is self-describing

With any sidecar running, `http://127.0.0.1:8787/docs` is Swagger UI over the
live OpenAPI document. Every route is callable from there. Useful ones:

| Route | What it tells you |
|---|---|
| `GET /settings` | effective settings, **which** secrets arrived, whether the model is priced |
| `POST /settings/verify?space_id=<id>` | can the space's effective settings and startup secrets build a priced provider; makes no remote API call |
| `GET /auth/chatgpt` | ChatGPT connection state and safe account metadata, never tokens |
| `GET /channels` | is Discord connected, `last_error`, who was refused |
| `GET /spaces/{id}` | the space's stored rule overrides, folder and default-space flag |
| `GET /runs?space_id=<id>` | runs belonging to that space |
| `GET /budget?space_id=<id>` | app-wide spend/cap and that space's share |
| `GET /runs/{id}/events/history` | the whole event log of a run as a JSON array |
| `GET /approvals` | what is pending right now |
| `POST /debug/fake_run?step_ms=500` | a scripted 20-event run, no model needed |

### Reading the event stream

The stream is plain SSE with **unnamed** frames: the event type is inside the
JSON body, deliberately (a named frame never fires `EventSource.onmessage`;
Phase 2 lost 20 of 20 events to that). So `curl` shows exactly what the browser
gets:

```bash
curl -N 'http://127.0.0.1:8787/runs/<run-id>/events'
curl -N -H 'Last-Event-ID: 12' 'http://127.0.0.1:8787/runs/<run-id>/events'
```

Use `curl.exe` in Windows PowerShell 5.1, where `curl` may be an alias for
`Invoke-WebRequest`. Substitute a real run id. A browser's first connection can
resume with `?after_seq=12`; reconnects also accept `Last-Event-ID`.

The stream closes itself on a terminal event (`run.completed`, `run.failed`,
`run.cancelled`). Anything appended *after* a terminal event is invisible to a
live watcher and visible to a replay, which was a real Phase 8 bug, and it is
the first thing to suspect when live and replay disagree by one event.

### A run with no model

`POST /debug/fake_run` plays a fixed script of 20 events over 10 seconds
(`step_ms=0` for tests). It exercises the store, the bus, SSE, the reducer and
the graph without a provider or a key. It is what the Phase 7 pixel comparison
used, because it is reproducible. The endpoint always creates its run in Main;
it does not take a `space_id` parameter.

### A run with a free model

Install Ollama, `ollama pull qwen3:4b`, and `PATCH /settings` with
`{"provider": "ollama", "model": "qwen3:4b"}`. Runs cost $0, need no key, and
`qwen3:4b` reached `run.completed` in previous live checks. Those runs were slow
and their plans were weak; the [project history](../history/README.md) preserves
the measurements and the failed `gemma4:e4b` attempts. These are observations
from particular runs, not a guarantee for a new task. If the chosen space
overrides provider/model, update that space too or set it to inherit.

### Logging

`logging.basicConfig(level=INFO)` to stderr; nothing writes to `logs/`. Under
`dev-app` the shell relays it as `[sidecar] ...`. Loggers are per package
(`agentspace.store`, `agentspace.secrets`, `agentspace.channels.discord`, …).
`ruff`'s `T20` rule bans `print` in `src/`: the event log is the output
channel, and stderr is for operational messages only.

**Nothing may log a secret.** `SecretStore.__repr__` is value-free on purpose;
`parse_secrets_line` reports counts, not content. If you add a log line near a
credential, log its *name*.

### When a run fails

Every failure path ends in a `run.failed` event whose `reason` is written for a
user. Read it from the history endpoint or the UI before reading code:

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

`auto_approve: ["low", "medium", "high"]` makes every gate answer itself, so a
scripted or local-model run proceeds with nobody clicking. Auto-approved calls
still write their `approvals` row and both events, marked `automatic`. Set it
back afterwards. `max_run_seconds` can be raised for slow local runs. Both
settings are available in **Settings > Limits and approvals** and can be
overridden in **Space settings**. A space or agent policy may narrow the
app-wide approval set, so changing the app default alone need not auto-approve
a particular run.

---

## Debugging the frontend

`just dev-desktop`, open `http://127.0.0.1:5173` in a browser, and keep the console
open. Phase 7's missing-handoff-edges bug was visible **only** as a React Flow
warning in the console while every test passed.

### Where state lives

- **`state/reducer.ts`** is the single fold. `RunView` is derived from events
  and nothing else. An event type it does not recognise lands in
  `view.unrecognised` rather than being dropped, so a server newer than the
  build shows up as a list of names, not as silence.
- **`state/runStore.ts`** (Zustand) holds `events`, `cursor` and `connection`.
  `view === reduceAll(events.slice(0, cursor))`, always. Scrubbing backwards
  refolds from zero because the reducer has no inverse: that is by design and
  a test fails if you "optimise" it.
- **`state/graph.ts`** turns a `RunView` into nodes, edges and a camera,
  arithmetically. The camera is *not* `fitView`: fitting depends on when nodes
  were measured, which made live and replay differ by 10% of the pixels.
- **`lib/events.ts`** is the `EventSource` client. It closes itself on a
  terminal event; without that the browser re-requests a finished run every
  second forever.

The run projection's local state is for facts about the viewer, such as log
filters and the selected agent. App navigation, space selection, editable
settings and fetched rosters have their own stores and API state; they are
outside the event-only run projection.

### Rules the UI follows that look like bugs

- `llm.token` events never change an agent's activity. Only `agent.thinking`
  and `llm.request` do, because a model can stream nothing at all.
- The terminal summary labels the supervisor's account and reports actual
  tool calls separately. They can disagree; the UI
  must not pretend otherwise.
- No relative timestamps anywhere. "3 seconds ago" would make the same event
  render differently on every fold.
- Replay and live must render identically **except** the scrubber. `RunPanel`
  is the boundary: `run-projection` is pure, the scrubber is not.

### Tests

`just test-desktop` runs vitest once; `npm run test:watch` in `apps/desktop`
watches. `src/test/setup.ts` stubs `ResizeObserver` and gives React Flow nodes a
fixed non-zero size: jsdom has no layout, and with zero-sized nodes React Flow
silently draws no edges, which is precisely the bug the test needs to be able
to see.

---

## Debugging the Tauri shell

`apps/desktop/src-tauri/src/lib.rs` resolves the
data directory and spawn the frozen sidecar with it in the environment; read
the `SECRET_NAMES` from the OS keychain and write them as one JSON line to
the sidecar's stdin; and on exit write `shutdown`, wait up to five seconds for
port 8787 to close, then kills as a last resort. It also creates a per-launch
instance tag echoed by `/health`, so the webview can reject another process on
8787, and exposes a folder opener restricted to this app's data directory.

- Run it with `just dev-app`. The debug build keeps the console; output is
  `eprintln!`, no `RUST_LOG`.
- Lint it with `just check-tauri`: **after** `just build-sidecar`.
  `tauri-build` validates `externalBin` on every cargo invocation, clippy
  included, so with an empty `binaries/` it fails on a missing resource before
  linting a line. This order looks wrong and is pinned by a test.
- Set a key in the desktop app's **Settings > Keys**, then quit and reopen.
  This section is unavailable in a browser. The keychain service is
  `dev.agentspace.desktop`; Windows Credential Manager uses an address like
  `<name>.dev.agentspace.desktop`, and macOS uses the service plus the key
  name as account. Do not place key values in command arguments.
- On macOS a rebuilt ad-hoc-signed app can prompt for keychain access again.
  **Always Allow** trusts the current binary. **Deny** omits that key from
  the handshake and logs `[keychain] could not read <name>: ...`; a missing
  entry is the only read error silently treated as unset.
- To check the handshake, look for `[keychain] sending 1 key(s)` followed by
  the sidecar's `received 1 secret(s)`. These logs contain names and counts,
  not values. A keychain denial is observable in the Rust stderr log even
  though the settings screen sees only that the key did not arrive.
- Orphan check after any shutdown change: close the window, then confirm no
  `agentspace-sidecar` process survives and 8787 is released.
  - **Windows:** `Get-Process agentspace-sidecar` and
    `netstat -ano | findstr :8787`.
  - **macOS:** `pgrep -f agentspace-sidecar` and `lsof -ti tcp:8787`.
  - With `--onefile` there are *two* sidecar processes while running
    (bootloader + interpreter) and the PID the shell holds is the
    bootloader's.
- `SECRET_NAMES` in `lib.rs` and `SECRET_KEYS` in `secrets.py` are one list in
  two languages; `test_secrets.py` reads the Rust source and compares.

---
