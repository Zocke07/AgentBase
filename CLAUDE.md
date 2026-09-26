# CLAUDE.md

## Read first

Read [BUILD_SPEC.md](BUILD_SPEC.md) in full at the start of a session. It is the
design and constraint authority. This file holds current working context; the
[historical session record](docs/history/README.md) preserves earlier findings
and decisions. Read the relevant history when changing a boundary it explains.

The product and repository are **AgentBase**. Its bundle identifier is
`dev.agentbase.desktop`; preserve it after the one-time rename migration so
future changes do not relocate users' data or disconnect their stored keys.

## Current state

- The product was renamed to **AgentBase** on 2026-09-24. New installs use the
  AgentBase package, bundle, sidecar, schema, data, keychain and browser-storage
  namespaces. On its first canonical launch, an empty AgentBase data directory
  adopts the prior profile and its SQLite database. Legacy credentials, browser
  preferences and saved visualization schemas remain readable during the
  transition; current AgentBase values take precedence.
- Phases 0 through 9 and the spaces redesign are implemented. Do not restart
  Phase 0 or replace completed work from an earlier phase.
- The current release line is **0.4.6**: the rename to AgentBase across the
  product, package, bundle and data identifiers, with one-time adoption of a
  pre-rename install's data and database and read-through fallbacks for its
  keychain entries, browser preferences and saved visualizations, over 0.4.5's
  charts from CSV and JSON, portable agent-written visualization specs,
  dashboards, Mermaid, exports and visual RAG metrics, over 0.4.4's guards on
  runaway runs, per-run cost ceiling (migration 014) and data files in
  Knowledge, over 0.4.3's
  provider-change fix and folding rail (013), 0.4.2's model on each space
  (012), 0.4.1's investment roster (010) and per-tool answers (011), 0.4.0's
  schedules, Usage and tour, 0.3.3's run canvas and vault and 0.3.2's
  packaging. It includes the Windows installer and an ad-hoc signed,
  unnotarized Apple Silicon macOS disk image (a zip until 0.3.1; the image's
  Applications link keeps the app out of Downloads, where Gatekeeper
  translocates it and Spotlight ignores it). An incomplete first 0.2.0 Mac
  archive made Gatekeeper report that the app was damaged; the corrected
  bundle has a complete code seal. Check the release page and tag workflow
  for publication status and cross-platform CI evidence.
- The UI has a left rail, spaces, Home, Runs, Agents, Knowledge, Visualize, Usage, Space
  settings, and app-wide Settings. Approvals are docked. The run canvas is a
  left-to-right workflow (goal, supervisor, workers, outcome) with an
  inspector; the Knowledge section is laid out as an Obsidian vault and one
  Markdown renderer (`components/Markdown.tsx`, over `lib/markdown.ts`)
  serves notes, agent prose and excerpts without ever emitting raw HTML.
  A first launch opens a tour, gated on the `onboarding_completed` setting.
  Discord is the only chat adapter; Telegram was removed on 2026-09-11.
- A space can schedule runs (Space settings): daily or weekly at a local time,
  or every N hours, started through `RunLauncher` by one scheduler task in the
  sidecar. The app must be open; a missed time is run once at the next launch
  or skipped, per the schedule. There is no tray or service mode.
- The default space ships the ten-definition investment research roster
  (migration 010, 2026-09-19): four Haiku collectors, Sonnet analysts and a
  risk manager, an Opus decision agent, a Sonnet reviewer, each with an
  explicit Anthropic model and no `run_shell` anywhere. Migration 015 moves
  an untouched `news-scanner` from raw `http_get` responses to `read_feed`,
  which parses complete RSS or Atom entries locally and supplies deterministic
  identifiers; the other network collectors retain `http_get`. The three
  generic roles are now the starter roles a new
  space is seeded from (`store/builtins.py`); 010 retires them from the
  default space only while untouched. The prompts assume scripts and config
  files the app does not ship; the user guide says which.
- Settings chooses the provider only; every space names its own model
  (`spaces.model`, filled by migration 012 for existing rows), an agent may
  pick its own, and the app-wide `settings.model` remains as the fallback
  that follows the provider and is not shown. A schedule may carry its own
  `max_run_seconds`, laid over the space's for its runs alone. `GET /runs`
  takes `origin`. A change of the app-wide provider moves every space that
  inherits the provider to the new provider's default model, since a model
  belongs to a provider. The Knowledge tree can delete a folder (backed up
  first); the rail folds to icons (Ctrl/Cmd+B).
- Three guards on runaway runs, all in `orchestrator/agent.py`: model
  answers may carry `MAX_OUTPUT_TOKENS` (16,384); an answer that hit the
  output limit is not run as a broken call but reported and nudged; an agent
  that fails the same way or makes the identical call `MAX_SAME_FAILURES`
  (3) times in a row completes with reason `stuck`. `max_run_cost_micros`
  (settings, spaces, migration 014; $2.00 by default, 0 off) fails a run
  that has spent it, checked before each model call like the deadline.
  Plain-text data files beside the notes are listed and edited through
  `/knowledge/files` and `/knowledge/file` (JSON parsed before a write).
- The Visualize section parses CSV, TSV, JSON and JSON-lines locally and draws
  bar, line, area, scatter, pie, metric and table views. A versioned `.viz.json`
  points at a data file, `.dashboard.json` composes saved charts and `.mmd` or
  `.mermaid` holds a diagram. Mermaid uses strict mode and its SVG is sanitized
  again before insertion. These are ordinary space files written through the
  existing gate; there is no visualization database or service.
- The latest recorded database migration is 015 (complete feed input for an
  untouched `news-scanner`). Existing workspace files are
  adopted into the default space once; new spaces get their own folders. Each
  space folder is also an Obsidian-compatible Markdown vault. The Knowledge
  section provides notes, properties, tags, links, backlinks, unresolved links,
  pins, filters, move with link rewriting, folder import, templates, daily
  notes, search, a graph and a retrieval evaluation. Local BM25 and
  hashed-vector RAG augments goals and handoffs with cited, untrusted excerpts
  that the Home preview and the run view show and the user can exclude.
  Completed runs and the `propose_memory` tool write proposed memories that
  the inbox approves, archives, pins, merges or forgets; only approved or
  pinned memories are retrieved. The practical vault limit is 10,000 notes.
- OpenAI access can use either an API key or the user's ChatGPT subscription.
  Both remain the `openai` provider and share the same AgentBase behavior;
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
  pinned Codex runtime, which is fetched from the wheel `uv.lock` pins on the
  first sign-in (never frozen into the sidecar), and only safe account status
  reaches the local API. Never
  put secrets in SQLite, files, logs or argv. The webview can set/delete keys,
  not read them; API key changes require an app restart, which Settings offers
  through the shell's `restart_app` (stop the sidecar, then relaunch), never by
  re-reading keys into a running sidecar.
- Spawn-time key reads use the native `keyring` crate directly so a macOS
  access denial remains an error. Do not route these reads through the plugin's
  `get_password`, which discards the error. Ad-hoc builds can prompt again
  after a rebuild or upgrade.
- Tools validate and resolve in `prepare`, pass the approval gate, then run
  `execute`. Enforce the definition's allowlist independently of the tool list
  offered to the model. Filesystem tools use the run's space folder.
- `run_shell` has a timeout and process-tree termination, but no OS filesystem
  or network isolation. Do not describe approval as a containment guarantee.
  `http_get` and `read_feed` check public addresses and connect to the checked
  address; redirects require a new checked request. `read_feed` accepts at
  most 2 MB of untrusted XML and returns no more than 20 complete entries.
- `RunLauncher` is shared by UI and Discord. It snapshots roster, rules and
  limits at run start. Worker delegation is sequential. A definition edited
  mid-run does not change that run.
- Approval rules can only narrow app-wide permission. Space `null` inherits;
  space `[]` asks for everything. Definition `[]` inherits. A denial of the
  same tool and original arguments persists for that run. Per-tool answers
  (`tool_policies`: ask, allow, deny) are read before the risk level; a space
  can only make one stricter, and a definition that names levels turns an
  allow outside them back into a question. A yes given "for this run"
  (`approvals.scope = 'run'`) answers every later call to that tool in the
  run; a no is never for a run.
- Budget arithmetic uses integer micros. Check before a call; persist spend
  before yielding its streamed completion. Deleting a finished run keeps its
  spend with `run_id` cleared, preserving the app-wide budget total.
- Spaces own rosters and app-managed folders. The default space cannot be
  archived or deleted; a space with runs must be archived or have those runs
  deleted first. Deleting a run leaves the files it wrote alone.
- Markdown is the knowledge source of truth. Retrieval rebuilds from the space
  folder on use, reparsing only changed files, and excludes hidden paths and
  symlinks. It never edits `.obsidian`, calls a remote embedding service, runs
  a background index job or treats retrieved prose as instructions. Automatic
  run memories use unique app-owned paths and are named in `run.completed`;
  a memory is retrieved only once approved or pinned. Merges and moves back up
  the files they change under `.agentbase/backups/`.
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
