# Development Setup

## Toolchain

[`just`](https://just.systems) drives every task. The repository forbids `.sh`
and `.bat` files; a test enforces this.

| Tool | Version | Needed for | Notes |
|---|---|---|---|
| `just` | any recent | everything | |
| [`uv`](https://docs.astral.sh/uv/) | any recent | backend | Fetches Python 3.12; do not install it separately. |
| Node | `26.x` (see [`.nvmrc`](../../.nvmrc)) | frontend | `nvm use` reads it. |
| Rust via `rustup` | stable; manifest minimum 1.77.2 | `just dev-app`, `just build-installer`, `just check-tauri` | Not needed for backend/browser development, `just check`, or `just test`. |
| Visual Studio Build Tools, *Desktop development with C++* | | Rust on Windows | MSVC linker; unnecessary on macOS. |
| Xcode Command Line Tools | | Rust on macOS | Install with `xcode-select --install`; unnecessary on Windows. |
| WebView2 runtime | | running the app on Windows | Preinstalled on Windows 11; macOS uses system WebKit. |
| [7-Zip](https://7-zip.org) | | `just verify-build` (Windows) | Unpacks NSIS to compare its sidecar; unnecessary on macOS. |

`just versions` prints what it finds. Python is **3.12 exactly**: `discord.py`
imports `audioop`, which 3.13 removes.

**Caches and development data stay in the repository.** The justfile exports
`CARGO_HOME`, `UV_CACHE_DIR`, `npm_config_cache`, `PYINSTALLER_CONFIG_DIR`, and
`AGENTBASE_DATA_DIR` under git-ignored `.dev/`; `just paths` shows the resolved
locations. These exports apply **only to `just` recipes**. Set them manually
when [running the backend](#backend--ui-in-a-browser-the-fast-loop) or inspecting
[development data](#the-dev-data-directory). Tool installations, including
uv-managed Python and Rust, remain in their usual system locations.

## From clone to green

```
git clone https://github.com/Zocke07/AgentBase
cd AgentBase
just setup     # uv sync + npm install
just check     # ruff, format check, mypy twice, eslint, tsc
just test      # pytest + vitest
```

`just ci` runs `check` then `test`, as CI does; `check` depends on `setup`, so
it works from a clean clone. Run it before pushing.

The backend typecheck runs natively and for the other supported platform:
`mypy --platform darwin` on Windows, `mypy --platform win32` on macOS. mypy
otherwise prunes the non-host branch of `sys.platform` conditionals, hiding
platform-specific errors. `just fmt` applies Ruff formatting and safe fixes
and ESLint fixes.

---

## Running it

Choose the loop that matches your change.

### Backend + UI in a browser: the fast loop

No Rust or freeze step; use two terminals for instant reloads.

**Terminal 1: source sidecar.** No `just` recipe sets its data directory, so
set it manually to avoid writing to the real app-data directory
(`%LOCALAPPDATA%\dev.agentbase.desktop` on Windows,
`~/Library/Application Support/dev.agentbase.desktop` on macOS):

<details open>
<summary>Windows (PowerShell)</summary>

```powershell
cd apps\backend
$env:AGENTBASE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run python -m agentbase
```
</details>

<details>
<summary>macOS / Linux (zsh / bash)</summary>

```bash
cd apps/backend
export AGENTBASE_DATA_DIR="$(git rev-parse --show-toplevel)/.dev/data"
uv run python -m agentbase
```
</details>

It binds `127.0.0.1:8787`, migrates, and logs to the terminal. **stdin is its
control channel:**

- The **first line** you type is the API-key handshake. To give it a key
  without touching the keychain, type a JSON object and press Enter:

  ```
  {"anthropic_api_key": "<your key>"}
  ```

  Logs show the name, never the value: `received 1 secret(s): anthropic_api_key`.
  `{}` is a valid empty handshake. Tauri uses this same path.
- Typing `shutdown` and Enter stops it cleanly. So does **Ctrl+C**, and so
  does **EOF**: `< NUL` (Windows), `< /dev/null` (macOS/Linux), or a closed
  pipe stops it immediately. Keep stdin open in scripts.
- `AGENTBASE_PORT=8790` moves the port (1024–65535). The Tauri shell does not
  read this (it pins 8787), so it is only useful for a second, source-run
  sidecar.

**Terminal 2: the frontend:**

```
just dev-desktop
```

Vite serves `127.0.0.1:5173` (strict port). Use **Edge** on Windows (WebView2)
or **Safari** on macOS (system WebKit). Outside Tauri, it uses
`http://127.0.0.1:8787`; `ALLOWED_ORIGINS` includes both `127.0.0.1:5173` and
`localhost:5173`.

To point the tab at a sidecar on another port, start Vite with
`VITE_AGENTBASE_SIDECAR_PORT` set (for example `8790`). Only the dev server
reads it, only the port moves, and a production build ignores it
(`lib/sidecar.ts`).

<details>
<summary>Hot reload for the backend (Windows: PowerShell)</summary>

`run()` does not use uvicorn's reloader, but `create_app` is a factory, so:

```powershell
cd apps\backend
$env:AGENTBASE_DATA_DIR = "$(git rev-parse --show-toplevel)\.dev\data"
uv run uvicorn agentbase.main:create_app --factory --host 127.0.0.1 --port 8787 --reload --reload-dir src
```

This loses the stdin handshake (fine for keyless Ollama) and watchdog.
**Stop it with Ctrl+C in that terminal.** Its worker holds the socket; killing
the parent from Task Manager or `taskkill` can leave 8787 occupied. See
[Gotchas](1_architecture.md#gotchas).
</details>

<details>
<summary>Hot reload for the backend (macOS / Linux: zsh / bash)</summary>

```bash
cd apps/backend
export AGENTBASE_DATA_DIR="$(git rev-parse --show-toplevel)/.dev/data"
uv run uvicorn agentbase.main:create_app --factory --host 127.0.0.1 --port 8787 --reload --reload-dir src
```

This loses the stdin handshake (fine for keyless Ollama) and watchdog.
**Stop it with Ctrl+C in that terminal.** Killing only its parent (for example
with Activity Monitor or `kill`) can leave the worker and port 8787 alive. See
[Gotchas](1_architecture.md#gotchas).
</details>

### The interface without a sidecar: `just workbench`

`just workbench` opens `workbench.html` on the dev server: the colour tokens
with each listed pair's contrast ratio, the type in use, the shared controls
in their states, the rail, and the run view for every scenario in
`src/test/scenarios.ts`. A run page has a cursor, playback from 1x to 8x,
single steps, and a switch between events arriving live and a replayed log.
The bar's switches set the theme, reduced motion and the platform, and the
page, its conditions and a run page's cursor are in the link, so
`workbench.html?page=run-shell-question&theme=dark&cursor=12` opens that
state. Nothing in it calls the sidecar, and the app's build does not include
it. Add a page in `src/workbench/pages.tsx`; the visual tests pick it up.

Scenarios are written from made-up content. Never copy a log from `.dev/data`
or an installed app's data into a fixture or a screenshot: the default space
holds a person's portfolio.

### Screenshots of the real app: `just ui-shots`

```
just ui-shots before             # every section, both themes, three window sizes
just ui-shots after --reuse      # again, on the same scratch data and clock
just ui-shots --compare before after
```

The script starts a scratch sidecar on port 8790 with its data under
`.dev/shots/.scratch`, seeds made-up notes and the scripted debug run, starts
Vite on 5173 and drives headless Chromium. PNGs land in
`.dev/shots/<label>/`. Stop any dev server or dev app first: the sidecar's
CORS list names port 5173 alone, so Vite cannot move. The browser's clock is
pinned and every animation ends at once, so `--reuse` gives the same bytes
for the same code, and `--compare` proves that a change is invisible. For a
screenshot that differs it says how many pixels, by how much and where. A
few pixels changed by a level or two on a control's rounded corner is the
browser's rasteriser, seen once in eight captures; capture again to settle
it. The sidecar's own clock is not pinned, so capture both sets in the same
month. The first use downloads Chromium and WebKit into
`.dev/cache/playwright` (`just setup-browsers`).

### The whole app: `just dev-app`

```
just dev-app
```

Runs `just build-sidecar` (PyInstaller; one or two minutes), then `tauri dev`:
Vite, the debug Rust shell, its window, and **the frozen sidecar** from
`src-tauri/binaries/`. Use it for shell-owned behavior: the keychain handshake,
data-directory injection, startup/shutdown, and `tauri.localhost` origin.

Consequences of "the frozen sidecar":

- A backend change needs `just build-sidecar` again (or re-run `dev-app`).
  Vite hot-reloads the frontend as usual.
- The shell reads **your real OS keychain**: entries under service
  `dev.agentbase.desktop`. A dev run with a key stored there uses it. The
  terminal shows `[keychain] sending N key(s): [...]`.
- The data directory is `.dev/data`: `just` exports `AGENTBASE_DATA_DIR`, and
  the shell accepts an inherited value.
- The debug build keeps a console: every sidecar line arrives prefixed
  `[sidecar]`. On Windows, right-click → **Inspect** opens WebView2 devtools;
  macOS uses WebKit's inspector.

### The installed app

`just build-installer`, then run the produced bundle:

- **Windows:** the `.exe` from `apps/desktop/src-tauri/target/release/bundle/nsis/`.
- **macOS:** the `.app` from `apps/desktop/src-tauri/target/release/bundle/macos/`.
  Open it with `open AgentBase.app` or double-click in Finder.

See [Packaging](6_packaging.md) for bundle checks and the macOS archive.
An installed launch exercises the default data directory, packaged origin, and
upgrade path; [project history](../history/README.md) records bugs found only
there.

**Only one thing can hold 8787.** The installed app, `dev-app`, and a
source-run sidecar all bind it. Close the installed app before developing.

---

## The dev data directory

Every `just` recipe, including the Tauri shell under `dev-app`, uses `.dev/data/`:

```
.dev/data/
  agentbase.sqlite3      runs, events, spend, settings, spaces, agent_defs, approvals
  agentbase.sqlite3-wal  (WAL mode: readers never block the writer)
  spaces/
    <default-space-id>/    Main's sandbox folder
    <space-id>/           each additional space's sandbox folder
  logs/                   created, currently unused
```

Migration 006 assigns legacy runs and definitions to Main (`DEFAULT_SPACE_ID`
in `store/spaces.py`). Startup adopts legacy `workspace/` into
`spaces/<default-space-id>/`; new installs use the spaces layout. Each run
resolves tools only within its own space folder.

For a fresh-install check, set a separate temporary `AGENTBASE_DATA_DIR` and
preserve needed development files. Deleting `.dev/data` removes its history
and space files; the next launch migrates and recreates Main with its built-in
roster. `just clean-dev` also removes package caches; `just clean` removes all
git-ignored files, including `.venv`, `node_modules`, and `target/`.

WAL makes reads safe while the app runs. No `sqlite3` CLI is required; use the
interpreter:

<details open>
<summary>Windows (PowerShell)</summary>

```powershell
cd apps\backend
uv run python -c "import sqlite3; c = sqlite3.connect('../../.dev/data/agentbase.sqlite3'); print(c.execute('PRAGMA user_version').fetchone()); [print(r) for r in c.execute('SELECT seq, agent_id, type FROM events WHERE run_id = (SELECT id FROM runs ORDER BY created_at DESC LIMIT 1) ORDER BY seq')]"
```
</details>

<details>
<summary>macOS / Linux (zsh / bash)</summary>

```bash
cd apps/backend
uv run python -c "import sqlite3; c = sqlite3.connect('../../.dev/data/agentbase.sqlite3'); print(c.execute('PRAGMA user_version').fetchone()); [print(r) for r in c.execute('SELECT seq, agent_id, type FROM events WHERE run_id = (SELECT id FROM runs ORDER BY created_at DESC LIMIT 1) ORDER BY seq')]"
```
</details>

`settings` stores JSON key/value pairs. `secrets` are never stored there.

---
