# Testing and CI

## Tests

```
just test                                   # both suites
just test-backend                           # pytest
just test-backend tests/test_sandbox.py -k symlink -v
just test-backend-cov                       # with --cov=agentbase term-missing
just test-desktop                           # vitest run
just test-desktop src/state/reducer.test.ts
just test-visual                            # workbench pages in Chromium and WebKit
just test-visual --update                   # rewrite the screenshot baselines
```

Backend tests use **anyio's** pytest plugin (asyncio only) with a **60-second
per-test timeout**, so hanging streams fail CI. An autouse fixture sets
`AGENTBASE_DATA_DIR` to `tmp_path`; tests cannot touch real data even when
they omit paths.

### The doubles: `tests/support.py`

| Name | What it is for |
|---|---|
| `ScriptedProvider([...])` | Fixed completions for `complete` and `stream`; rejects over-reads and records requests, prompts, and offered tools. |
| `says(text, *calls)` | One scripted `Completion`; `call("write_file", path=..., content=...)` makes a `ToolCall`. |
| `StandingAnswer(service, approve=…)` | Immediately answers through the real gate, writing the row and both events. |
| `FakeClock` | Deterministic wall-clock-limit deadlines. |
| `tool_runtime(...)` | `ToolRuntime` rooted in a temp sandbox. |
| `reconstruct(events)` | Python reducer that checks the log alone reconstructs a run; tests also inspect rows and persisted state. |

`RunLauncher.provider` lets a test supply `ScriptedProvider`; every agent still
uses `BudgetedProvider`, so tests cannot bypass the cap.

For a run test: script turns, launch, let `StandingAnswer` handle the gate,
then assert `reconstruct(store.read(...))`. See `test_orchestrator.py`,
`test_agent_registry.py`, and `test_approval_gate.py`.

### Write tests first for three modules

BUILD_SPEC §6 names the event store, budget ledger, and sandbox: "These three
are where silent bugs become expensive."

### Mutation-check your tests

For critical guarantees, deliberately **break the guarantee**, confirm its test
fails, then restore it. [Project history](../history/README.md) includes a
mutation too small to fail despite leaving the supposed target intact. A passing
mutation is not evidence of correctness.

### Visual tests: `just test-visual`

`vitest.browser.config.ts` runs `src/**/*.visual.tsx` in Vitest's browser
mode with the Playwright provider, in headless Chromium (close to WebView2)
and WebKit (close to WKWebView). `workbench/pages.visual.tsx` renders every
workbench page, compares it with a committed screenshot
(`workbench/__screenshots__/`) and runs axe on it; a serious or critical
finding fails the page.

- Baseline names carry the browser and the platform (`-chromium-darwin`),
  because fonts differ between operating systems. A platform with no
  baselines writes them on its first run and fails that run; commit them and
  run again.
- Every page is compared in light, and the pages in `DARK_TOO` also in dark.
  A run page (`layout: "fill"`) is captured at 1,100 by 720, as a window
  shows it; any other page (`"flow"`) at its whole height. Axe checks every
  page in both themes.
- A failed comparison leaves its actual and diff images in `.dev/visual/`.
  After an intended change, look at them, then `just test-visual --update`.
- The context is pinned to UTC and `en-US`, and animations end at once, so a
  screenshot never depends on the machine's settings or on timing.
- It is not part of `just ci` until Windows has baselines too.

`src/workbench/build.test.ts` builds the app in memory in the ordinary suite
and fails if anything from `workbench/`, `test/`, `design/` or `scripts/`
would ship.

### Fixture runs

`src/test/scenarios.ts` holds one run per shape the interface draws: policy
answers naming hosts, an open question, a sandbox refusal, a missed lookup,
a stuck worker, budget warnings, failed and cancelled runs, a chat origin, a
ghost handoff, and twelve and twenty agents. `scenarios.test.ts` holds each
to what it says it shows, `replayIdentity.test.tsx` compares live with
replay at several cursors of each, and the workbench and the visual tests
draw them. Add a scenario there when a new state needs drawing.

### Tests that skip, and why

`test_sidecar_binary.py`, `test_installer_bundle.py`, and `test_macos_dmg.py`
inspect built artifacts and skip without prerequisites: correct for `just test`,
wrong for releases. `just verify-build` uses `--require-build-checks` to turn
each skip into a named failure. `test_installed_app.py` **installs software**
only under `--install-smoke` (`just verify-installed`), never ordinary
`just test`. Platform checks skip on other hosts. On macOS, `just build-installer`
creates the image inspected by the immediately following `just verify-build`.

The Windows symlink-escape test uses a no-privilege directory junction, which
`Path.resolve` follows identically. Skipping the primary platform is not
coverage.

---

## CI

[`.github/workflows/build.yml`](../../.github/workflows/build.yml) runs on
`main` pushes, pull requests, `v*` tags, and manual dispatch:

```
test (windows, macos)  →  build (windows, macos)  →  smoke (windows)  →  release (tag only)
     just ci                just build-installer       just verify-installed   gh release create/edit
                            just verify-build
                            just check-tauri
                            upload installer / dmg
```

- **`build` has `needs: test`.** This §5 Phase 9 requirement blocks builds on
  red tests; `test_ci_workflow.py` asserts it.
- **Build, check, and test commands use `just` recipes.** The workflow also
  uses setup/artifact actions and `gh`; a test pins its test job to `just ci`.
- Test, build and Windows smoke jobs share `.github/actions/toolchain`.
- The build jobs upload `AgentBase-windows-installer` and
  `AgentBase-macos-app`. The latter is the disk image, one file, so artifact
  upload cannot strip the app's executable permissions.
- The macOS check mounts the image, verifies its app and `Applications` link,
  copies the app out, checks version/modes/sidecar hash, and launches the
  sidecar. Windows smoke installs the downloaded NSIS artifact and starts its
  sidecar with Python removed from the environment.
- Only `v*` tags create GitHub releases, after build and smoke. Both assets use
  notes from `docs/releases/<version>.md`.
- `.dev/cache` is cached; `target/` deliberately is not.

To reproduce the applicable jobs locally, run these commands in order:

```
just ci
just build-installer
just verify-build
just check-tauri
```

`just verify-installed` also performs the current machine's Windows install
smoke test. Local checks do not replace the other platform's CI or a downloaded
macOS app's Gatekeeper check.

---
