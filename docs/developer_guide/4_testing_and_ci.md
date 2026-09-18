# Testing and CI

## Tests

```
just test                                   # both suites
just test-backend                           # pytest
just test-backend tests/test_sandbox.py -k symlink -v
just test-backend-cov                       # with --cov=agentspace term-missing
just test-desktop                           # vitest run
just test-desktop src/state/reducer.test.ts
```

Backend tests are async on **anyio's** pytest plugin (asyncio backend only),
with a **60-second per-test timeout**: a stream that never terminates fails
instead of hanging CI. An autouse fixture points `AGENTSPACE_DATA_DIR` at
`tmp_path`, so no test can touch a real data directory even if it forgets to
pass paths.

### The doubles: `tests/support.py`

| Name | What it is for |
|---|---|
| `ScriptedProvider([...])` | A `Provider` that returns a fixed list of completions, on both `complete` and `stream`. Raises if asked for more than scripted. Records every request, system prompt and offered tool list. |
| `says(text, *calls)` | Builds one scripted `Completion`; `call("write_file", path=..., content=...)` builds a `ToolCall`. |
| `StandingAnswer(service, approve=…)` | Answers every approval the instant it is raised, **through the real gate**: the row is written and both events fire. Not a fake service. |
| `FakeClock` | Deterministic deadlines for the wall-clock limit. |
| `tool_runtime(...)` | A `ToolRuntime` rooted at a temp sandbox. |
| `reconstruct(events)` | A Python reducer used to check that the log alone reconstructs a run. Other tests also assert directly on event rows and persisted state. |

`RunLauncher.provider` is the override hook: a test passes a
`ScriptedProvider` and every agent in the run uses it, still wrapped in
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

For a critical guarantee, a targeted mutation can show whether its test notices
the intended failure: temporarily **break the guarantee** and confirm the test
fails, then restore it. The [project history](../history/README.md) records
these, including one where the first mutation was too small and the suite
stayed green while the thing supposedly under test had not been removed. A
mutation that does not fail is not evidence the code is right.

### Tests that skip, and why

`test_sidecar_binary.py`, `test_installer_bundle.py` and `test_macos_dmg.py`
inspect built artefacts and skip when prerequisites are absent: right for
`just test`, wrong for a
release. `just verify-build` passes `--require-build-checks`, which turns each
skip into a failure naming what was missing. `test_installed_app.py` **installs
software** and only runs under `--install-smoke` (`just verify-installed`); it
does not install anything during ordinary `just test` runs. Platform-specific
checks also skip on the other host. On macOS, `just build-installer` produces
the disk image the check mounts, so nothing runs between it and
`just verify-build`.

The symlink-escape sandbox test runs on Windows rather than skipping: it falls
back to a directory junction, which needs no privilege and which
`Path.resolve` follows identically. A test that skips on the primary platform
is not coverage of it.

---

## CI

[`.github/workflows/build.yml`](../../.github/workflows/build.yml), on push to
`main`, on pull requests, on `v*` tags, and through manual dispatch:

```
test (windows, macos)  →  build (windows, macos)  →  smoke (windows)  →  release (tag only)
     just ci                just build-installer       just verify-installed   gh release create/edit
                            just verify-build
                            just check-tauri
                            upload installer / dmg
```

- **`build` has `needs: test`.** That one line is §5 Phase 9's requirement (a
  red test blocks the build), and `test_ci_workflow.py` asserts it, because
  deleting it breaks nothing visible.
- **Build, check and test commands live in `just` recipes.** The workflow also
  invokes setup/artifact actions and `gh` for publication; a test pins the test
  job to `just ci`.
- Test, build and Windows smoke jobs share `.github/actions/toolchain`.
- The build jobs upload `AgentSpace-windows-installer` and
  `AgentSpace-macos-app`. The latter is the disk image, one file, so artifact
  upload cannot strip the app's executable permissions.
- The macOS image check mounts the image, checks that it holds the app and an
  `Applications` link, copies the app out, checks its bundle version,
  executable modes and sidecar hash, then launches that sidecar.
  The Windows smoke job installs its downloaded NSIS artifact and starts the
  installed sidecar with Python removed from its environment.
- Only a `v*` tag creates a GitHub release, after build and smoke succeed.
  Both platform assets are attached, with notes loaded from
  `docs/releases/<version>.md`.
- `.dev/cache` is cached; `target/` deliberately is not.

To reproduce the applicable jobs locally, run these commands in order:

```
just ci
just build-installer
just verify-build
just check-tauri
```

`just verify-installed` additionally performs the Windows installation smoke
check on the current machine. Local checks do not replace the other platform's
CI run or a downloaded macOS app's Gatekeeper check.

---
