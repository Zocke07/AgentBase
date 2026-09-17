# Verification and remaining work

Updated 2026-09-15. This is the current record; the
[historical session notes](history/README.md) retain earlier evidence and
superseded gaps. A test result below is scoped to what was actually executed.

## Markdown knowledge, local RAG and durable memory

The 2026-09-15 knowledge-vault addition was checked on Apple Silicon macOS.
Each space now exposes ordinary Markdown notes through the native Knowledge
section, including safe source/preview modes, YAML properties and tags,
wikilinks, backlinks, retrieval search and a linked-note graph. The same local
retriever supplies cited, untrusted context to run goals and worker handoffs.
Successful runs write unique `memory/runs/<run-id>.md` outcome notes, and the
desktop shell can open only a validated space folder through an encoded
Obsidian URI.

`just lint typecheck` passed for 108 Python source files on both the macOS and
Windows mypy targets, plus desktop ESLint and TypeScript. The complete suites
passed with **763 backend tests** and **324 frontend tests**; 11 backend tests
skipped for absent platform or release-archive prerequisites. Focused tests
also covered external Markdown parsing, relative links, heading retrieval,
stable citations, path and `.obsidian` refusal, API CRUD/CORS, run memory and
the agent-facing search tool. Rust formatting, Clippy and both Rust unit tests
passed. A fresh sidecar containing migration 007 was built at **132,920,928
bytes**, SHA-256
`9028c9359be3f1105713b19b33516cdf23703235708c2cc9b71929fd4ee0b3b3`;
all **13 frozen-sidecar tests** then passed against those exact bytes. The
backend passes used normal macOS process and network facilities so their
frozen-sidecar and DNS checks could execute.

## ChatGPT subscription transport

OpenAI API-key and ChatGPT subscription access now construct the same `openai`
provider contract. The ChatGPT path uses a pinned Codex App Server runtime for
OAuth and one structured model decision, while AgentSpace retains its own
orchestrator, tool execution, approvals, events, limits and budget wrapper.

On Apple Silicon macOS, `just check` passed for 102 Python source files on both
macOS and Windows mypy targets plus desktop lint and typecheck. The full suites
passed with **750 backend tests** and **319 frontend tests**; 11 backend tests
skipped for absent platform or release-archive prerequisites. Rust formatting
and its one auth-URL test passed. The freshly frozen sidecar is **133,046,736
bytes**, SHA-256
`097497ae43ab32c3a5d0273d6420bb3d42253d82da1acc6ef5c53ac68ae09b99`.
All **13 frozen-sidecar tests** passed with normal macOS process facilities,
including first-launch data, `/auth/chatgpt` runtime startup, event streaming,
clean shutdown and zero orphan processes. The managed sandbox itself blocked
the PyInstaller executable's process/semaphore startup, matching the existing
release-check limitation recorded below. A separate direct launch of that
frozen binary returned
`{"state":"disconnected","email":null,"plan":null,"error":null}` from the
auth endpoint, then stopped cleanly through its stdin shutdown command.

## 0.2.0 macOS signing correction

The published 0.2.0 Mac archive reproduced the user's **damaged and can't be
opened** Gatekeeper error. `codesign --verify --deep --strict` showed that the
archive preserved executable modes but lacked a complete app-bundle signature.

The corrected 0.2.0 build configures Tauri's ad-hoc identity and keeps hardened runtime
disabled. Enabling the runtime caused the re-signed PyInstaller sidecar to fail
while loading its extracted Python library because the process and mapped file
had different code identities. The release test now strips signatures from
temporary copies before checking sidecar content, verifies the complete bundle
signature, then launches the archived sidecar. The corrected local archive
passed all **15 applicable release checks**; four Windows-only checks skipped.
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` is 24,188,613 bytes with local
SHA-256 `3d1ebcc69b79cf3ed5dd4691722488c3928e1a7743c3746a2e9992a3e32d4719`.

## 0.2.0 preparation

Documentation and local release preparation were completed before publication.
The [v0.2.0 release page](https://github.com/Zocke07/AgentBase/releases/tag/v0.2.0)
is the authority for publication status and downloadable artifacts. The tag
workflow is the authority for cross-platform CI results.

On Apple Silicon macOS, `just ci` passed with **738 backend tests and 313
frontend tests** after the documentation, version and Discord mention changes.
Eight backend tests skipped because their current build or platform prerequisite
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

- A real OpenAI API-key request, especially streamed usage accounting, and a
  run with workers using different providers. Anthropic and Ollama already
  have live evidence in the history; the old claim that no provider was called
  is stale.
- Completing ChatGPT browser sign-in with a personal account and running a real
  subscription-backed task. The isolated Codex runtime has started and reported
  `disconnected`; automated tests cover auth lifecycle, one-decision transport,
  normalized usage and tool calls, but no personal OAuth session was used.
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
