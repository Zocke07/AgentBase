# Development Setup

## Toolchain

Everything is driven through [`just`](https://just.systems). There are no `.sh`
or `.bat` files in the repository and a test fails if one appears.

| Tool | Version | Needed for | Notes |
|---|---|---|---|
| `just` | any recent | everything | |
| [`uv`](https://docs.astral.sh/uv/) | any recent | backend | Fetches Python 3.12 itself; do not install Python for this. |
| Node | `26.x` (see [`.nvmrc`](../../.nvmrc)) | frontend | `nvm use` reads the file. |
| Rust via `rustup` | stable; manifest minimum 1.77.2 | `just dev-app`, `just build-installer`, `just check-tauri` | Not needed for the backend, the browser dev loop, `just check` or `just test`. |
| Visual Studio Build Tools, *Desktop development with C++* | | Rust on Windows | The MSVC linker. Not needed on macOS. |
| Xcode Command Line Tools | | Rust on macOS | `xcode-select --install`. Provides the Apple linker and system headers. Not needed on Windows. |
| WebView2 runtime | | running the app on Windows | Preinstalled on Windows 11. macOS uses the system WebKit: no extra install. |
| [7-Zip](https://7-zip.org) | | `just verify-build` (Windows) | Unpacks the NSIS installer to compare the sidecar inside it. Not needed on macOS: the macOS bundle is a `.app` directory, not an NSIS archive. |

`just versions` prints what it finds. Python is **3.12 exactly**: `discord.py`
imports `audioop`, which 3.13 removes.

**Package caches and development data stay inside the repository.** The
justfile exports `CARGO_HOME`, `UV_CACHE_DIR`, `npm_config_cache`,
`PYINSTALLER_CONFIG_DIR` and `AGENTSPACE_DATA_DIR` into a git-ignored `.dev/`,
so a clone on a roomy drive does not fill the system drive. `just paths` prints
the resolved locations. This applies **only inside `just` recipes**: a command
you run by hand does not get these exports, which matters when
[running the backend](#backend--ui-in-a-browser-the-fast-loop) or inspecting
[development data](#the-dev-data-directory). Tool installations, including
uv-managed Python and Rust toolchains, still use their normal system locations.

## From clone to green

```
git clone https://github.com/Zocke07/AgentBase
cd AgentBase
just setup     # uv sync + npm install
just check     # ruff, format check, mypy twice, eslint, tsc
just test      # pytest + vitest
```

`just ci` is `check` + `test`, exactly what the CI test jobs run. `check`
depends on `setup` so it works on a clean clone. Run `just ci` before pushing.

The backend typecheck runs natively and for the other supported platform:
`mypy --platform darwin` on Windows, `mypy --platform win32` on macOS. mypy
otherwise prunes the non-host branch of `sys.platform` conditionals, hiding
platform-specific errors. `just fmt` applies Ruff formatting and safe fixes
and ESLint fixes.

---

## Running it

There are three ways, and which one you want depends on what you are changing.

### Backend + UI in a browser: the fast loop

No Rust, no freeze step, instant reloads. Two terminals.

**Terminal 1: the sidecar from source.** There is no `just` recipe for this
yet, so set the data directory by hand or the sidecar writes to the *real*
app-data directory (`%LOCALAPPDATA%\dev.agentspace.desktop` on Windows,
`~/Library/Application Support/dev.agentspace.desktop` on macOS):

<details open>
<summary>Windows (PowerShell)</summary>

```powershell
cd apps\backend
$env:AGENTSPACE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run python -m agentspace
```
</details>

<details>
<summary>macOS / Linux (zsh / bash)</summary>

```bash
cd apps/backend
export AGENTSPACE_DATA_DIR="$(git rev-parse --show-toplevel)/.dev/data"
uv run python -m agentspace
```
</details>

It binds `127.0.0.1:8787`, applies migrations, and logs to the terminal.
**The terminal is its stdin, and stdin is the control channel:**

- The **first line** you type is the API-key handshake. To give it a key
  without touching the keychain, type a JSON object and press Enter:

  ```
  {"anthropic_api_key": "<your key>"}
  ```

  The log says `received 1 secret(s): anthropic_api_key`: the name, never
  the value. `{}` is a valid empty handshake. This is how the Tauri shell
  delivers keys too, so you are exercising the real path.
- Typing `shutdown` and Enter stops it cleanly. So does **Ctrl+C**, and so
  does **EOF**: which means `< NUL` (Windows), `< /dev/null` (macOS/Linux)
  or a closed pipe stops it immediately. If you script it, keep stdin open.
- `AGENTSPACE_PORT=8790` moves the port (1024–65535). The Tauri shell does not
  read this (it pins 8787), so it is only useful for a second, source-run
  sidecar.

**Terminal 2: the frontend:**

```
just dev-desktop
```

Vite serves on `127.0.0.1:5173` (strict port). Open it in **Edge** on
Windows (that is WebView2's engine, so what you see is what the packaged app
sees) or **Safari** on macOS (the system WebKit). Outside Tauri the page
falls back to `http://127.0.0.1:8787` for the sidecar, and both
`127.0.0.1:5173` and `localhost:5173` are in `ALLOWED_ORIGINS`.

<details>
<summary>Hot reload for the backend (Windows: PowerShell)</summary>

`run()` does not use uvicorn's reloader, but `create_app` is a factory, so:

```powershell
cd apps\backend
$env:AGENTSPACE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run uvicorn agentspace.main:create_app --factory --host 127.0.0.1 --port 8787 --reload --reload-dir src
```

You lose the stdin handshake (no keys: fine for Ollama) and the watchdog.
**Stop it with Ctrl+C in that terminal.** The reloader is a parent process
with a spawned worker holding the socket; killing the parent from Task Manager
or `taskkill` can leave the worker alive and 8787 taken. See
[Gotchas](1_architecture.md#gotchas).
</details>

<details>
<summary>Hot reload for the backend (macOS / Linux: zsh / bash)</summary>

```bash
cd apps/backend
export AGENTSPACE_DATA_DIR="$(git rev-parse --show-toplevel)/.dev/data"
uv run uvicorn agentspace.main:create_app --factory --host 127.0.0.1 --port 8787 --reload --reload-dir src
```

You lose the stdin handshake (no keys: fine for Ollama) and the watchdog.
**Stop it with Ctrl+C in that terminal.** The reloader is a parent process
with a spawned worker holding the socket; killing only the parent (e.g. via
Activity Monitor or `kill`) can leave the worker alive and 8787 taken. See
[Gotchas](1_architecture.md#gotchas).
</details>

### The whole app: `just dev-app`

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
- The shell reads **your real OS keychain**: entries under service
  `dev.agentspace.desktop`. A dev run with a key stored there uses it. The
  terminal shows `[keychain] sending N key(s): [...]`.
- The data directory is `.dev/data`, because `just` exports
  `AGENTSPACE_DATA_DIR` and the shell defers to an inherited value.
- The debug build keeps a console: every sidecar line arrives prefixed
  `[sidecar]`. On Windows, right-click → **Inspect** opens WebView2 devtools;
  macOS uses WebKit's inspector.

### The installed app

`just build-installer`, then run the produced bundle:

- **Windows:** the `.exe` from `apps/desktop/src-tauri/target/release/bundle/nsis/`.
- **macOS:** the `.app` from `apps/desktop/src-tauri/target/release/bundle/macos/`.
  Open it with `open AgentSpace.app` or double-click in Finder.

See [Packaging](6_packaging.md) for bundle checks and the macOS archive.
An installed launch exercises the default data directory, packaged origin
and upgrade path. Several previous bugs were found only by installing and
looking; the [project history](../history/README.md) records those results.

**Only one thing can hold 8787.** The installed app, `dev-app`, and a
source-run sidecar all bind it. Close the installed app before developing.

---

## The dev data directory

`.dev/data/` is what every `just` recipe (and the Tauri shell under
`dev-app`) uses:

```
.dev/data/
  agentspace.sqlite3      runs, events, spend, settings, spaces, agent_defs, approvals
  agentspace.sqlite3-wal  (WAL mode: readers never block the writer)
  spaces/
    <default-space-id>/    Main's sandbox folder
    <space-id>/           each additional space's sandbox folder
  logs/                   created, currently unused
```

Migration 006 assigns old runs and definitions to Main, whose fixed UUID is
`DEFAULT_SPACE_ID` in `store/spaces.py`. On startup an existing legacy
`workspace/` is adopted into `spaces/<default-space-id>/`;
new installs use the spaces layout directly. Each run resolves tools against
its own space's folder, not the whole `spaces/` directory.

For a fresh-install check, use a separate temporary `AGENTSPACE_DATA_DIR` and
retain any development files you need. Deleting `.dev/data` removes all its
history and space files; migrations then recreate Main and its three built-in
agents at next launch. `just clean-dev` deletes it along with the package
caches; `just clean` deletes every git-ignored file including `.venv`,
`node_modules` and `target/`.

Reading the database while the app runs is safe (WAL). There is no `sqlite3`
CLI dependency; use the interpreter:

<details open>
<summary>Windows (PowerShell)</summary>

```powershell
cd apps\backend
uv run python -c "import sqlite3; c = sqlite3.connect('../../.dev/data/agentspace.sqlite3'); print(c.execute('PRAGMA user_version').fetchone()); [print(r) for r in c.execute('SELECT seq, agent_id, type FROM events WHERE run_id = (SELECT id FROM runs ORDER BY created_at DESC LIMIT 1) ORDER BY seq')]"
```
</details>

<details>
<summary>macOS / Linux (zsh / bash)</summary>

```bash
cd apps/backend
uv run python -c "import sqlite3; c = sqlite3.connect('../../.dev/data/agentspace.sqlite3'); print(c.execute('PRAGMA user_version').fetchone()); [print(r) for r in c.execute('SELECT seq, agent_id, type FROM events WHERE run_id = (SELECT id FROM runs ORDER BY created_at DESC LIMIT 1) ORDER BY seq')]"
```
</details>

The `settings` table is key/value with JSON values; the `secrets` are **not**
in it and never will be.

---
