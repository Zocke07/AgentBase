# Verification and remaining work

Updated 2026-09-14. This is the current record; the
[historical session notes](history/README.md) retain earlier evidence and
superseded gaps. A test result below is scoped to what was actually executed.

## 0.2.1 macOS signing correction

The published 0.2.0 Mac archive reproduced the user's **damaged and can't be
opened** Gatekeeper error. `codesign --verify --deep --strict` showed that the
archive preserved executable modes but lacked a complete app-bundle signature.

Version 0.2.1 configures Tauri's ad-hoc identity and keeps hardened runtime
disabled. Enabling the runtime caused the re-signed PyInstaller sidecar to fail
while loading its extracted Python library because the process and mapped file
had different code identities. The release test now strips signatures from
temporary copies before checking sidecar content, verifies the complete bundle
signature, then launches the archived sidecar. The corrected local archive
passed all **15 applicable release checks**; four Windows-only checks skipped.
`AgentSpace_0.2.1_aarch64-apple-darwin.app.zip` is 24,185,918 bytes with local
SHA-256 `dc255ce360df9f4252180838b6479e666d979967373ceb32dd8d70a30fbbe28e`.

## 0.2.0 preparation

Documentation and local release preparation were completed before publication.
The [v0.2.0 release page](https://github.com/Zocke07/AgentBase/releases/tag/v0.2.0)
is the authority for publication status and downloadable artifacts. The tag
workflow is the authority for cross-platform CI results.

On Apple Silicon macOS, `just ci` passed with **734 backend tests and 313
frontend tests** after the documentation, version and Discord mention changes.
Ten backend tests skipped because their current build or platform prerequisite
was absent. The first run inside the managed command sandbox failed because it
blocked DNS and PyInstaller's System V semaphore; the same gate passed with
normal OS facilities.

`just build-installer`, `just package-macos`, `just verify-build` and
`just check-tauri` then passed. The build produced
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` (23 MB, SHA-256
`5cf8bdee4ab107b6b52b282da31b68acaacf4ca27248183e69f80fa5b99fe1af`).
Four Windows-only NSIS checks skipped on macOS; the other **14 release checks
passed**. They verified the bundle version and identifier, archived executable
modes and hashes, fresh database startup, HTTP health, and clean extracted
sidecar shutdown with Python removed from its environment. Rust Clippy passed.
The packaged Tauri window and a downloaded copy's Gatekeeper flow were not
opened in this session.

## Backend coverage baseline

`just test-backend-cov` ran on Apple Silicon macOS on 2026-09-13 before the
release changes: **733 passed, 8 skipped**, in **39.67 seconds**. Coverage was
**4,146 of 4,473 statements (92.69%, displayed as 93%)**. This does not measure
branch coverage, frontend code or Rust.

| Module | Statement coverage |
|---|---:|
| Event store | 100% |
| Budget ledger | 96% |
| Agent registry | 100% |
| Sandbox | 82% |
| Provider transport | 77% |
| Discord adapter | 58% |

The counts alone do not suggest an excessive suite. Many guards protect
failures that leave the happy path green: a sidecar omitted from a bundle,
an offered tool bypassing its definition's allowlist, a budget charge lost
when streaming stops, or a setting accepted but ignored. The history records
manual mutations used to show these tests fail when the boundary is removed;
this session has not rerun those mutations. Coverage is not a mutation score.

## Outstanding live checks

These remain open in the latest recorded evidence, even where scripted tests
cover the behavior. They are not all release blockers.

- A real OpenAI request, especially streamed usage accounting, and a run with
  workers using different providers. Anthropic and Ollama already have live
  evidence in the history; the old claim that no provider was called is stale.
- A real model attempting to spawn another space's agent. Live runs proved
  that only the selected roster is offered; the refusal itself was scripted.
- Discord starting a run in a non-default space, real mentions, multiple users
  or guilds, and rate-limit pressure. Do not send chat messages as part of a
  check without the user's authorization.
- Two real clients racing to answer the same approval. Duplicate resolution
  is covered by the API tests, not a recorded live race.
- Large transcripts, large windowed event logs, and backward replay cost.
  Small-run correctness does not establish performance at tens of thousands
  of events. Parallel workers are not implemented.
- A downloaded macOS release passing Gatekeeper's manual-open flow. Earlier
  Mac checks launched a locally built app, which had no download quarantine.

The first Mac session already closed automatic browser SSE reconnect,
two simultaneous browser streams, clicking run deletion, both-theme replay
comparison, packaged startup/shutdown and the native keychain round trip.
See the history for the measured limits, including small graph measurement
differences in the pixel comparison.
