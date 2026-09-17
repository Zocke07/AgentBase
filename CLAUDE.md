# CLAUDE.md

## Read first

Read [BUILD_SPEC.md](BUILD_SPEC.md) in full at the start of a session. It is the
design and constraint authority. This file holds current working context; the
[historical session record](docs/history/README.md) preserves earlier findings
and decisions. Read the relevant history when changing a boundary it explains.

The product is **AgentSpace**; the repository is **AgentBase**. Preserve the
bundle identifier `dev.agentspace.desktop`: changing it relocates users' data
and disconnects their stored keys.

## Current state

- Phases 0 through 9 and the spaces redesign are implemented. Do not restart
  Phase 0 or replace completed work from an earlier phase.
- The current release line is **0.2.0**. It includes the Windows installer and
  an ad-hoc signed, unnotarized Apple Silicon macOS app archive. An incomplete
  first Mac archive made Gatekeeper report that the app was damaged; the
  corrected 0.2.0 bundle has a complete code seal. Check the release page and
  tag workflow for publication status and cross-platform CI evidence.
- The UI has a left rail, spaces, Home, Runs, Agents, Space settings, and
  app-wide Settings. Approvals are docked. Discord is the only chat adapter;
  Telegram was removed on 2026-09-11.
- The latest recorded database migration is 007. Existing workspace files are
  adopted into the default space once; new spaces get their own folders. Each
  space folder is also an Obsidian-compatible Markdown vault. The Knowledge
  section provides notes, properties, tags, links, backlinks, search and a
  graph. Local hybrid RAG augments goals and handoffs with cited, untrusted
  excerpts; completed runs write durable `memory/runs/<run-id>.md` notes.
- OpenAI access can use either an API key or the user's ChatGPT subscription.
  Both remain the `openai` provider and share the same AgentSpace behavior;
  Codex App Server is a credential and single-decision inference transport,
  never the agent orchestrator. Direct Claude subscription login is not
  supported because Anthropic does not permit third-party Claude.ai login or
  routing of Free, Pro or Max credentials. Its separate unmodified-Claude-Code
  embedding exception is not an interchangeable provider credential transport.

See [Verification](docs/verification.md) for executed checks, outstanding live
checks and release status. Keep that document current instead of growing a
second chronological log here.

## Working rules

- Follow BUILD_SPEC constraints and record agreed deviations there. Report
  what actually ran and what remains unverified.
- Use `just` for project tasks. Do not add `.sh`, `.bat`, `.cmd` or `.ps1`
  wrappers. Recipes must work with the configured host shell, including
  Windows PowerShell 5.1.
- Write a test before changes to the event store, budget ledger or sandbox.
  For other changes, choose checks that can detect a real behavioral failure.
- Commit logical units with descriptive messages. Keep a documentation move
  and its link updates together. Preserve existing uncommitted user work.
- No em dashes in repository prose, source or config; the hygiene test enforces
  this. Comments explain reasons and boundaries rather than restating code.

## Boundaries to preserve

- The orchestrator is hand-written. No agent framework and no new service
  infrastructure in the shipped app. Every bind is hardcoded to `127.0.0.1`.
- The append-only event log is the authority within a run. Live and replay
  use one reducer over an event prefix. Adding an event type updates the Python
  contract, generated TypeScript and reducer together. Model summaries are
  claims; executed tool calls are separate evidence.
- API keys, ChatGPT OAuth tokens and the Discord token live in the OS keychain.
  API keys reach the sidecar over stdin at launch; ChatGPT OAuth is owned by the
  pinned Codex runtime and only safe account status reaches the local API. Never
  put secrets in SQLite, files, logs or argv. The webview can set/delete keys,
  not read them; API key changes require an app restart.
- Spawn-time key reads use the native `keyring` crate directly so a macOS
  access denial remains an error. Do not route these reads through the plugin's
  `get_password`, which discards the error. Ad-hoc builds can prompt again
  after a rebuild or upgrade.
- Tools validate and resolve in `prepare`, pass the approval gate, then run
  `execute`. Enforce the definition's allowlist independently of the tool list
  offered to the model. Filesystem tools use the run's space folder.
- `run_shell` has a timeout and process-tree termination, but no OS filesystem
  or network isolation. Do not describe approval as a containment guarantee.
  `http_get` checks public addresses and connects to the checked address;
  redirects require a new checked request.
- `RunLauncher` is shared by UI and Discord. It snapshots roster, rules and
  limits at run start. Worker delegation is sequential. A definition edited
  mid-run does not change that run.
- Approval rules can only narrow app-wide permission. Space `null` inherits;
  space `[]` asks for everything. Definition `[]` inherits. A denial of the
  same tool and original arguments persists for that run.
- Budget arithmetic uses integer micros. Check before a call; persist spend
  before yielding its streamed completion. Deleting a finished run keeps its
  spend with `run_id` cleared, preserving the app-wide budget total.
- Spaces own rosters and app-managed folders. The default space cannot be
  archived or deleted; a space with runs must be archived or have those runs
  deleted first. Deleting a run leaves the files it wrote alone.
- Markdown is the knowledge source of truth. Retrieval rebuilds from the space
  folder and excludes hidden paths. It never edits `.obsidian`, calls a remote
  embedding service or treats retrieved prose as instructions. Automatic run
  memories use unique app-owned paths and are named in `run.completed`.
- Discord accepts explicit commands/mentions from allowed senders only. Its
  supervised adapter runs in-process and uses the same approval gate as the UI.

## Commands and release checks

```text
just setup             # install backend and frontend dependencies
just check             # lint, formatting check, Python/TypeScript typechecks
just ci                # check plus backend and frontend tests
just test-backend-cov   # backend statement coverage, not branch coverage
just schemas           # regenerate committed OpenAPI and TypeScript
just build-installer   # freeze sidecar, then build NSIS or macOS .app
just verify-build      # require built artifacts and verify their contents
just check-tauri        # Rust clippy; run after a sidecar exists
just paths             # cache, dependency and development data locations
```

`just typecheck` checks Python on the host and the opposite target platform.
`tauri-build` checks `externalBin` during clippy too, so Rust checks need the
frozen sidecar first. Never restore a cached Rust `target/` in release CI:
stale sidecars have previously survived bundling.

Windows smoke tests install the downloaded installer on a fresh CI runner
and launch its sidecar with Python removed from the environment. This is the
recorded substitute for a second Windows machine, not a GUI launch test or a
runner with Python uninstalled. Tag-triggered release publication must remain
gated on both build verification and the Windows install smoke test.

## Find details

- [Developer guide](docs/developer_guide/README.md): architecture, setup,
  debugging, testing, change checklists and packaging.
- [User guide](docs/user_guide/README.md): installation and the current UI.
- [Verification](docs/verification.md): current evidence and open checks.
- [Historical record](docs/history/README.md): phase reports and original
  decision reasoning, including superseded findings.

Code lives in `apps/backend` and `apps/desktop`; generated API contracts live
in `packages/schemas`. Development caches and runtime data stay under `.dev/`
through justfile exports. Installed apps use the OS local application-data
directory, not the repository. Tool installations and some Tauri tool caches
remain in their system locations.
