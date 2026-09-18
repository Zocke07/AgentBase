# Architecture

For installation and the first checks, start with [Development setup](2_development_setup.md).

## Repository map

```
apps/backend/src/agentspace/    Python 3.12 FastAPI sidecar
  main.py                       app factory, lifespan, stdin watchdog, run()
  config.py                     BIND_HOST (hardcoded), ports, data paths
  secrets.py                    API keys in memory; the stdin handshake
  events/                       EventType, EventStore.append, EventBus
  store/                        SQLite + migrations (*.sql), settings, spaces, agent_defs
  providers/                    Provider protocol, Anthropic/OpenAI/Ollama, ChatGPT transport,
                                pricing, factory
  budget/ledger.py              the monthly cap, checked before every call
  knowledge/store.py            Markdown parser, links, graph, local vectors, RAG memory
  orchestrator/                 run lifecycle, supervisor, agent loop, limits,
                                control tools, registry, launcher
  tools/                        catalogue, Tool protocol, sandbox, approval gate,
                                runtime, builtin/{filesystem,knowledge,network,shell}.py
  channels/                     Discord adapter, identity allowlist,
                                the chat renderer, throttle, service
  api/                          runs, stream (SSE), approvals, agents, spaces, knowledge,
                                settings, auth, channels
  openapi.py                    builds the OpenAPI doc and emits the TS types
apps/backend/tests/             pytest; support.py holds the shared doubles
apps/desktop/src/               React 19 + Vite + TypeScript
  lib/                          api.ts (typed calls), events.ts (SSE client), sidecar.ts,
                                markdown.ts (the Obsidian dialect), fuzzy.ts, graphLayout.ts
  state/                        reducer.ts: the fold; runStore, graph, spaces, hooks
  components/                   Rail, SpaceSwitcher, HomeView, RunsView, AgentsView,
                                SpaceSettingsView, SettingsView, RunGraph, EventLog,
                                ApprovalPanel, AgentEditor, BudgetMeter, RunPanel,
                                Markdown, KnowledgeView, NoteTree, NoteEditor,
                                QuickSwitcher, MemoryInbox, KnowledgeEvaluation
apps/desktop/src-tauri/         Rust shell: spawns the sidecar, reads the keychain
  binaries/                     the frozen sidecar lands here (git-ignored)
packages/schemas/               openapi.json + src/api.ts, GENERATED and committed
.github/                        workflows/build.yml + actions/toolchain
.dev/                           git-ignored: caches and dev runtime data
```

The [project history](../history/README.md) records why modules were added beyond
the original layout in BUILD_SPEC §3.

### The one idea

Every agent action is an append-only row in `events`. The UI is
`reduceAll(events.slice(0, cursor))` and nothing else; live is that fold with
the cursor at the head, replay is the same fold with a smaller cursor. The
chat reply is a second pure fold of the same log. If you are about to send the
frontend a separate representation of an agent action, stop and put that fact
in the event contract. Navigation, settings, rosters and loading state use their
own API/store state; the run projection is the part derived only from events.

### Spaces and settings

A space owns its roster and the sandbox folder at `<data dir>/spaces/<id>/`.
`store/spaces.py` derives this path; a space row cannot name an arbitrary folder.
Runs and agent definitions have `space_id`; a launcher snapshots the effective
settings and that space's roster before the run starts. Renaming or editing a
space does not rewrite a running or historical run.

Model and run limits resolve from the app defaults through space overrides and,
where applicable, agent definitions. Approval policy can only narrow: a space's
`null` means inherit, while `[]` means ask for everything. An agent definition's
`[]` means inherit. Model credentials, OpenAI's access mode, the monthly cap,
and the Discord connection are app-wide. `channel_space_id` selects the space
receiving Discord commands.

### OpenAI credential transports

`openai_access` selects `api_key` or `chatgpt` without introducing another
provider. Both factory branches return a provider named `openai` with the same
model id and `Provider.complete`/`Provider.stream` contract, so the provider
pool, budget wrapper, orchestrator, tools, events and limits do not branch on
authentication method.

ChatGPT access is implemented with a process-wide, pinned Codex App Server
runtime with its `CODEX_HOME` under `<data dir>/codex`. The App Server
executable is not frozen into the sidecar: `providers/codex_runtime.py`
carries a manifest of the `openai-codex-cli-bin` wheels `uv.lock` pins
(`just codex-manifest` regenerates it, and a test keeps the two equal),
fetches this platform's wheel into `<data dir>/codex-runtime/<version>/<tag>/`
on the first sign-in, verifies the size and SHA-256 before unpacking only the
members the SDK uses, and hands the executable to the SDK through
`CodexConfig.codex_bin`. A checkout with the wheel installed uses it directly,
so tests and `just dev-app` stay offline. It is a credential and inference
transport, not an agent framework. Each call starts an ephemeral read-only thread with
approvals denied and Codex tools disabled, supplies the AgentSpace conversation
and tool schemas as data, and requests one structured decision. A requested
tool is converted to the normal `ToolCall`; the hand-written AgentSpace loop
decides whether and how to execute it. This preserves the approval and event
boundaries even though the wire protocol differs from an API-key request. The
App Server's structured JSON stream is incrementally decoded so only its
top-level user-facing `text` reaches normal `llm.token` events; JSON framing
and tool arguments never appear as display text.

The runtime forces ChatGPT login and OS-keychain credential storage. The local
auth API returns connection state, email, plan and the browser URL only; it
never returns access or refresh tokens. Account entitlements can differ between
ChatGPT and API access, so a selected model can be rejected by one transport.
The adapter reports that error without changing the model.

The rail separates Home, Runs, Agents and Space settings from app-wide Settings.
`RunPanel` contains the event-derived `run-projection`; its scrubber and the
docked `ApprovalPanel` also need current viewer or approval-service state.

### Markdown knowledge and RAG

`KnowledgeStore` treats a space folder as the canonical vault. Each request
walks the folder with `os.walk`, compares every visible `.md` file's size,
mtime and inode with the last snapshot, and parses only the files that
changed; an unchanged vault reuses its resolved links. Hidden paths and
symlinks are skipped. Parsing splits a note at headings and computes each
chunk's BM25 term counts, a deterministic 768-slot hashed vector and its term
sets once, so a query over 10,000 notes (`MAX_NOTES`) costs tens of
milliseconds for the scan and about a tenth of a second for ranking. The
snapshot cache is keyed by resolved root and shared with the agent-facing
`search_knowledge` tool. This is intentionally local and dependency-free so the
frozen sidecar does not ship a model runtime or send notes to an embedding
service. `test_knowledge.py` pins the 10,000-note bound with real files.

`RunLauncher` hands the store to `execute_run`. Goal retrieval happens before
the supervisor is created, and handoff retrieval happens before each worker's
first model call. Retrieved prose is delimited as untrusted data and carries
stable wiki citations. `run.started` records the exact excerpts and the
citations the user excluded from the Home preview; the reducer folds them into
`RunView.knowledge` so the run view and a replay show the same evidence.
Successful outcomes are projected into unique Markdown files under
`memory/runs` with the goal's citations under `## Sources`;
`run.completed.memory_path` connects the durable event to that projection.

Memories are Markdown with a `type` of `run-memory` or `agent-memory` and a
`status` of `proposed`, `approved` or `archived`. `SearchFilters` admits only
approved or pinned memories by default, which is what makes the inbox a trust
gate rather than a label. `memory_markdown` is the one writer for run
memories, the `propose_memory` tool and merges, so the inbox can read every
shape back. The event log remains authoritative for what happened.

---

## Conventions

**From BUILD_SPEC §6.** One phase per session. Do not claim something works
unless you executed it: "should work" and "works" are different words.
Negative results are useful; report them. Ask before deviating from a §1
constraint; do not route around it. Commit per logical unit with a real
message. Keep [CLAUDE.md](../../CLAUDE.md)'s current context updated and record
decisions and verification results in the [project history](../history/README.md).

**The recurring bug, stated as a rule.** Nine times in this project something
was correct everywhere except where the product actually used it, and every
test was green: CORS headers, named SSE frames, a `*.sql` glob, silently
dropped settings fields, a duplicated default, an unsettable policy, a
mispriced model id, a setting that did nothing until restart, a recipe that
could never have run. **Every one was found by running the thing.** Install it,
open it in the browser, type the command in Discord, read the console. A green
suite is where verification starts, not where it ends.

**Lint rules that encode decisions.** `PTH` (pathlib only, zero string path
concatenation), `DTZ` (no naive datetimes in an event log), `T20` (no `print`),
`S` (bandit), `TID` (no relative imports), `ARG` (unused arguments: exempted
only for `ARG002` on protocol-conforming doubles and adapters). `mypy --strict`
with `warn_unreachable` and `disallow_any_unimported`. ESLint enforces
case-sensitive import paths even on a case-insensitive host. The build matrix
currently runs Windows and macOS.

**Line endings are LF, and it is enforced.** `.gitattributes` has
`* text=auto eol=lf`, `ruff format` is pinned to `lf`, and `ruff format
--check` is in the gate. If you write source from a Python helper, pass
`newline="\n"`: `Path.write_text` on Windows writes CRLF and only the format
check notices.

**Two lists that must agree get a test, not a comment.** Settings model vs.
patch model, `SECRET_KEYS` vs. `SECRET_NAMES`, migrations vs. the packaging
glob, the justfile vs. the workflow. When you find yourself writing "keep in
sync with X", write the test instead.

**Hardcoded on purpose:** `BIND_HOST = "127.0.0.1"`, guarded by
`assert_loopback_only` at every bind and by a test that fails if it becomes
configurable. `ALLOWED_ORIGINS` is an explicit allowlist, never a wildcard.

---

## Gotchas

**The sidecar stops on stdin EOF.** `python -m agentspace < NUL` (Windows) or
`python -m agentspace < /dev/null` (macOS), or a subprocess with a closed
stdin, exits at once with `stdin reached EOF; shutting down`. Hold stdin open.
This is the shutdown mechanism, not a bug.

**Port 8787 is taken and nothing is listening.**

- **Windows:** Check for an orphaned uvicorn reload worker:
  `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like
  '*multiprocessing*' }` and `taskkill /PID <id> /T /F`. Or a stray
  `agentspace-sidecar` from an installed app or a crashed `dev-app`.
  `netstat -ano | findstr :8787` names the PID; note it can report the
  *creator* of the socket rather than the process now holding it.
- **macOS:** `lsof -ti tcp:8787` names the PID. Kill it with
  `kill <pid>`. Check for an orphaned uvicorn worker with
  `ps aux | grep multiprocessing`.

**`Invoke-WebRequest` and `curl` do not enforce CORS; a webview does.** A green
HTTP smoke test proves the server answered, not that the page was allowed to
read the answer. Test UI-facing changes in a browser.

**`httpx2`, not `httpx`.** The distribution and the module are both `httpx2`.

**`&&` is a parser error in Windows PowerShell 5.1**, which is `just`'s shell
there. Every recipe body is a single command with `[working-directory(...)]`
instead of `cd &&`. This is not an issue on macOS where `just` uses `sh`/`zsh`.

**Vite's watcher ignores `src-tauri/**`.** Under `tauri dev` cargo writes
`target/` while Vite watches; on Windows the resulting EBUSY kills the dev
server. Do not remove the ignore.

**An open SQLite handle locks the file on Windows.** Tests close the database
before `tmp_path` teardown; the lifespan closes it before exit so the installer
can replace it. One connection behind a lock, not one per thread, for the same
reason. This is less of an issue on macOS where POSIX file locking is
advisory, but the codebase follows the same pattern everywhere.

**`Get-Content`/`json.load` on a pipe decodes as cp1252 in Git Bash.** A
`-` read back as `â€“` is your pipe, not your data. Check with `ord()` before
reporting mojibake. (macOS terminals default to UTF-8; this is a Windows
problem.)

**macOS Keychain access can prompt again after a rebuild.** An ad-hoc-signed
binary has a different identity when its code changes. **Always Allow** trusts
the current binary; a later rebuild may ask again. **Deny** leaves that key out
of the startup handshake and logs `[keychain] could not read <name>: ...`.
See [Debugging the Tauri shell](3_debugging.md#debugging-the-tauri-shell).

**`/var` is a symlink on macOS.** The sandbox resolves paths with
`Path.resolve()`, and on macOS `/var` → `/private/var`. An unresolved sandbox
root silently rejects everything whose resolved path does not start with it.
The codebase resolves the root at construction time for this reason.

**Anthropic coalesces streaming deltas unpredictably**: the same prompt
produced 1, 2 and 10 `text_delta` frames on four requests. Never build timing
around delta size, and never treat `llm.token` as a liveness signal.

**Small local models confabulate.** Four live runs have announced work
(`finish("saved to notes.txt")`) that the log shows never happened. When
debugging a run, believe `tool.called`, not the summary.

**`/agent` is the live-verified Discord trigger.** `INTENTS` enables `guilds`
for command sync and the non-privileged `guild_messages` intent for explicit
mentions; `message_content` stays disabled. Discord includes content for a
message that mentions the bot, and the handler rejects every message without
that mention. The mention path has unit tests but is not live-verified. Any
intent change requires reviewing `test_channel_adapters.py` and BUILD_SPEC §1
constraint 6; ambient chat must never become agent context.
