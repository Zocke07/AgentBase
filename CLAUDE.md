# CLAUDE.md

## Read this first

The full specification is [BUILD_SPEC.md](BUILD_SPEC.md). **Read it in full at the
start of every session.** This file is a pointer and a running log, not a summary
— when the two disagree, BUILD_SPEC.md wins.

## Current phase

**Phase 0 — Scaffold and cross-platform hygiene.** Complete.

**Phase 1 — Packaging spike.** Complete. A built NSIS installer installs
per-user, launches, reaches the sidecar, and leaves zero processes behind.

**Phase 2 — Event spine.** Complete. SQLite + migrations, `EventStore.append`
with atomic per-run `seq`, an `EventBus`, and a resumable SSE stream. Verified
against the acceptance criterion with a real `curl` client killed mid-stream —
and, separately, from inside the webview.

**Phase 3 — Providers, budget, keychain.** Complete. Three providers behind one
protocol, integer-micros pricing, a monthly cap that refuses before the call,
and API keys delivered from the OS keychain over stdin.

**Phase 4 — Orchestrator.** Complete. A hand-written supervisor/worker loop, a
run whose event log alone reconstructs it, three enforced limits, and streaming
through the budget guard. Verified with a **real two-worker Anthropic run**:
3 agents, 6 model calls, 50 events, `run.completed`, $0.0260 recorded.

### What the first real API call showed

**The provider shapes were right.** Phase 3 predicted "at least one shape bug"
on the first real call and there was none in the request/response mapping.
Anthropic's split token accounting — input on `message_start`, output on
`message_delta` — produced correct non-zero usage on all six calls (998/256,
868/141, 1055/184, 1156/354, 992/189, 1303/198), tool calls came back with
their arguments intact, and `stop_reason` mapped cleanly. The mock-transport
fixtures had the shapes correct.

**`llm.token` granularity is server-decided and varies wildly.** This is the
finding worth carrying into Phase 7. The same prompt, same model, same payload
produced **1, 2, and 10** `text_delta` frames across four requests. Suspecting
the adapter was merging frames, a probe wrapped `stream_sse` to count frames in
against `TextDelta`s out **on one request**: they matched exactly, every time
(2→2, sizes `[123, 27]` and `[140, 10]` identical in and out). So the adapter is
faithful and Anthropic simply coalesces its own deltas, probably influenced by
how fast the client reads.

The first comparison was two *separate* requests and looked like a bug — 10
frames raw versus 2 through the provider. It was not. Do not conclude anything
about streaming granularity from two different calls.

Consequence for Phase 7: a UI that assumes a per-token typewriter effect will
look wrong, because a whole 479-character paragraph can arrive in four chunks
or one. Render whatever arrives; do not build timing around delta size.

**Keys stayed where they belong.** After a real run: no key material anywhere in
`agentspace.sqlite3`, its `-wal`/`-shm`, or the sidecar's stdout/stderr, and
`/settings` reported `configured_secrets: ["anthropic_api_key"]` — the name,
never the value. The stdin handshake was performed by a stand-in for the Tauri
shell, so this exercised sidecar-side secret handling end to end; the
keychain→stdin half is still untested (see below).

### The bug the real run found

**A setting that could not be set, and said it could.** `PATCH /settings` with
`max_steps_per_agent` returned `200 OK` and changed nothing:
`UpdateSettingsRequest` lists its fields explicitly and the three Phase 4 limits
were never added, so Pydantic silently dropped them. §5 Phase 4 says the limits
are "all configurable" — and they were, but only by writing to SQLite directly,
which is not something the product can do.

The silence is the worse half: the caller was told it worked. `extra="forbid"`
now makes an unknown or misspelled field a 422 naming it, which is also what
Phase 7 needs to put the error on the offending input rather than in a toast.

This is the fourth time in this project the same shape has appeared — correct
everywhere except where it is actually used, and invisible to a green test
suite. Phase 1's CORS, Phase 2's named SSE events, Phase 3's `*.sql` glob, and
now this. Every one of them was found by running the thing, not by reading it.

### What Phase 4 established, and how it was verified

**The event log is load-bearing, not a record kept alongside the truth.** A
worker's result reaches the supervisor by being appended as `agent.message` and
read back **out of SQLite** by `Mailbox.collect` — not by being returned up the
call stack. That is slower than passing a string and it is the point: the §5
Phase 4 criterion ("the full event log alone is sufficient to reconstruct
exactly what happened") stops being an aspiration and becomes a thing that
breaks loudly. Confirmed by mutation: deleting the single `deliver` call in
`Agent._finish` fails **seven** tests, including the run completing at all. A
design where the log is written *and* the value returned would have passed
every one of them with the log silently half-empty.

**The reconstruction is asserted by a reducer that can only see events.**
`reconstruct()` in `test_orchestrator.py` takes a list of event rows and has no
access to the `runs` table, the orchestrator, or the provider. Every assertion
about a run goes through it. The five `test_dropping_*` cases then remove one
event type at a time and confirm the matching assertion actually fails — so
none of them is quietly resting on live state. The reducer lives in the tests
because §5 Phase 7 owns the real one, in TypeScript.

**The limits are shaped by §4's closed event list, not by preference.** There
is no `agent.failed`, so an agent that runs out of steps *completes* with
`reason: "max_steps"`. Wall-clock fails the run. `max_agents_per_run` refuses
the spawn, tells the supervisor through `tool.error`, and leaves the run alive —
killing a run that is otherwise succeeding because its supervisor asked for one
worker too many trades real work for strictness, and a supervisor that loops on
retrying hits the step limit anyway. (Asked before deviating, per §6.)

**The deadline is checked before the model call, and that ordering is pinned.**
Moving `check_deadline()` after `_call_model` bills 100 input tokens on a run
that should already have stopped, and
`test_a_run_that_outlives_its_deadline_fails` fails on `input_tokens == 0`.
Without that one assertion the mutation passes.

**`BudgetedProvider` had to grow `stream()` or stop meaning anything.** The
orchestrator streams by default. A guard that wrapped only `complete()` would
have left the cap binding nothing that actually runs, while every Phase 3 test
kept passing. Spend is recorded *before* the terminal completion is yielded,
because a consumer that stops iterating the moment it has the completion would
otherwise close the generator unbilled.

**A token flood cannot gap a slow subscriber — now measured, not assumed.**
This closes the Phase 2 note that said to revisit backpressure here. One
streamed response of 900 words overflows the 512-event queue by a wide margin
while the client reads nothing. The test holds a second subscriber purely to
assert it was actually marked stale, because "more than 512 events arrived" is
a different claim from "a subscriber was dropped and the stream recovered by
re-reading SQLite". Both hold, and the client still receives a gapless 1..N.

**Only calls that touch nothing are offered.** `finish`, `handoff`,
`spawn_agent` — see `orchestrator/control.py`. Anything reaching the
filesystem, shell or network needs Phase 6's approval gate, and shipping it now
would create exactly the ungated path §1 constraint 5 forbids. The
`tool.requested` → `tool.called` → `tool.result` sequence is nonetheless the
real one, so Phase 6 inserts the approval events between the first two rather
than reshaping what exists.

### The bug worth remembering (Phase 4)

**Two of them, and neither was in the product.**

The first: `Path.write_text()` on Windows translates `\n` to `\r\n`. Editing
source with a Python helper script silently converted six LF files to CRLF,
against `.gitattributes`' `* text=auto eol=lf`. `ruff check`, `mypy` and
`pytest` were all still green — only `ruff format --check` noticed, and it is
**not** in `just check` (`lint` is `lint-backend` + `lint-desktop`;
`lint-backend-format` is a separate recipe nothing depends on). Git would have
normalized it at commit, so the damage was confined to the working tree — but
the lesson is that the one check that catches this is the one the gate does not
run. Use `newline="\n"` explicitly when writing files from a script.

The second: `httpx`'s ASGI transport **buffers a response body to completion**
before handing it back. The first version of the backpressure test opened an
SSE stream over `ASGITransport` and then started the run that would fill it —
which deadlocks, because the request cannot return until the response ends and
the response cannot end until the run it is waiting on begins. It presented as
a `pytest-timeout` kill with a stack in `GetQueuedCompletionStatus`, which
looks exactly like a server-side hang and is not one. The stream is therefore
consumed through `run_stream` directly; the HTTP framing above it is already
covered by the Phase 2 tests, and what had never run under real overflow is the
resync path.

Also worth recording because it was *not* a bug: a `run.failed` payload read
back over HTTP appeared to contain `â€"` mojibake. It did not. The stored
codepoint is a clean U+2014 and the corruption was in the inspecting pipe —
`json.load(sys.stdin)` decodes with the locale encoding, which is cp1252 in Git
Bash on this machine. Checked with `ord()` before reporting anything.

Next up: **Phase 5 — Agent registry.** Do not start it before re-reading
BUILD_SPEC §5 Phase 5.

### What Phase 3 established, and how it was verified

**The budget check is a wrapper, not a convention.** `BudgetedProvider`
implements the same protocol as the provider it wraps, so the only way to reach
a model is through the check. A rule the orchestrator is merely *expected* to
call first survives exactly until the second call site, and the evidence of
breaking it is a provider invoice rather than a stack trace. Confirmed by
mutation: moving the check after the call makes
`test_a_run_over_cap_is_refused_before_any_api_call_fires` fail, because the
provider double raises if it is called at all. A test that only asserted the
error message would have passed with the request already sent.

**An unpriced model is refused, never charged at zero.** `PRICES.get(model, 0)`
is the obvious implementation and it silently disables the cap the day a
provider ships a model id the table does not know. `pricing.UnknownModelError`
makes that loud, and both the ledger and the pre-flight check refuse rather than
treating an unknown cost as no cost.

**Money never touches a float.** Prices are stored as micros *per million
tokens*, because real published prices include $2.50 and $0.05 per million —
2.5 and 0.05 micros per token, which are not integers. `cost_micros` rounds up
(a cap must never under-count); `format_micros` rounds to nearest (a display
should be the closest true reading — rounding a single micro up would render it
as `$0.0001`, a hundredfold overstatement). Writing the tests first is what
surfaced those two rules being silently inconsistent.

**Migration 002 is the first to run against a populated database.** This file
previously recorded that no migration had ever crossed real user data.
`test_upgrade_preserves_an_existing_populated_database` now builds a v1 database
with runs and events in it and upgrades it. Confirmed live as well: a real data
directory came up at `user_version: 2` with `spend` and `settings` present.

**`--add-data` now globs `*.sql`.** The justfile named `schema.sql` explicitly,
which was correct while there was one migration. Adding 002 without noticing
would have produced a binary that starts and then dies on a missing resource —
invisible to `just ci`, to every dev run and to every test, because all of those
read the file off the source tree rather than out of the bundle. Same shape as
the Phase 1 and Phase 2 bugs: correct everywhere except where it ships.
`test_every_migration_file_is_bundled_by_the_packaging_glob` pins it.

**stdin now carries two protocols, and they cannot be confused.** The first line
is the JSON key handshake; every line after it is watched for `shutdown`. The
sentinel is not valid JSON, so a launch that sends no handshake at all —
`python -m agentspace` by hand — still starts and still stops. The handshake is
read on the reader thread rather than at startup on purpose: a blocking read
would turn a missing key into a sidecar that never binds its port.

### The bug worth remembering (Phase 3)

**Nothing dramatic broke — the existing guards fired instead.** Three mechanisms
already in the repo caught real mistakes, which is worth recording precisely
because it is the boring outcome:

- `test_no_api_keys_in_tracked_files` failed on the placeholder keys in the new
  provider tests. The guard was right and the placeholders changed; relaxing the
  pattern instead would have retired the one test that stops a real key being
  committed.
- ruff's `ARG001` caught a genuinely unused parameter in a parametrized test.
  The exemption then needed for protocol-conforming test doubles was therefore
  scoped to `ARG002` (method arguments) only, so `ARG001` keeps its signal.
- `mypy --strict` rejected a test double typed `list[object]` where the protocol
  says `list[ToolSpec]`. It was not conforming to the protocol it claimed to
  implement, so the test proved less than it appeared to.

The lesson is the inverse of Phases 1 and 2, where a check was missing and the
failure was invisible. Here the checks existed, and the cost of keeping them was
three small fixes rather than one weakened rule.

### What Phase 2 established, and how it was verified

**The gap-free guarantee is a property of the stream, not of the bus.** The bus
is an in-process hint that new rows exist; SQLite is the only authority. The SSE
stream keeps its own cursor and, on *any* anomaly — a sequence gap, a repeat, a
dropped buffer, a stale subscription — re-reads the range from the database
rather than reasoning about the cause. Two things make that necessary rather
than defensive:

- Appends commit inside `asyncio.to_thread` and can resume in either order, so
  events genuinely reach `publish` out of sequence under concurrency.
- Subscriber queues are bounded. A wedged client is marked stale and its buffer
  dropped, because the durable row makes the buffered copy worthless.

Subscribe happens *before* the backlog read. The reverse order silently drops
anything appended in between, and is invisible until the log is under load.

**`seq` is assigned inside one SQL statement** (`SELECT MAX(seq)+1` within the
`INSERT`, under `BEGIN IMMEDIATE`, with `UNIQUE(run_id, seq)` behind it), so
atomicity is a database property rather than something application locking has
to maintain. This was confirmed by mutation: rewriting the append as a
read-then-write race makes
`test_concurrent_appends_produce_a_gapless_sequence` fail, and the UNIQUE
constraint fires as the second line of defence.

**Migration 001 creates only `runs` and `events`.** §4 specifies three more
tables; they arrive in the phases that use them. A migration runner whose
second step never executes before release is untested machinery, so
`test_store_db.py` applies a synthetic migration 002 to prove stepping and
rollback-on-failure work.

### The bug worth remembering (Phase 2)

**A named SSE event never fires `EventSource.onmessage`.** Frames originally
carried `event: llm.token`, which is the more idiomatic-looking SSE. A webview
probe using `onmessage` then received **0 of 20** events while `fetch` against
the same endpoint received all 20 — the server was blameless and every terminal
test was green.

Named events require `addEventListener` for that exact name, so any type the
client has not registered is dropped with no error anywhere. With 26 event types
and more arriving each phase, that converts "someone forgot to update the
client" into invisible data loss in a UI whose entire contract is being a
faithful projection of the event log. Frames are therefore **unnamed**; the type
travels inside the JSON body, everything arrives on one `onmessage`, and an
unrecognised type reaches the reducer where it can be logged loudly.

This is the same lesson as Phase 1's CORS bug in a new costume: the failure was
invisible from a terminal and obvious from inside the webview. `curl` satisfied
the acceptance criterion perfectly while the webview received nothing.

**CORS is now asserted, not assumed.** `test_stream_cors.py` covers the packaged
app's `http://tauri.localhost` origin directly, including the preflight for
`Last-Event-ID` — which matters because the *initial* EventSource connection is
a simple GET and is not preflighted, while the *reconnect* is. Getting that
wrong yields a stream that works once and then dies silently at the first
resume, which from the UI is indistinguishable from a run that stopped emitting.

### What Phase 1 established, and how it was verified

Four traps from §5 Phase 1, each now covered by a test rather than a comment:

- **The `externalBin` filename is asymmetric.** The file in `binaries/` must
  carry the target triple (`agentspace-sidecar-x86_64-pc-windows-msvc.exe`) or
  Tauri never resolves it — but Tauri *strips* that triple when staging and
  installing, so the shipped file is `agentspace-sidecar.exe`. Looking for the
  built name inside the installer finds nothing and looks exactly like a
  bundling failure. `bundled_name()` in `test_installer_bundle.py` encodes both
  halves.
- **The orphaned sidecar.** `--onefile` means the PID Tauri holds is the
  bootloader's, not the server's. Shutdown never relies on signals: the shell
  writes `shutdown` to stdin and drops the handle. Verified on the *installed*
  app — two `agentspace-sidecar` processes while running (bootloader + real
  interpreter), zero one second after closing the window, port released.
- **Stale cached sidecar in the bundle.** Not trusted to the build log:
  `test_installer_carries_the_freshly_built_sidecar` unpacks the installer with
  7-Zip and compares SHA-256 against the freshly built binary.
- **WebView2 on machines that lack it.** `webviewInstallMode` is
  `embedBootstrapper`, and a test asserts `MicrosoftEdgeWebview2Setup.exe` is
  physically inside the installer.

### The bug worth remembering

The packaged app once looked completely healthy and was not. The window
rendered, the sidecar bound in half a second, and an HTTP request from
PowerShell returned `{"ok": true}` — while the page sat retrying at attempt 22.
The webview does not share an origin with the sidecar (Tauri serves from
`http://tauri.localhost` on Windows), and FastAPI sent no CORS headers, so the
browser fetched successfully and discarded the response.

**curl and `Invoke-WebRequest` do not enforce CORS; a webview does.** A green
HTTP smoke test proves the server answered, not that the client was allowed to
read the answer. It surfaced only from screenshotting the running app and
reading the retry counter. When Phase 7 adds SSE, expect the same class of
problem and test it from inside the webview, not from a terminal.

`ALLOWED_ORIGINS` in `config.py` is an explicit allowlist and must stay one — a
wildcard would let any page the user has open read from their agent workspace.

### Not verified

- **A machine with no Python installed.** The frozen sidecar was run with a
  minimal environment and no Python on `PATH` and served correctly, but this
  machine has Python. Genuine proof needs a second machine, which is Phase 9's
  acceptance criterion.
- **macOS.** Nothing has run there. CI is Phase 9.
- **Reinstall-over-existing at scale.** Three `/S` reinstalls over an existing
  install have now worked, each with a rebuilt sidecar. Still nothing like the
  number of upgrade cycles a released app sees, and no reinstall has yet
  happened across a *schema migration* — the case that matters once migration
  002 exists.

Phase 2 specifically:

- **The browser's own EventSource reconnect.** Resume was verified three ways —
  `curl` with an explicit `Last-Event-ID`, a webview `fetch` with the same
  header (which exercises the CORS preflight), and the unit tests. What was not
  forced is the browser *automatically* reconnecting a dropped EventSource and
  supplying the header itself. The server cannot tell the two apart, but the
  browser's retry timing and its handling of a stream that closes normally are
  untested. Phase 7 writes the real client; force a mid-run disconnect there.
- ~~**Backpressure against a real client.**~~ **Closed in Phase 4.** A 900-word
  streamed response overflows the 512-event queue while the client reads
  nothing; the subscription is asserted to have actually gone stale, and the
  client still receives a gapless 1..N. Consumed through `run_stream` rather
  than over HTTP — see the Phase 4 bug note for why an in-process HTTP client
  cannot do this.
- **Two simultaneous SSE clients on one run.** Covered on the bus, not through
  the HTTP layer against a live server. It becomes real in Phase 8, when a run
  is watched from the dashboard and a chat channel at once.

Phase 3 specifically:

- **No real API call has ever been made.** Every provider test runs against an
  `httpx2.MockTransport`. The request bodies are asserted against each vendor's
  documented shape, but no Anthropic, OpenAI or Ollama endpoint has actually
  answered one, so a wrong header name or a renamed field would pass the suite.
  Still true after Phase 4, and now the one thing blocking it — see the Phase 4
  list below.
- **Ollama has never been run.** No daemon was started. The provider exists to
  keep the abstraction free of cloud assumptions (§7), and it does that whether
  or not it works — but "it works" is not claimed.
- **The Rust keychain path is compiled, not exercised.** `cargo check` passes
  and `send_secrets` is wired into spawn, but nothing has stored a key in the
  Windows Credential Manager and watched it arrive. The *sidecar* half of the
  handshake was verified end to end by hand — a real secrets line on stdin, keys
  reported as configured by `/settings`, values absent from the log, the process
  and the database — so what remains untested is specifically
  keychain-read → stdin-write inside the packaged app. This is the gap the
  no-UI scope decision created, and it is exactly the class of thing Phases 1
  and 2 both got wrong from a terminal. **Phase 4 strengthened the sidecar half
  further** — a real Anthropic key travelled the handshake and drove a real run,
  after which no key material was present in the database, its `-wal`/`-shm`, or
  the process output — but the keychain read itself is still the untested step.
- ~~**The budget refusal has no HTTP path yet.**~~ **Closed in Phase 4.**
  `POST /runs` drives the orchestrator, so a run over the cap now fails with
  `budget.exceeded` in its own event log. It was enforced at the
  `BudgetedProvider` layer and unit-tested there, including the mutation check.
  Nothing over HTTP makes a model call until the orchestrator exists, so the
  refusal cannot yet be observed from outside the process.
- **`budget.warning` fires once per period, per the crossing test — but only
  within one process.** The before/after comparison reads the database, so a
  restart mid-month cannot re-fire it. Two runs appending concurrently at the
  threshold could, in principle, both observe the crossing; that race is not
  tested and becomes real in Phase 4.
- **Prices are list prices recorded on a date, not truth.** Anthropic rows come
  from the bundled `claude-api` reference (checked 2026-06-24), OpenAI rows from
  `developers.openai.com` (checked 2026-09-09). A stale row mis-counts the
  user's own cap; it never affects what a provider actually bills.

Phase 4 specifically:

- **OpenAI and Ollama have still never answered a real request.** Anthropic now
  has, and its shapes were correct. OpenAI's `stream_options.include_usage` is
  the remaining one that fails silently in the direction of under-billing — if
  it is wrong, every streamed OpenAI call records as free and the cap stops
  binding while the run works perfectly. Ollama has never had a daemon started
  against it at all.
- **The webview has never seen an orchestrated run.** Live SSE was verified with
  `curl` against a real uvicorn sidecar — including the `tauri.localhost` CORS
  preflight carrying `Last-Event-ID` — but the frontend is still the Phase 1
  shell, so no `EventSource` has consumed orchestrator events. This is exactly
  the shape of the Phase 1 CORS bug and the Phase 2 named-event bug, both of
  which were invisible from a terminal. Phase 7 writes the real client; do the
  check there rather than trusting the `curl` result.
- **Concurrency between agents.** Delegation is strictly sequential: a worker
  runs to completion before the supervisor's next turn. Nothing has ever
  appended events for two agents at once, so `seq` ordering has not had to
  carry any orchestration meaning. Parallel workers are a real feature and a
  real risk to the reconstruction guarantee; they are not in this phase.
- **The budget crossing race is still open, and is now reachable.** Phase 3
  noted that two runs appending concurrently at the 80% threshold could both
  observe the crossing. `POST /runs` now starts runs, so two concurrent runs is
  an ordinary thing a user can do. Untested.
- **Long transcripts.** `llm.request` carries the full message list, so a run
  that goes many steps writes the conversation into the log repeatedly, growing
  quadratically. Correct for reconstruction and untested for size. Nothing has
  run long enough to care yet.
- **A worker-initiated `handoff` does not re-delegate.** It records
  `agent.handoff`, completes the worker, and hands the request back to the
  supervisor as text for it to act on. The event is real; the automatic
  follow-through is not implemented, and no test asserts the supervisor
  actually does anything sensible with it.

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

`packages/schemas/` (generated TS types) arrives in Phase 7. It is absent rather
than stubbed, because BUILD_SPEC §5 says do not build ahead.

The backend now also holds `store/` (SQLite + migrations and workspace
settings), `events/` (types, store, bus), `providers/` (protocol, pricing,
Anthropic/OpenAI/Ollama, factory), `budget/` (the monthly cap) and `api/`
(runs, stream, settings), per the §3 layout. `secrets.py` sits at the package
root because it is process-wide state, not storage — keys never reach the
database.

Phase 4 added `orchestrator/` — `run.py` (lifecycle, the event sequence, the
mailbox), `supervisor.py`, `agent.py`, plus two modules §3 does not name:
`limits.py` (the run ceilings) and `control.py` (the tool vocabulary an agent
may call). `registry.py` is Phase 5 and is absent rather than stubbed.
`tools/` is still empty: it belongs to Phase 6 with the approval gate.

## Decisions made mid-build

Recorded here as they happen, so a later session does not re-litigate them.

- **2026-09-09 — a worker's result travels through SQLite, not up the call
  stack.** §5 Phase 4 says agents communicate via `agent.message` events and
  never direct function calls, which taken literally is impossible — some
  object has to call some other object. `Mailbox.deliver` appends the event and
  `Mailbox.collect` reads it back out of the database, so the *content* never
  moves in a Python variable. Slower than returning a string, and the reason
  the acceptance criterion is structural rather than aspirational. See the
  Phase 4 notes for the mutation that proves it.
- **2026-09-09 — `max_agents_per_run` refuses the spawn instead of failing the
  run.** §5 says every limit "emits a terminal event when hit", and the strict
  reading would kill the run. Asked before deviating (§6): a supervisor asking
  for one worker too many should not destroy work already done, and a
  supervisor that loops on retrying hits the step limit anyway. The other two
  limits are forced by §4's closed event list — no `agent.failed` exists, so
  the step limit *completes* an agent with a reason.
- **2026-09-09 — control-flow tools live in `orchestrator/control.py`, not in
  `tools/`.** Phase 4 needs the agent loop to call *something*, and §1
  constraint 5 forbids any filesystem/shell/network call that does not pass the
  approval gate — which is Phase 6. So this phase offers only calls that touch
  nothing: `finish`, `handoff`, `spawn_agent`. Building `tools/base.py` now
  would pre-empt the risk model and sandbox that Phase 6 owns. The
  `tool.requested` → `tool.called` → `tool.result` sequence is real, so Phase 6
  adds approval events between the first two rather than reshaping it.
- **2026-09-09 — `Provider` gained `stream()`, and `BudgetedProvider` wraps
  it.** Deferring streaming would have left `llm.token` emitted by nothing but
  the debug script, left the queue-overflow question untestable, and meant
  rewriting the agent loop later rather than extending it. Wrapping only
  `complete()` in the budget guard would have left the cap binding nothing the
  orchestrator actually calls, with every Phase 3 test still green.
- **2026-09-09 — streamed spend is recorded before the terminal completion is
  yielded.** After would be the natural order, and it loses the charge whenever
  a consumer stops iterating as soon as it has the completion — which is a
  perfectly reasonable thing to write.
- **2026-09-09 — the run limits are `settings` rows, not constants.** §5 says
  "all configurable". The `settings` table already exists, so this is three new
  keys and no migration. `RunLimits` is resolved once at run start, frozen, and
  written into `run.started` — a run must not be held to different rules at
  step 1 and step 12, and a replay has to be able to say what the rules were.
- **2026-09-09 — `POST /runs` starts the orchestrator and returns immediately.**
  Holding the request open for the length of a run would make the response a
  second way to learn what the event stream already says, and would put a
  proxy's idle timeout in charge of when a run ends.

- **2026-09-09 — the data directory is derived from the bundle identifier, not
  `APP_NAME`.** Tauri's per-user NSIS installer installs into
  `%LOCALAPPDATA%\<productName>` — `%LOCALAPPDATA%\AgentSpace` — which is
  byte for byte where an `APP_NAME`-derived data directory resolved. The event
  log would have lived *inside the installation*, to be deleted by an uninstall
  and put at risk by every upgrade. Found empirically: a stray
  `agentspace.sqlite3` turned up in the installed app's own directory. It now
  resolves to `%LOCALAPPDATA%\dev.agentspace.desktop`, which is also exactly
  what Tauri's `app_data_dir()` returns, so the injected value and the fallback
  name the same place instead of differing by one directory. A test asserts the
  identifier still matches `tauri.conf.json`.
- **2026-09-09 — the shell calls `app_local_data_dir()`, not `app_data_dir()`.**
  On Windows `app_data_dir()` is `%APPDATA%` — the *roaming* profile, copied to
  and from a server on every logon in a domain environment. Roaming a live
  SQLite database, its `-wal`/`-shm` files, an agent workspace and logs invites
  corruption and bloats every logon. Caught by installing the packaged app and
  looking at where the file actually landed: it was in `%APPDATA%`, while the
  sidecar's own fallback computed `%LOCALAPPDATA%` — the exact silent
  divergence the previous entry claims to prevent. Both are now
  `%LOCALAPPDATA%\dev.agentspace.desktop`.
- **2026-09-09 — an autouse fixture isolates every test's data directory.**
  The stray database above was written *by the test suite*: `create_app()` with
  no explicit paths falls back to the real OS app-data directory, so any test
  building an app without passing paths wrote to the developer's machine.

- **2026-09-09 — migration 001 creates only `runs` and `events`.** §4 specifies
  five tables. Creating `spend`, `agent_defs` and `approvals` now would satisfy
  the data model in one step but leave the migration runner with exactly one
  migration, forever — the second step would first execute on a user's machine
  during an upgrade. They arrive in Phases 3, 5 and 6 as migrations 002+.
- **2026-09-09 — SSE frames carry no `event:` field.** See "The bug worth
  remembering (Phase 2)". The type is in the JSON body; a named SSE event would
  silently bypass `onmessage` for any type the client had not registered.
- **2026-09-09 — one SQLite connection behind a `threading.Lock`, not a
  connection per thread.** Thread-local connections scale better and are wrong
  here: pool-thread connections are never deterministically closed, and on
  Windows an open handle keeps the database file locked, which breaks both test
  teardown and installer replacement. Operations are sub-millisecond and every
  async caller arrives via `asyncio.to_thread`, so the loop never blocks.
- **2026-09-09 — the Tauri shell defers to an inherited `AGENTSPACE_DATA_DIR`.**
  §5 Phase 2 asks for the data directory to come from Tauri's path API, and it
  does — but only when the variable is unset. Overriding unconditionally would
  have moved dev state out of `.dev/data` and quietly contradicted the layout
  table above.
- **2026-09-09 — `pytest-timeout` with a 60 s cap.** An SSE stream that fails to
  terminate hangs the suite instead of failing it, and would hang the Phase 9 CI
  job. It earned its place immediately: it caught a real defect where a client
  resuming past the head of an already-completed run waited forever, because the
  stream only learned a run was over by *seeing* its terminal event. The stream
  now also checks the run's status.
- **2026-09-09 — a `settings` table, beyond the five §4 specifies.** The Phase 3
  acceptance criterion needs the provider choice to live somewhere, and §4 has
  no table for it. A file beside the database would split authority between
  SQLite and the filesystem, which §2 is explicit about. Key/value with a JSON
  `value`, so Phase 7's settings UI and Phase 8's channel config do not each
  need a migration that widens a table. Additive only — it changes nothing §4
  specifies. Asked before deviating, per §6.
- **2026-09-09 — raw `httpx` against both REST APIs, not the vendor SDKs.**
  Normalizing token usage and tool calls is required by §5 Phase 3 either way,
  so the SDKs would save little of the actual work while adding two large
  dependency trees to a `--onefile` binary and two new hidden-import problems at
  freeze time. The distribution is `httpx2` and the module it provides is
  `httpx2`, not `httpx`; it moved from a dev-only dependency (it arrives under
  Starlette's TestClient) to a runtime one.
- **2026-09-09 — prices are micros per *million* tokens, not per token.**
  Published prices include $2.50 and $0.05 per million, which are 2.5 and 0.05
  micros per token — not integers. Storing the per-million figure keeps every
  price exact and moves the single division to the point of charging, where the
  rounding rule can be stated explicitly.
- **2026-09-09 — the budget guard is a Provider wrapper.** `BudgetedProvider`
  makes "check before the call" structural rather than a rule Phase 4 has to
  remember. See the Phase 3 notes above for the mutation test that keeps it
  honest.
- **2026-09-09 — the secrets handshake is read on the stdin reader thread.**
  §5 Phase 3 wants keys over stdin at spawn. Reading them in `run()` before
  starting the server would hang any launch that sends no handshake — a hand-run
  `python -m agentspace`, or a shell that died between spawn and write — turning
  a missing key into a sidecar that never binds and never says why. The wire
  protocol is unchanged: first line is the handshake, the rest is the watchdog.
- **2026-09-09 — `tauri-plugin-keyring` rather than the `keyring` crate direct.**
  §5 Phase 3 names the plugin, and inspecting it showed it exposes `KeyringExt`
  to Rust as well as JS commands — so one dependency serves both the spawn-time
  read and Phase 7's settings UI. It is a 0.1.0 single-author crate, which is
  worth knowing; it wraps `keyring` 3.6 with `windows-native`.
- **2026-09-09 — `--add-data` globs `*.sql` instead of naming `schema.sql`.**
  See the Phase 3 notes. Naming files individually means each new migration
  needs a justfile edit whose omission is invisible until the packaged binary
  runs.
- **2026-09-09 — Vite's dev watcher ignores `src-tauri/**`.** `tauri dev` runs
  cargo and Vite against the same tree; Vite's watcher opens `target/` files
  while cargo is still writing them, and on Windows the resulting EBUSY is
  raised as a fatal error that kills the dev server and takes `tauri dev` with
  it. Nothing under there is a frontend source file.

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
- **2026-09-09 — CORS allowlist rather than a Tauri HTTP proxy.** The webview
  reaching the sidecar over plain `fetch` needs CORS headers. The alternative
  was routing every call through a Rust command. Direct `fetch` keeps the
  frontend ordinary — which matters when Phase 7 needs `EventSource` for SSE,
  something a Rust proxy would have to reimplement.
- **2026-09-09 — Tauri bundler tools stay on the system drive.** `tauri build`
  downloads NSIS and the WebView2 bootstrapper into `%LOCALAPPDATA%	auri`
  (8.5 MB, one-time). Tauri resolves that path through `dirs::cache_dir()` with
  no override, so unlike the cargo/uv/npm caches it cannot be redirected into
  `.dev/`. Small enough to accept; recorded so nobody re-investigates.
- **2026-09-09 — `.dev` added to the hygiene test's pruned directories.**
  Package caches contain vendored `.sh` files, which would have failed
  `test_no_shell_or_batch_scripts` for reasons unrelated to this repository, and
  walking gigabytes of cache would make the suite slow enough to stop being run.
  A test asserts the walker never descends into `.dev`.
