# CLAUDE.md

## Read this first

The full specification is [BUILD_SPEC.md](BUILD_SPEC.md). **Read it in full at the
start of every session.** This file is a pointer and a running log, not a summary
— when the two disagree, BUILD_SPEC.md wins.

## Current phase

**Phase 0 — Scaffold and cross-platform hygiene.** Complete.

**Phase 1 — Packaging spike.** Complete. A built NSIS installer installs
per-user, launches, reaches the sidecar, and leaves zero processes behind.

**Phase 2 — Event spine.** Complete. SQLite + migrations, `EventStore.append`
with atomic per-run `seq`, an `EventBus`, and a resumable SSE stream. Verified
against the acceptance criterion with a real `curl` client killed mid-stream —
and, separately, from inside the webview.

Next up: **Phase 3 — Providers, budget, keychain.** Do not start it before
re-reading BUILD_SPEC §5 Phase 3.

### What Phase 2 established, and how it was verified

**The gap-free guarantee is a property of the stream, not of the bus.** The bus
is an in-process hint that new rows exist; SQLite is the only authority. The SSE
stream keeps its own cursor and, on *any* anomaly — a sequence gap, a repeat, a
dropped buffer, a stale subscription — re-reads the range from the database
rather than reasoning about the cause. Two things make that necessary rather
than defensive:

- Appends commit inside `asyncio.to_thread` and can resume in either order, so
  events genuinely reach `publish` out of sequence under concurrency.
- Subscriber queues are bounded. A wedged client is marked stale and its buffer
  dropped, because the durable row makes the buffered copy worthless.

Subscribe happens *before* the backlog read. The reverse order silently drops
anything appended in between, and is invisible until the log is under load.

**`seq` is assigned inside one SQL statement** (`SELECT MAX(seq)+1` within the
`INSERT`, under `BEGIN IMMEDIATE`, with `UNIQUE(run_id, seq)` behind it), so
atomicity is a database property rather than something application locking has
to maintain. This was confirmed by mutation: rewriting the append as a
read-then-write race makes
`test_concurrent_appends_produce_a_gapless_sequence` fail, and the UNIQUE
constraint fires as the second line of defence.

**Migration 001 creates only `runs` and `events`.** §4 specifies three more
tables; they arrive in the phases that use them. A migration runner whose
second step never executes before release is untested machinery, so
`test_store_db.py` applies a synthetic migration 002 to prove stepping and
rollback-on-failure work.

### The bug worth remembering (Phase 2)

**A named SSE event never fires `EventSource.onmessage`.** Frames originally
carried `event: llm.token`, which is the more idiomatic-looking SSE. A webview
probe using `onmessage` then received **0 of 20** events while `fetch` against
the same endpoint received all 20 — the server was blameless and every terminal
test was green.

Named events require `addEventListener` for that exact name, so any type the
client has not registered is dropped with no error anywhere. With 26 event types
and more arriving each phase, that converts "someone forgot to update the
client" into invisible data loss in a UI whose entire contract is being a
faithful projection of the event log. Frames are therefore **unnamed**; the type
travels inside the JSON body, everything arrives on one `onmessage`, and an
unrecognised type reaches the reducer where it can be logged loudly.

This is the same lesson as Phase 1's CORS bug in a new costume: the failure was
invisible from a terminal and obvious from inside the webview. `curl` satisfied
the acceptance criterion perfectly while the webview received nothing.

**CORS is now asserted, not assumed.** `test_stream_cors.py` covers the packaged
app's `http://tauri.localhost` origin directly, including the preflight for
`Last-Event-ID` — which matters because the *initial* EventSource connection is
a simple GET and is not preflighted, while the *reconnect* is. Getting that
wrong yields a stream that works once and then dies silently at the first
resume, which from the UI is indistinguishable from a run that stopped emitting.

### What Phase 1 established, and how it was verified

Four traps from §5 Phase 1, each now covered by a test rather than a comment:

- **The `externalBin` filename is asymmetric.** The file in `binaries/` must
  carry the target triple (`agentspace-sidecar-x86_64-pc-windows-msvc.exe`) or
  Tauri never resolves it — but Tauri *strips* that triple when staging and
  installing, so the shipped file is `agentspace-sidecar.exe`. Looking for the
  built name inside the installer finds nothing and looks exactly like a
  bundling failure. `bundled_name()` in `test_installer_bundle.py` encodes both
  halves.
- **The orphaned sidecar.** `--onefile` means the PID Tauri holds is the
  bootloader's, not the server's. Shutdown never relies on signals: the shell
  writes `shutdown` to stdin and drops the handle. Verified on the *installed*
  app — two `agentspace-sidecar` processes while running (bootloader + real
  interpreter), zero one second after closing the window, port released.
- **Stale cached sidecar in the bundle.** Not trusted to the build log:
  `test_installer_carries_the_freshly_built_sidecar` unpacks the installer with
  7-Zip and compares SHA-256 against the freshly built binary.
- **WebView2 on machines that lack it.** `webviewInstallMode` is
  `embedBootstrapper`, and a test asserts `MicrosoftEdgeWebview2Setup.exe` is
  physically inside the installer.

### The bug worth remembering

The packaged app once looked completely healthy and was not. The window
rendered, the sidecar bound in half a second, and an HTTP request from
PowerShell returned `{"ok": true}` — while the page sat retrying at attempt 22.
The webview does not share an origin with the sidecar (Tauri serves from
`http://tauri.localhost` on Windows), and FastAPI sent no CORS headers, so the
browser fetched successfully and discarded the response.

**curl and `Invoke-WebRequest` do not enforce CORS; a webview does.** A green
HTTP smoke test proves the server answered, not that the client was allowed to
read the answer. It surfaced only from screenshotting the running app and
reading the retry counter. When Phase 7 adds SSE, expect the same class of
problem and test it from inside the webview, not from a terminal.

`ALLOWED_ORIGINS` in `config.py` is an explicit allowlist and must stay one — a
wildcard would let any page the user has open read from their agent workspace.

### Not verified

- **A machine with no Python installed.** The frozen sidecar was run with a
  minimal environment and no Python on `PATH` and served correctly, but this
  machine has Python. Genuine proof needs a second machine, which is Phase 9's
  acceptance criterion.
- **macOS.** Nothing has run there. CI is Phase 9.
- **Reinstall-over-existing beyond one upgrade pass.** One `/S` reinstall over
  an existing install worked; repeated upgrade cycles are untested.

## The constraints that get violated by accident

Restated from BUILD_SPEC §1 because these are the ones a well-meaning refactor
erodes. The full list is in the spec.

- **No agent framework.** The orchestration loop is hand-written. Owning the
  event stream is the product.
- **No Docker / Postgres / Redis / LiteLLM in the shipped product.** Two
  sanctioned exceptions, neither of which changes what ships: the Phase 10
  reviewer demo, and the Phase 6 container wrapper around `run_shell` on the
  maintainer's own instance.
- **`127.0.0.1` is hardcoded.** `agentspace.config.BIND_HOST` is a `Final`
  constant and `assert_loopback_only()` guards every bind. There is a test that
  fails if this becomes configurable.
- **API keys live in the OS keychain.** Never `.env`, SQLite, a config file, a
  log line, or `argv` — they reach the sidecar over stdin at spawn time.
- **Every filesystem / shell / network tool call passes the approval gate.** No
  privileged path for any channel, including Discord and Telegram.
- **Chat channels trigger on explicit commands/mentions only.** Never ingest
  ambient channel messages into agent context.

And the idea the whole design hangs off (§2): **every agent action is an
append-only event row, and the UI is a pure projection of the event log.** If you
are about to send a message to the frontend that is not an event row, that is the
bug — fix it rather than working around it.

## Commands

Everything goes through `just` — there are no `.sh` or `.bat` files in this repo,
and a test enforces that.

```
just              # list every recipe
just setup        # install backend + frontend dependencies
just check        # lint + typecheck, both halves — the gate
just ci           # check + test
just test         # pytest
just fmt          # ruff format + eslint --fix
just versions     # resolved toolchain versions
```

## Layout

```
apps/backend    Python 3.12 FastAPI sidecar (uv, ruff, mypy --strict)
apps/desktop    React + TypeScript frontend (Vite, ESLint, tsc --noEmit)
.dev/           git-ignored: package caches + dev runtime data (see below)
```

## Where generated files go

Everything that grows lives inside the repository, so a clone on a roomy drive
does not fill the system drive. `just paths` prints the resolved locations.

| What | Where | How |
|---|---|---|
| Rust build output | `apps/desktop/src-tauri/target/` | default |
| Backend venv | `apps/backend/.venv/` | default |
| Frontend deps | `apps/desktop/node_modules/` | default |
| cargo registry | `.dev/cache/cargo/` | `CARGO_HOME`, exported by the justfile |
| uv cache | `.dev/cache/uv/` | `UV_CACHE_DIR` |
| npm cache | `.dev/cache/npm/` | `npm_config_cache` |
| Dev SQLite / logs / agent workspace | `.dev/data/` | `AGENTSPACE_DATA_DIR` |
| PyInstaller bootloader cache | `.dev/cache/pyinstaller/` | `PYINSTALLER_CONFIG_DIR` |
| Frozen sidecar binary | `apps/desktop/src-tauri/binaries/` | `--distpath` |

Tool *installations* deliberately stay on the system drive at their default
locations: rustup toolchains (`~/.rustup`), the rustup shims (`~/.cargo/bin`),
VS Build Tools, uv's Python builds, Node.

Two things to keep straight:

- The exports live in the justfile, so they apply to **this repository's recipes
  only**. Other projects on the machine keep using the shared machine-wide
  caches. The trade is that a package needed by both is downloaded twice; the
  point is containment of *this* project's growth, not a global saving.
- `AGENTSPACE_DATA_DIR` is a **dev-only** override. The shipped application still
  resolves the OS app-data dir via `agentspace.config.default_data_dir`, as
  BUILD_SPEC §5 Phase 2 requires. Do not change that default to match the dev
  path — the end user has no repository.

`packages/schemas/` (generated TS types) arrives in Phase 7. It is absent rather
than stubbed, because BUILD_SPEC §5 says do not build ahead.

The backend now also holds `store/` (SQLite + migrations), `events/` (types,
store, bus) and `api/` (runs, stream), per the §3 layout.

## Decisions made mid-build

Recorded here as they happen, so a later session does not re-litigate them.

- **2026-09-09 — the data directory is derived from the bundle identifier, not
  `APP_NAME`.** Tauri's per-user NSIS installer installs into
  `%LOCALAPPDATA%\<productName>` — `%LOCALAPPDATA%\AgentSpace` — which is
  byte for byte where an `APP_NAME`-derived data directory resolved. The event
  log would have lived *inside the installation*, to be deleted by an uninstall
  and put at risk by every upgrade. Found empirically: a stray
  `agentspace.sqlite3` turned up in the installed app's own directory. It now
  resolves to `%LOCALAPPDATA%\dev.agentspace.desktop`, which is also exactly
  what Tauri's `app_data_dir()` returns, so the injected value and the fallback
  name the same place instead of differing by one directory. A test asserts the
  identifier still matches `tauri.conf.json`.
- **2026-09-09 — an autouse fixture isolates every test's data directory.**
  The stray database above was written *by the test suite*: `create_app()` with
  no explicit paths falls back to the real OS app-data directory, so any test
  building an app without passing paths wrote to the developer's machine.

- **2026-09-09 — migration 001 creates only `runs` and `events`.** §4 specifies
  five tables. Creating `spend`, `agent_defs` and `approvals` now would satisfy
  the data model in one step but leave the migration runner with exactly one
  migration, forever — the second step would first execute on a user's machine
  during an upgrade. They arrive in Phases 3, 5 and 6 as migrations 002+.
- **2026-09-09 — SSE frames carry no `event:` field.** See "The bug worth
  remembering (Phase 2)". The type is in the JSON body; a named SSE event would
  silently bypass `onmessage` for any type the client had not registered.
- **2026-09-09 — one SQLite connection behind a `threading.Lock`, not a
  connection per thread.** Thread-local connections scale better and are wrong
  here: pool-thread connections are never deterministically closed, and on
  Windows an open handle keeps the database file locked, which breaks both test
  teardown and installer replacement. Operations are sub-millisecond and every
  async caller arrives via `asyncio.to_thread`, so the loop never blocks.
- **2026-09-09 — the Tauri shell defers to an inherited `AGENTSPACE_DATA_DIR`.**
  §5 Phase 2 asks for the data directory to come from Tauri's path API, and it
  does — but only when the variable is unset. Overriding unconditionally would
  have moved dev state out of `.dev/data` and quietly contradicted the layout
  table above.
- **2026-09-09 — `pytest-timeout` with a 60 s cap.** An SSE stream that fails to
  terminate hangs the suite instead of failing it, and would hang the Phase 9 CI
  job. It earned its place immediately: it caught a real defect where a client
  resuming past the head of an already-completed run waited forever, because the
  stream only learned a run was over by *seeing* its terminal event. The stream
  now also checks the run's status.
- **2026-09-09 — Vite's dev watcher ignores `src-tauri/**`.** `tauri dev` runs
  cargo and Vite against the same tree; Vite's watcher opens `target/` files
  while cargo is still writing them, and on Windows the resulting EBUSY is
  raised as a fatal error that kills the dev server and takes `tauri dev` with
  it. Nothing under there is a frontend source file.

- **2026-09-09 — `eslint-plugin-import-x` instead of `eslint-plugin-import`.**
  Phase 0 requires a lint rule enforcing case-sensitive import paths. The
  canonical `eslint-plugin-import@2.32.0` caps its ESLint peer at 9 and will not
  install against the ESLint 10 in this tree; its companion
  `eslint-import-resolver-typescript` drags it back in as an optional peer.
  `eslint-plugin-import-x` is the maintained fork, supports ESLint 10, ships the
  same `no-unresolved` rule with `caseSensitiveStrict`, and bundles
  `createNodeResolver` so the TypeScript resolver is not needed at all.
- **2026-09-09 — `just check` depends on `just setup`.** The Phase 0 acceptance
  criterion is that `check` passes *on a clean clone*, which it cannot do if the
  venv and `node_modules` are missing. Both installers are no-ops when the trees
  are already in sync.
- **2026-09-09 — per-recipe `[working-directory(...)]` instead of `cd &&`.**
  `&&` is a parser error in Windows PowerShell 5.1, so chained-directory recipes
  would be shell-specific. Every recipe body is a single command instead.
- **2026-09-09 — generated files redirected into `.dev/` via justfile exports.**
  The system drive had 16 GB free and a Tauri `target/` directory alone can
  reach 5-10 GB. Rather than edit shell profiles or move tool installations,
  the justfile exports `CARGO_HOME`, `UV_CACHE_DIR`, `npm_config_cache` and
  `AGENTSPACE_DATA_DIR` into the working tree. Verified by wiping `.venv`,
  `node_modules` and `.dev`, re-running `just check`, and confirming a
  `cargo build` of a crate with a dependency put `anyhow` in
  `.dev/cache/cargo/registry/` while `~/.cargo/` kept only `bin`.
  Side benefit: the uv cache now sits on the same volume as the venv, so uv
  hardlinks instead of copying — the "Failed to hardlink files; falling back to
  full copy" warning is gone.
- **2026-09-09 — CORS allowlist rather than a Tauri HTTP proxy.** The webview
  reaching the sidecar over plain `fetch` needs CORS headers. The alternative
  was routing every call through a Rust command. Direct `fetch` keeps the
  frontend ordinary — which matters when Phase 7 needs `EventSource` for SSE,
  something a Rust proxy would have to reimplement.
- **2026-09-09 — Tauri bundler tools stay on the system drive.** `tauri build`
  downloads NSIS and the WebView2 bootstrapper into `%LOCALAPPDATA%	auri`
  (8.5 MB, one-time). Tauri resolves that path through `dirs::cache_dir()` with
  no override, so unlike the cargo/uv/npm caches it cannot be redirected into
  `.dev/`. Small enough to accept; recorded so nobody re-investigates.
- **2026-09-09 — `.dev` added to the hygiene test's pruned directories.**
  Package caches contain vendored `.sh` files, which would have failed
  `test_no_shell_or_batch_scripts` for reasons unrelated to this repository, and
  walking gigabytes of cache would make the suite slow enough to stop being run.
  A test asserts the walker never descends into `.dev`.
