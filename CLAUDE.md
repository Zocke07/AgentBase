# CLAUDE.md

## Read this first

The full specification is [BUILD_SPEC.md](BUILD_SPEC.md). **Read it in full at the
start of every session.** This file is a pointer and a running log, not a summary
— when the two disagree, BUILD_SPEC.md wins.

## Current phase

**Phase 0 — Scaffold and cross-platform hygiene.** Complete; `just check` passes
on a clean clone.

**Phase 1 — Packaging spike.** In progress. The sidecar half is done and
verified; the Tauri bundle half is being built.

The two Phase 1 traps that are already handled and tested:

- **The `externalBin` filename.** Tauri resolves `binaries/agentspace-sidecar`
  on disk as `agentspace-sidecar-<target triple>.exe`. Anything else is silently
  not found at bundle time. The triple is computed once in the justfile from
  `os()`/`arch()`, and `test_target_triple_matches_the_justfile` asserts the
  Python side agrees — including the macOS rows, which only CI can execute.
- **The orphaned sidecar.** `--onefile` means the PID Tauri holds is
  PyInstaller's bootloader, not the server. Shutdown therefore never relies on
  signals: the shell writes `shutdown` to stdin and then drops the handle,
  closing the pipe. `agentspace.main._stop_on_stdin_close` stops the server on
  either signal, from inside the process that really is the server.
  `test_closing_stdin_leaves_no_orphan_process` asserts zero survivors.

Still to verify before Phase 1 can be called done: the NSIS installer builds,
installs per-user, launches, reaches the sidecar, and leaves nothing behind in
Task Manager on quit — plus that the sidecar inside the produced installer is
the freshly built one, not a stale cached copy.

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

`packages/schemas/` (generated TS types) and `apps/desktop/src-tauri/` arrive in
Phases 7 and 1 respectively. They are absent rather than stubbed, because
BUILD_SPEC §5 says do not build ahead.

## Decisions made mid-build

Recorded here as they happen, so a later session does not re-litigate them.

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
- **2026-09-09 — `.dev` added to the hygiene test's pruned directories.**
  Package caches contain vendored `.sh` files, which would have failed
  `test_no_shell_or_batch_scripts` for reasons unrelated to this repository, and
  walking gigabytes of cache would make the suite slow enough to stop being run.
  A test asserts the walker never descends into `.dev`.
