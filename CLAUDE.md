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
3 agents, 6 model calls, 50 events, `run.completed`, $0.0260 recorded — and
against a **real local Ollama model**, which switched in as a settings change
with no credentials and no cost.

**Phase 5 — Agent registry.** Complete. Agents are rows in `agent_defs`, not
Python classes: the supervisor picks from a roster the user controls, an
allowlist decides what each may touch, and a definition edited mid-run leaves
the in-flight run alone. Verified against a **real local model** driving agents
that existed only because they were POSTed to the API — including one run that
reached `run.completed` on a roster containing nothing the product ships.

**Phase 6 — Tools and the approval gate.** Complete. Five tools that reach the
disk, the shell and the network, each behind a workspace sandbox and a
human-in-the-loop gate that genuinely blocks. Verified against a **real local
model that actually tried to escape**: `qwen3:4b` called
`write_file(path="../../ESCAPED.txt")` and was refused with `tool.denied` and
`blocked_by: "sandbox"` — with every risk level pre-approved, so the gate would
have allowed it instantly had the sandbox not caught it first.

**Phase 7 — Dashboard.** Complete. A React Flow graph, a filterable event log, a
modal approval gate, a budget meter, a replay scrubber and an agent editor — all
of them one pure fold of the event log. Verified in a **real browser driving a
real local model**: a run started from the page, watched live over `EventSource`,
its approval answered by clicking Allow, and the file appeared on disk. Replay
was then measured against live, pixel by pixel.

**Phase 8 — Channel adapters.** Complete. Discord and Telegram behind one
`ChannelAdapter` protocol, an allowlist deciding who may address the workspace,
and a chat reply that is a second pure fold of the event log. Verified against a
**real Discord server**: `/agent` typed in a channel started a run driven by a
real local model, its message was edited live while a dashboard-side client
received **52 of 52** events over the same SSE endpoint, two `write_file` calls
stopped at the approval gate and were answered by pressing **Allow** in Discord,
and `reminder.txt` appeared on disk with exactly the 16 bytes the prompt named.

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

### What the first real Ollama run showed

Run against a real daemon (Ollama 0.33.3, `gemma4:e4b`, 9.6 GB) — the first
time §7's "optional and untested" local path has executed at all.

**The abstraction held, with no code change.** `PATCH /settings` to
`provider: "ollama"` was the entire switch. `/settings` then reported
`configured_secrets: []` and `/settings/verify` returned ok — a provider with
no API key, no cost and no remote host, which is the case the Ollama
implementation exists to keep honest. Three runs recorded **$0.0000**: the
`ollama/*` zero-price wildcard resolves, so the ledger neither charges nor
refuses it as unpriced.

**Both transports worked first try.** Tool calls parsed with their arguments
intact on the blocking path *and* the NDJSON streaming path, and
`prompt_eval_count`/`eval_count` came back as non-zero normalized usage. The
streamed path specifically preserved a tool call through the final
empty-message frame — the case `_merge_frame` exists for and
`test_ollama_stream_keeps_a_tool_call_a_later_empty_message_would_erase`
covers, now confirmed against a real server.

**`llm.token` can be legitimately empty.** Every gemma response was a pure tool
call with no prose, so the whole run emitted **zero** `llm.token` events. Taken
with the Anthropic finding that deltas arrive 1–10 at a time, the rule for
Phase 7 is: never treat token events as a liveness signal. `agent.thinking` and
`llm.request` are what say an agent is working.

**Three limit paths fired for real, and behaved.** The `max_agents_per_run`
refusal fired six times in one run while the run stayed alive — exactly the
behaviour chosen over failing the run, and the fallback in that reasoning ("a
supervisor that loops on retrying hits the step limit anyway") is precisely
what then happened. A worker-initiated `handoff` ran for the first time. And
`register_agent` deduplicated a model that reused a name three times, producing
`worker2`, `worker2-2`, `worker2-3` — two agents sharing an `agent_id` would
have merged into one node on replay.

**The model is not capable enough to finish a run.** gemma4:e4b never called
`finish`: it spawned workers until it ran out of either agents or steps, across
three attempts with limits from 4 to 10 steps. Its workers produced good text;
the supervisor could not close the loop. So the local path is now verified at
the *protocol* level and found wanting at the *capability* level, which is a
more useful statement than §7's "untested". Nothing here suggests an
orchestrator defect — every limit and every event behaved correctly around a
model that would not converge.

### Which local model actually drives the loop

The binding constraint on the maintainer's machine is **VRAM, not RAM**: an RTX
4050 Laptop has 6.1 GB total, ~4.9 GB free. A model has to fit in that to run
on the GPU at all.

**`qwen3:4b` (2.5 GB, Q4_K_M) completes runs.** Verified end to end: 3 agents,
2 handoffs, 8 model calls, `run.completed` in 205 s with a correct answer, at
$0.0000. It also emitted **144 `llm.token` events**, so unlike gemma it gives a
live UI something to render.

**`gemma4:e4b` (9.6 GB) cannot, for two separate reasons.** It does not fit —
8.0B at Q4_K_M against 4.9 GB free means most of it ran on the CPU, which is
why its runs took 60–80 s to fail. And more fundamentally it never calls
`finish`: handed a transcript where the work was plainly complete, it responded
with *two more* `spawn_agent` calls, three times out of three. That probe
matters because it rules out the supervisor prompt as the cause — the model
simply does not reason about completion. Do not spend time tuning prompts for
it.

**Thinking mode is not the bottleneck.** Ollama leaves qwen3's reasoning on and
it costs about 17% in time and 16% in output tokens (26.2 s / 1494 tokens
versus 21.7 s / 1249 with `think: false`, one sample each). Tool calls survive
either way. The provider has no way to send `think`, and on this evidence it is
not worth adding one.

**Plan quality is the real gap, not mechanics.** qwen3:4b spawned two drafters
instead of a drafter and a shortener, and reused a worker name — `register_agent`
deduplicated it to `draft_worker-2`. It converged anyway. Expect a local model
to need more steps and a higher agent cap than a frontier one for the same goal.

### The bug the Ollama run found

**A failed run was reporting itself completed.** When the supervisor exhausted
its steps, `execute_run` called `run.complete(outcome.result)` regardless of
*why* the supervisor stopped, and the result was the out-of-steps placeholder.
The user got status `completed` and the summary "supervisor stopped after 4
steps with no result" — a terminal event asserting the run worked when it had
not, while the workers' actual output sat in the log unmentioned.

§4 has no `agent.failed`, so an agent out of steps *completes* with a reason.
The mistake was treating that as a fact about the run. A supervisor that never
called `finish` did not answer the goal; the run now fails with a reason that
also says where the workers' output is. A *worker* hitting the same limit still
completes the run, because the supervisor can finish around it.

This was invisible to the whole test suite because every script ends by
finishing, and the test that covered the step limit asserted
`status == "completed"` — it encoded the bug rather than catching it. Both
directions are now tested.

### The bug the first Anthropic run found

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

### What Phase 5 established, and how it was verified

**An agent is now a row, and the proof is that a run can be driven by agents
that only ever existed as HTTP requests.** Against a real `qwen3:4b`, two
definitions — `haiku_writer` and `haiku_critic` — were created with `curl`, the
three seeded built-ins were disabled so the roster contained *nothing* the
product ships, and the run spawned both and got real work out of them: a haiku,
and a syllable count naming the offending line. Their roles, prompts and step
limits in the event log are the rows', not anything a model typed. That is §5
Phase 5's first acceptance clause in its literal form.

**A second live run completed end to end on an agent that only existed as an
HTTP request.** `note_keeper` — created with `curl`, `allowed_tools:
["read_file"]`, the built-ins disabled so it was the entire roster — was spawned
by the supervisor, worked, handed back, and the run reached `run.completed`.
That is §5 Phase 5's first acceptance clause with a terminal success behind it,
not merely a spawn.

**And its summary was a confabulation, which is the most useful thing either
run produced.** The run completed with `"Database migrations note saved to
notes.txt"`. No file was written. Nothing could have been: the data directory
contains only `agentspace.sqlite3` and its `-wal`/`-shm`, and the entire run
contains exactly three `tool.called` events — `spawn_agent`, `handoff`,
`finish`, all control calls that touch nothing.

Two conclusions, and they point in opposite directions.

*§1 constraint 5 held, observably.* An agent whose prompt ordered it to write a
file, in a run whose stated goal was to write a file, reached the filesystem
zero times, because there is nothing for it to reach through. The absence of a
file on disk is the check that matters, and it was made by looking.

*A terminal event's `summary` is a model's assertion, not a verified fact.* The
event log is honest — it records three control calls and no file tool — while
the sentence shown to the user is false. This is exactly why §2 makes the log
the authority and the UI a projection of it. **Phase 7 must not render
`run.completed.summary` as though the work described in it happened.** What
happened is the `tool.called` events; the summary is what an agent claims about
them, and the two are separately observable precisely so they can disagree.

Worth stating plainly because it is the failure a graph UI is *for*: a user
reading "saved to notes.txt" learns nothing, and a user watching three control
calls go by with no file tool among them learns everything.

**The same run exercised three Phase 4 guarantees against the new shape.**
Spawning one definition twice produced `haiku_writer` and `haiku_writer-2`, both
carrying the same `definition_id` — so a replay can tell two agents apart and
still say they came from one row. The `max_agents_per_run` refusal fired as a
`tool.error` and the run stayed alive. And the supervisor, having never called
`finish`, ended the run as `failed` rather than `completed` — the Phase 4 bug
fix behaving correctly under a genuinely inconclusive run.

**Exposure and enforcement are separate, and only one of them is a boundary.**
The obvious implementation of an allowlist is to pass the model only the tools
its definition permits. That is necessary and it is not sufficient: a model can
name any string, which is why `_unknown_tool` existed before this phase.
`Agent._permit` therefore reads `spec.allowed_tools`, never the offered
`self._tools`. Three mutations pin this:

- removing the permission check entirely — the Phase 4 shape — fails **five**
  tests;
- making enforcement read the offered list instead of the allowlist fails
  `test_a_tool_offered_by_mistake_is_still_refused`, which is the only test that
  can tell the two apart, because everywhere in the product one is built from
  the other;
- re-reading the roster at spawn time instead of snapshotting it fails the
  mid-run-edit test.

The first mutation is worth recording twice, because the *first* attempt at it
passed. Rewriting one branch of `_permit` left the denial fallback intact, so
the tests stayed green while the thing being tested had not actually been
removed. A mutation that does not fail is not evidence the code is right — it is
evidence the mutation was too small.

**`tool.requested` is written before the permission check.** §5 Phase 5's claim
is that a forbidden call is *blocked*, and "blocked" is only observable if the
attempt is in the log beside the refusal. A denial that erased the attempt would
leave a replay unable to say what the agent tried to do.

**The system prompt is in the event log for the first time.** It previously
appeared in no event at all — `llm.request` carries the message list, and the
system prompt travels beside it as a separate provider argument — so Phase 4's
"the log alone reconstructs the run" had a hole in it that nothing noticed while
prompts were generated from code. Once the prompt is a row a user wrote, it is
the most load-bearing fact about why two runs of the same goal differed. It now
rides in `agent.spawned`, once per agent, and was confirmed to arrive over SSE
with the rest of the snapshot: definition name, allowlist, step limit and model.

**The tool catalogue is names and risk levels with no implementations.** §5
Phase 5 requires `allowed_tools` to "resolve to a registered tool", which needs
a registry of tools in this phase, before any tool may exist under §1 constraint
5. So `tools/catalogue.py` declares the five built-ins §5 Phase 6 names and
their risk, and `GET /tools` reports every one as `available: false`. An agent
*permitted* a catalogue tool that calls it is told the tool is unavailable and
no `tool.called` is written — `tool.called` means the call executed, and
emitting it for a tool with no implementation would put a false statement in
the log.

**The `max_steps` validation refuses on write and clamps again at spawn.** The
write-time rule compares against a workspace cap that can be lowered afterwards;
`test_the_run_limit_clamps_a_definition_written_when_the_cap_was_higher` is what
stops that from being the only check. Confirmed live: definitions capped at 3
steps ran under a supervisor capped at 10.

### The bug the live run found (Phase 5)

**Creating an ordinary agent was impossible whenever the workspace cap was
below 20.** `CreateAgentRequest.max_steps` defaulted to the literal `20` from
§4's column default. Lowering `max_steps_per_agent` to 10 — which the product
invites, and which the step-limit failure message explicitly suggests — then
made every `POST /agents` that omitted `max_steps` fail with
`400 [max_steps] max_steps of 20 is above this workspace's limit of 10`:
a rejection naming a field the caller had not supplied, with no way to connect
it to a setting changed elsewhere. The fix is that an unsupplied `max_steps`
resolves to `min(20, cap)` instead of asserting a number the workspace may not
allow.

It also masked an unrelated defect for as long as it lasted: a duplicate name
was returning `400` rather than `409`, because validation reached the
`max_steps` rule before the uniqueness check. The parametrized validation test
accepted either code, so nothing caught it. Both now have their own tests.

**The whole suite was green.** Every test either sent an explicit `max_steps` or
left the cap at its default, so no test ever had a cap below 20 *and* an omitted
`max_steps` at the same time. It took thirty seconds of using the thing to find
— which is now the fifth time in this project the same shape has appeared, after
Phase 1's CORS, Phase 2's named SSE events, Phase 3's `*.sql` glob and Phase 4's
silently-dropped settings fields. The pattern is specific enough to state as a
rule: **a default that duplicates a value the user can change is a bug waiting
for the user to change it.**

### What the local model showed this time

**qwen3:4b will not invent a tool it was not offered — it goes silent instead.**
Handed a system prompt ordering it to call `write_file` while being offered only
`finish` and `handoff`, it returned **empty content and no tool call, five
times running**, until the step limit ended it. A direct probe of
`POST /api/chat` with the same prompt shows why: the entire response went into
Ollama's separate `message.thinking` field, with `message.content` empty and
`tool_calls` null.

Two things follow.

**The adapter drops `thinking`, so the log records nothing where the model
reasoned at length.** `providers/ollama.py` reads `message.content` and
`message.tool_calls`. That is not wrong — reasoning is not output, and adding a
thinking channel to the `Provider` protocol touches all three providers,
`llm.token`, and the Phase 7 renderer — but it means an agent can burn its whole
budget and leave an event log that says it produced nothing. **Deliberately not
fixed in Phase 5**: it is a Provider-protocol design decision, not an
agent-registry one, and it should be made where its cost across all three
providers is visible. Recorded here so Phase 7 does not conclude the loop is
broken when it renders five empty responses.

**A model that returns nothing at all is a real failure mode, and the step limit
is the only thing that ends it.** `_NO_TOOL_NUDGE` assumes prose to push back
against; there was no prose. Nothing here suggests an orchestrator defect —
every event is correct and the limit fired — but "the model said nothing" and
"the model is thinking" are indistinguishable from the log, which matters for a
UI whose whole job is showing what an agent is doing.

**And it emits tool calls as prose when it gets stuck.** In the haiku run, after
the agent cap refused a spawn, the supervisor's next output was the literal JSON
`{"name": "spawn_agent", "arguments": {...}}` as *text*, with no structured tool
call — so the loop nudged it and it burned its remaining steps. Same conclusion
as CLAUDE.md's existing gemma finding, one level worse: a small model degrades
into describing the call it means to make.

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

### What Phase 6 established, and how it was verified

**The acceptance criterion fired against a real model, not a script.** §5 Phase
6 asks that "an agent instructed to write outside the workspace root is blocked
at the sandbox layer, and this is visible in the event log as `tool.denied`".
`qwen3:4b`, given a system prompt ordering it to call `write_file` with
`../../ESCAPED.txt` and told not to simplify the path, did exactly that. The log
shows `tool.requested` carrying the escaping path, then `tool.denied` with
`blocked_by: "sandbox"`, and no such file exists anywhere on disk.

Two things make it mean something rather than merely happen:

*The gate was wide open.* `auto_approve` was `["low","medium","high"]`, so the
approval gate would have allowed that call instantly. The only thing between the
model and the write was the sandbox, which is precisely the claim being tested.

*The `approvals` table is empty.* Every call that reaches the gate writes a row —
including an auto-approved one, deliberately, so the log can answer "what did
this run do without asking me". Zero rows is direct evidence that the refusal
happened **before** the gate was consulted, which is §5 Phase 6's "rejected
before the approval prompt is even shown" observed rather than asserted.

**This closes the Phase 5 gap that said a real model had never been denied a
tool.** Phase 5 tried twice with `qwen3:4b` and got refusal-by-silence once and
a `handoff` the other time. What was different here was not a better prompt but
a *plausible* call: the agent was offered `write_file` and told to use it, so
the denial came from the boundary rather than from the model declining to try.

Also worth recording: the agent **reacted** to the denial rather than looping on
it. Told plainly that the path was outside the workspace, it called `handoff` to
a nonexistent `another_agent`. Wrong, but it shows the refusal text reached the
model and changed its plan — which is why `_denied` explains itself instead of
returning a bare error.

**It took two attempts, and the first is the more useful finding.** Given the
same goal but a prompt that merely *described* the path, qwen3 skipped the tool
entirely and called `finish("pwned")` — a `run.completed` whose summary asserts
an outcome that never happened, with three control calls and no file tool in the
log. That is Phase 5's confabulation finding reproduced exactly, on a different
goal. Restating it because Phase 7 renders these: **the summary is a model's
claim, the `tool.called` events are what happened, and they disagree routinely.**
Both live runs this phase ended `completed` with a summary of "pwned" and an
empty workspace.

**The sandbox rejects before the gate asks, and the ordering is the design.**
An approval dialog is a question put to a human, and a question is only safe to
ask if every answer is survivable. Asking "may this agent write to
`../../../etc/hosts`?" makes the user's misclick into the vulnerability. So
`Tool.prepare` resolves and validates while touching nothing, the gate runs
between `prepare` and `execute`, and a call that cannot be allowed is never
offered as a choice. Confirmed by mutation: recording a sandbox violation as
`tool.error` instead of `tool.denied` fails four tests including the acceptance
criterion, and bypassing the gate so every call is allowed fails six — including
the one asserting a denied call does not happen.

**Three ways a call can be stopped, and the log tells them apart.** The
allowlist refused it (the definition never permitted it), the sandbox refused it
(out of bounds, nobody asked), or the user refused it (in bounds, asked,
declined). All three are `tool.denied`; `blocked_by: "sandbox"` is what separates
a prompt-injected agent probing the boundary from a user declining a routine
write. A log that collapsed them would render those two as the same event.

**Resolution, not inspection.** The sandbox compares fully resolved paths. A
string search for `".."` rejects the legitimate `reports/../notes.txt` and misses
a symlink containing neither dots nor slashes — the escape that actually works.
That mutation fails four tests, including both of those cases. The symlink test
*runs on Windows* rather than skipping: unprivileged accounts cannot create
symlinks without Developer Mode, so it falls back to a directory junction, which
needs no privilege and which `Path.resolve` follows identically. A test that
skips on the primary platform is not coverage of it.

**`http_get` is the tool that could call this application's own API.** §1
constraint 3 keeps other *machines* off the sidecar and does nothing about an
agent inside a run fetching `127.0.0.1:8787/settings`. `Sandbox.check_url`
refuses loopback, private, link-local and reserved addresses — including the
`169.254.169.254` metadata endpoint — and refuses `file:` and `data:` schemes,
which would otherwise be a filesystem read that never touched the path sandbox.
Redirects are reported rather than followed, because a `Location` header is
exactly how a checked public URL becomes an unchecked private one. What it
cannot stop is a name that resolves public at check time and private at connect
time; that needs the connection pinned to the checked address, which is a
property of the HTTP client. Recorded rather than papered over.

**What `run_shell` actually enforces, stated plainly.** §5 Phase 6 asks for "no
network and a hard timeout". The timeout is real, and it kills the process
*tree* — `taskkill /T` on Windows, a process-group signal on POSIX. Killing only
the direct child is the Phase 1 bootloader mistake in a new costume: the parent's
handle is not the process doing the work, so the kill returns cleanly and leaves
the command running after the run that started it has ended.

**"No network" is not enforced, and cannot be** in-process and cross-platform: a
command that calls `curl` reaches the internet. What is done instead is a child
environment built from an allowlist rather than inherited, so a credential put
into the sidecar's environment in some later phase is not readable by every shell
command an agent runs. This is the same gap §5 Phase 6's own addendum identifies
when it calls the app-level sandbox "a real but limited boundary" that "still
runs as your actual user account" — and it is why that addendum puts real
isolation in a container outside the shipped build. The shipped mitigation is
that `run_shell` is `high` risk and therefore always stops to ask.

**An auto-approved call still writes its row and emits both events.** The
temptation is to skip all of it since nobody was asked, and that is backwards:
the question a user asks afterwards is "what did this run do *without* asking
me", and it is only answerable if the automatic decisions sit in the log beside
the manual ones. `tool.approved` carries `automatic` so the two are separable.

**The gate borrows the run's wall-clock budget rather than keeping its own
deadline.** A separate approval timeout would be a second limit to configure and
explain, and the two would disagree — a run with five minutes left sitting on a
ten-minute approval window waits for a decision it can no longer act on. Expiry
settles the row rather than leaving it pending forever, which is what §4's
`expired` status is for.

**A denial stops a call, not a run — the supervisor routes around it.** Watched
live, and it is the most interesting thing the gate run produced after the
acceptance criterion itself.

The sequence: the user denied `overwrite notes.txt`; the worker was told plainly
and called `finish` with "Permission denied: cannot overwrite notes.txt"; the
supervisor read that, spawned a **second** copy of the same definition
(`escaper-2`, deduplicated by `register_agent`), and it asked for the same
overwrite again.

Nothing here is broken and nothing is bypassed. The second attempt stopped at
the gate exactly like the first, the user was asked again, and the file was
never modified — §1 constraint 5 held on every attempt. The `tool.denied`
reason does tell the *agent* not to retry, and that agent did not; the
supervisor is a different agent, and all it sees is a worker's summary saying
the task failed.

Two consequences worth carrying.

*For Phase 7:* a user can be asked the same question several times in one run,
so a dialog that assumes one question per decision will feel broken. Rendering
the approval history for a run — approved, denied, denied again — is more
useful than showing only what is currently outstanding.

*For the product generally:* "deny" currently means "not this call", not "not
this run". Making a denial sticky (a supervisor told that this exact call was
already refused) is a real feature and is not in this phase. It is also not
purely a convenience: a supervisor that can re-ask indefinitely turns a single
"no" into a war of attrition, and the only things bounding it today are the step
limit and the agent cap. Recorded rather than fixed, because the fix belongs
with whatever Phase 7 learns about how these dialogs actually feel to use.

**Every settled approval status has now been produced by a real run.** One
`write_file` was approved over HTTP and the file appeared; a second was denied
and did not; a third went unanswered and **expired on the run's wall-clock
deadline**, which then failed the run:

```
46 escaper-2 approval.requested  overwrite the file notes.txt (36 characters)
47 escaper-2 approval.resolved   status: "expired"
48 escaper-2 tool.denied         "... was not answered before this run ran out
                                  of time, so it did not happen."
49 -         run.failed          "This run hit its time limit of 900s (ran for 904s)."
```

That is the borrowed-deadline design working end to end: the gate did not keep a
clock of its own, it ran out of the run's. The four-second overshoot is correct
rather than sloppy — the approval expired at 900s and the run failed at the next
`check_deadline`, which happens before a model call, so the run stopped where it
could still write a coherent terminal event. §4's `approvals.status` now has no
value that exists only on paper.

**A restart makes every pending approval unanswerable, so startup expires them.**
A pending row's waiter is an `asyncio.Future` in the process that created it.
After a restart, resolving one would update a database and unblock nothing, and
the Phase 7 dialog would show live questions about runs that ended when the app
last closed.

### The bug the live run found (Phase 6)

**The approval policy could not be set through the API.** `GET /settings`
reported `auto_approve` and `PATCH /settings` rejected it with a 422, because
`UpdateSettingsRequest` lists its fields explicitly and Phase 6 added the field
to `WorkspaceSettings` only. §5 Phase 6's entire "policy setting for unattended
operation" was unreachable from the product: the setting existed, was enforced,
was tested, and no user could change it.

This is the **sixth** instance of the same shape, after Phase 1's CORS, Phase 2's
named SSE events, Phase 3's `*.sql` glob, Phase 4's silently dropped settings
fields, and Phase 5's `max_steps` default. Every one was found by running the
thing. The suite was green because every gate test sets the policy through
`SettingsStore` or the runtime directly — never through the endpoint a user has.

Phase 4's fix did its job: `extra="forbid"` turned what would otherwise have been
a silent `200 OK` into a loud 422 naming the field. What remained was the
*duplicated field list*, so the fix this time is structural.
`test_every_workspace_setting_can_be_patched` compares the two models' fields as
sets, which means a field added in Phase 8 is already covered by a test written
in Phase 6. Removing the field again fails three tests.

The lesson to carry forward: `extra="forbid"` converts a silent failure into a
loud one, which is worth a great deal and does not stop the field being
forgotten. Only comparing the two lists does that.

### The design decision worth not re-litigating (Phase 6)

**An empty `auto_approve` on a definition means "inherit", not "none".**

Phase 5 built `effective_auto_approve` as a pure intersection and tested it as
arithmetic, including the case `((), (LOW, HIGH)) -> frozenset()` under the
heading "asking for nothing does not widen anything". Consuming it for the first
time in Phase 6 revealed what that implies in the product: §4 defaults the column
to `'[]'` and every seeded built-in carries that value, so a strict intersection
makes the workspace policy **inert**. A user sets `auto_approve` to `["low"]` so
an overnight run can proceed, every definition intersects it away to nothing, and
the setting reports success while changing nothing — the same class of bug as the
one above, arrived at from the opposite direction.

So `ToolRuntime.auto_approve_for` reads an empty definition list as "not
answered" rather than "declined" and falls back to the workspace policy. A
definition that *does* name levels still narrows, through the untouched pure
intersection in `effective_auto_approve`.

**The security property is unchanged, which is the part that matters.** §5 Phase
5's note forbids a definition *escalating* — "it can never grant a risk level the
workspace policy has not enabled" — and under both readings the result is a
subset of the workspace policy. The only difference is whether a row nobody has
edited counts as having declined. It has not.

Worth stating at length because the strict reading is the safer-*looking* one and
is what a later reader will be tempted to restore: it requires opting in twice,
so a user who enables `high` at the workspace level does not thereby hand every
agent a shell. That is a real argument. The answer is that §5 Phase 6 asks for a
policy that lets "overnight runs progress", a knob that requires separately
editing every definition afterwards is not that knob, and the per-definition list
remains available to anyone who wants to narrow a particular agent.

### What Phase 7 established, and how it was verified

**The acceptance criterion is structural, not a promise kept.** §5 Phase 7 asks
that "replaying a completed run produces pixel-identical UI state to what was
shown live". The usual way to fail that is to have two code paths — one that
accumulates state as events arrive, one that rebuilds it from history — which
agree until one of them gains a feature. So there is one path: the store holds
the event array and a cursor, and the view is always
`reduceAll(events.slice(0, cursor))`. Live is that fold with the cursor pinned to
the head; replay is the same fold with a smaller cursor. **Scrubbing backwards is
not a second renderer, it is a smaller number.**

Confirmed by mutation: making `setCursor` fold forward from the current view in
both directions — the obvious optimisation — fails four tests, because the
reducer has no inverse and going backwards has to start over.

**And then it was measured, in a browser, against the pixels.** A scripted run
was attached to *while it was still running*, watched to completion, and the run
projection captured. The page was then reloaded and the same run replayed from
history, and captured again. The DOM came back **byte-for-byte identical**, and
the pixels differed in 0.018% of the canvas by a single unit of 255 — SVG
rasterization noise, not state. Per region, the event log and the run summary
differ by **zero** pixels.

Getting there took three attempts and the failures are the interesting part; see
"The bug the live run found (Phase 7)" below.

**The honest exception is the transport control, and it is excluded on purpose.**
Watching live at event 12, the log holds 12 events. Replaying the same run at
event 12, it holds 28 and you are standing at 12 of them. The scrubber cannot
match and should not: hiding the length of the run being replayed would be worse
than the difference. So `RunPanel` has two halves — `run-projection`, which is a
pure function of the log, and the scrubber, which says where you are standing.
The projection is compared at every position in the run; the whole panel is
compared at the head of a completed run, which is the criterion in its literal
form.

**A run was created, watched, approved and replayed entirely from the page.**
Against a real `qwen3:4b`: an agent created through the editor (never touching
Python), edited through the editor, spawned by the supervisor, and its
`write_file` call stopped at the gate. **Allow** was clicked in the browser and
`reminder.txt` appeared on disk with exactly the content the prompt named. A
second call was **denied** from the browser, and the run continued and completed
— "a denial stops a call, not a run", now watched in the UI rather than in a log.

That closes the Phase 6 gap which said no approval had ever been resolved from
anything but `curl`, and the Phase 4 gap which said the webview had never seen an
orchestrated run.

**The second dialog said "overwrite" where the first said "create".** Same tool,
same path, different sentence — because `Prepared.summary` is built from the
resolved call and the file existed by then. The Phase 6 decision to render the
resolved call rather than the raw arguments, confirmed in the UI.

**Each of the four warnings this file left for Phase 7 is answered by something
on screen.**

- `run.completed.summary` is rendered under the heading "The supervisor's account
  of the run", with the caveat "This is what the agent said it did. What it
  actually did is the N tool calls in the log below." A live run promptly
  obliged: the fourth confabulation in this project, `finish("reminder.txt")`
  from an agent that never called `write_file` at all, rendered beside a count of
  two control calls and no file tool.
- `llm.token` changes no activity state. Only `agent.thinking` and `llm.request`
  do, so an agent that streams nothing does not read as idle.
- `blocked_by` is rendered on every denial — `read_file [sandbox] — that path is
  outside the workspace` — and counted separately in the run summary.
- The approval dialog carries the run's decision history, not only what is
  outstanding. Watched live: "Earlier in this run: 1 decision — approved
  note_taker write_file", above a second question from `note_taker-2`.

**The generated types are generated, and a test says so.** §5 Phase 7 requires
the API types to come from the OpenAPI schema. `openapi-typescript` is the
canonical tool and caps its TypeScript peer at `^5.x` against the 6.0.3 here, so
it cannot be installed without `--legacy-peer-deps` on every `npm install` —
weakening peer checking across the whole tree for one dev tool, which is the
trade Phase 0 already refused with `eslint-plugin-import`. The input is 17
schemas over a closed set of keywords, so `agentspace/openapi.py` emits them.

**The emitter raises rather than guessing.** A generator that fell back to
`unknown` on an unfamiliar keyword produces a file that typechecks and protects
nothing, and a discriminated union of event payloads is an obvious Phase 8
candidate for triggering exactly that. `UnsupportedSchemaError` makes it a build
failure, and `test_openapi_snapshot.py` compares both committed artefacts against
the live app byte for byte, so a forgotten `just schemas` fails a test instead of
shipping types that describe a past API.

**`GET /runs` reads the `runs` table, not the event log.** The log is the
authority on what *happened* in a run; it is not the authority on which runs
exist, and a run created and never started has no events at all. That run is
precisely the one a user goes looking for an explanation of.

### The bug the live run found (Phase 7)

**Three, and two of them were invisible to a green suite.**

**The first: every Ollama configuration was told its runs would be refused.**
`GET /settings` computed `model_is_priced` from `settings.model` verbatim, while
the provider that actually runs namespaces a local model to `ollama/<name>`
before the ledger prices it. So the field whose own docstring promises "every run
will be refused" read false for a configuration that worked perfectly and cost
nothing — and the Phase 7 header rendered it as "unpriced — runs will be
refused" over a working setup. `POST /settings/verify` was right all along,
because it builds the provider first and asks about `provider.model`: two
endpoints, one configuration, opposite answers.

This is the **seventh** instance of this project's recurring shape, after Phase
1's CORS, Phase 2's named SSE events, Phase 3's `*.sql` glob, Phase 4's silently
dropped settings fields, Phase 5's `max_steps` default and Phase 6's unsettable
`auto_approve`. Every one was found by running the thing. The fix is structural
in the same way Phase 6's was: `qualified_model` is the single place that knows a
provider's naming rule, and
`test_qualified_model_is_what_the_built_provider_reports` compares it against
what a built provider actually says, for every provider.

**The second: no handoff edge was ever drawn.** `AgentCard` rendered no
`<Handle>`, so React Flow refused every edge touching it — logging a warning to
the console and drawing nothing. §5 Phase 7's "handoffs as edges" was entirely
missing while the graph looked finished. Every test passed, because they all
asserted node content and none asserted an edge. Found by reading the browser
console during a real run, which is the whole argument for doing that.

React Flow will not lay out an SVG edge in jsdom at all, so the drawn edge is
verified in a browser and the *handles* are what the test asserts — the thing
that was actually wrong.

**The third: replay was not pixel-identical, and the difference was the camera.**
Measured at 10% of the canvas's pixels, with a byte-identical DOM underneath.
React Flow's `fitView` frames what it has **measured**, so its result depends on
when it ran: first against nodes that had no dimensions yet, then against a pane
that changes height when the terminal event adds its claim block above it.

Two attempts to fix it by waiting for measurement failed, and the more
instructive one *appeared* to succeed — gating the refit on `useNodesInitialized`
produced identical pixels because the fit then never ran at all, leaving the
camera at identity. A criterion that passes because the feature stopped working
is worse than one that fails.

So the camera is arithmetic now, like the layout: `viewportFor` computes it from
the nodes and the pane and nothing else, recomputed when either changes. Every
region then differed by zero pixels. **The pane-resize half is not defensive** —
without it the two disagree by 10%, because the summary above the canvas grows
when the run ends.

### What Phase 8 established, and how it was verified

**Both acceptance criteria fired against a real Discord server, in one run.**
§5 Phase 8 asks that "the same run is observable simultaneously from the
dashboard and the originating chat channel, and a channel-originated tool call
still hits the approval gate." `/agent` was typed in a channel; the bot's single
message was edited live as the run progressed; a dashboard-side client consuming
`GET /runs/{id}/events` — the identical endpoint the React `EventSource` opens —
received **52 events against 52 in the log**. Two `write_file` calls stopped at
`approval.requested`, were surfaced to Discord as Allow/Deny buttons, were
answered by pressing **Allow** in Discord, and only then executed.
`reminder.txt` appeared with exactly the 16 bytes the prompt named, and the
`approvals` table holds both rows as `approved`.

**A chat reply is a second projection of the log, not a second path into the
orchestrator.** That is what makes "same event log, no special-casing" checkable
rather than asserted. Inbound, an adapter normalizes its platform's message and
hands it to :class:`RunLauncher` — the same object `POST /runs` uses. Outbound,
the message is `render(fold(events))` recomputed from scratch on every edit,
never appended to. `test_both_projections_of_one_log_say_the_same_thing` re-folds
the stored log and asserts it reproduces the final chat text byte for byte, and
the live run confirmed it.

Re-rendering rather than appending is the Phase 7 live-versus-replay reasoning
applied to a different surface: an accumulating renderer and a rebuilding one
agree until one of them gains a feature. There is only the rebuilding one, so a
reconnect or a resend shows what the log says rather than what the process
happened to witness.

**The fold is exhaustive, and `mypy --strict` proves it.** The `case _` arm calls
`assert_never`, so adding an `EventType` member without teaching the chat
projection about it is a **build failure**. That is deliberately stronger than
the TypeScript reducer's `default` branch, and the asymmetry is real: the browser
is a separately built artefact that can lag the server it talks to, so it must
handle an unknown type at runtime. This fold is compiled from the same enum it
folds, so the question is settled before the process starts. The three-way
obligation §4 describes is now a two-way one plus a compiler error.

**The allowlist is the security boundary this phase actually turns on, and §1
constraint 6 does not cover it.** That constraint stops the bot ingesting ambient
chatter. It says nothing about who may address it *deliberately* — a slash
command is an explicit trigger and therefore permitted — and a Discord bot
invited to a server can be invoked by anybody in that server. Without an
allowlist the three things a stranger reaches are the owner's monthly API budget,
the owner's desktop (every medium/high call raises a dialog on it), and through
`run_shell` the owner's user account. An external id with no entry resolves to
nobody, and a message from nobody starts no run.

The empty list means **nobody**, which is the opposite of the Phase 6 decision
about an empty `auto_approve` on a definition. The shapes look inconsistent and
the reasoning is identical: there the fallback direction was "inherit the
workspace policy" because a strict reading made the setting inert; here there is
no wider policy to inherit and the two candidate readings are "nobody" and
"everybody". In both places the empty case is the one that must not widen.

**And the refusal was exercised live, against the same account that had just
driven a successful run.** With the owner's id removed from the allowlist,
`/agent` in the same channel produced: a log line naming the sender, the reply
"This agent workspace is not configured to accept requests from this Discord
account. Nothing was run.", and — the part that matters — **no new run, no new
event, and no second `channel.inbound`**. The table stayed at 1 run and 52 events.
`GET /channels` reported `refused: ['Zocke (868311828982284310)']`.

The reply is terse on purpose. It goes to somebody who is by definition not
trusted, so it names nothing about the workspace: not the owner, not the other
allowlisted identities, not the goal they tried to run, not where the allowlist
lives. A stranger probing the bot learns only that it declined, while the *log*
and the status endpoint carry the full detail, because the owner is the one who
needs to be able to add them.

**Two privileged intents were never requested, and that is enforced rather than
remembered.** §5 Phase 8 says not to ask for `MessageContent`, and the payoff is
that Discord does not deliver the text of messages this bot was not mentioned in
— so §1 constraint 6 holds because the data never arrives, not because this code
declines to read it. `test_channel_adapters.py` asserts the intent set is exactly
`{guilds}` and, separately, that it is *strictly narrower* than `discord.py`'s
own `Intents.default()` — which is the tempting one-word "fix" that would turn
every flag on at once. Telegram gets the same property from privacy mode, which
is the default for a new bot and which nothing here turns off.

**Answering an approval from chat is not a privileged path.** Discord's buttons
and Telegram's inline keyboard both call
`ApprovalService.resolve` — the identical method `POST /approvals/{id}` calls,
including its 409 on an already-settled row, which is what a second click or a
race with the dashboard produces. There is no channel branch inside the gate,
because the gate never learns a channel exists. Only *who may press* is
channel-specific: the button check is on the interaction's user id, which the
platform asserts, never on anything carried in the message. `_MessageReply` takes
the originator's id as a constructor argument rather than reading it off the
placeholder message, whose author is the bot — deriving it from the message would
have been the plausible-looking mistake that lets anyone approve anyone's call.

**The default is still that chat cannot answer.** `channel_approvals` defaults to
`dashboard_only`: the question is *shown* in chat, so a stopped run does not look
like a crashed bot, but the answer is given at the machine the call would run on.
An approval is the moment the owner decides whether something touches their disk,
their shell or their network, and the default should not move that decision onto
a phone in a group chat. `originator` is available and was what the live run
used.

**Plain text, no markdown, on both platforms.** Telegram's MarkdownV2 requires
eighteen characters escaped and a single miss is a 400 that discards the whole
message. Agent output is arbitrary text — file contents, shell output, model
prose — so any markdown mode is a grenade whose fuse burns exactly until a run
produces something interesting. One plain renderer serves both and cannot fail
that way.

**One message per run, edited.** This is what makes the rate limits nearly moot,
rather than the throttle being clever. §5 Phase 8 quotes Discord's 50 req/s and
Telegram's 30 msg/s, and neither is the binding constraint: editing one message
is limited far more tightly (roughly five per five seconds for one Discord
webhook token). Traffic is bounded by the throttle interval instead of by how
talkative the run is. The live run made 52 events into a handful of edits.

**A refusal is deliberately not written to the event log.** §4 gives
`events.run_id` a NOT NULL foreign key, so a `channel.inbound` for a refused
message would need a run row to hang off — a run that never ran, in the user's
run list, creatable in unbounded numbers by any stranger who can see the bot.
Refusals are reported through a bounded in-memory list that `GET /channels`
renders, and that list survives a settings reconcile because it is the only trace
of the event that exists.

**`GET /channels` earns its place the way `tools/runtime.py` did.** §3 does not
name it. Without it, "Discord is enabled" is a setting the user wrote and nothing
anywhere says whether it worked — a token that never reached the keychain, a
library that failed to freeze, and a gateway that has been refusing to connect
for ten minutes all present identically as a bot that says nothing, and the user
can fix all three once told which it is. `PATCH /settings` knows what was asked
for; only the running `ChannelService` knows what happened.

**The confabulation check travels to chat, where it matters more.** A dashboard
user can read the event log and see a terminal summary disagreeing with it. A
chat user sees nothing except the one message, so the message carries the check
itself: the summary is labelled as the supervisor's account and rendered beside a
count of what actually executed.

### The bugs the live run found (Phase 8)

**Four, and three of them were invisible to a green suite.**

**The first: a bot that connects, reports itself healthy, and has no commands.**
`tree.sync()` with no guild registers *global* commands, which Discord caches for
up to an hour. It is what the documentation and nearly every example show. The
first live attempt connected, logged `discord connected as AgentBase#3281`,
reported `running: true` through `GET /channels` — and typing `/agent` produced
no interaction, no event and no log line anywhere, because the command did not
yet exist in the client. **There is no error in that sequence to find.** Commands
are now synced per guild, which takes effect immediately and is the correct
registration for a local-first app whose bot lives in one or two servers; the
global path is what a public bot with thousands of installs needs, and this is
not that. `on_guild_join` covers a server added later, and the guild count is
logged because "connected but in no servers" and "connected and synced" were
otherwise indistinguishable from outside while needing completely different
fixes.

**The second: `discord_enabled` did nothing until a restart.** `ChannelService`
started once, in the lifespan, so enabling a channel returned `200 OK`, wrote the
row, and connected nothing — and this product has no restart button. That is the
**eighth** appearance of this project's recurring shape, after Phase 1's CORS,
Phase 2's named SSE events, Phase 3's `*.sql` glob, Phase 4's silently dropped
settings fields, Phase 5's `max_steps` default, Phase 6's unsettable
`auto_approve` and Phase 7's `qualified_model`. Every one was found by running
the thing, and this one was no different: the setting was set and nothing
happened. `reconcile()` now runs on any settings change touching a channel, in
both directions, and the set of triggering fields is derived from the settings
model rather than hand-listed — the Phase 6 lesson about two lists that drift,
applied before it had a chance to.

**The third: `channel.outbound` was appended after the run's terminal event.**
§4's terminal events are defined as the ones "after which no further event can
appear for that run", and the SSE stream closes on them. Writing the outbound
record in a `finally` block therefore produced a log the dashboard could never
fully see: a real `qwen3:4b` run put **38 events in the table and handed a
simultaneous watcher 37**. Live and replay disagreed, which quietly breaks §5
Phase 7's pixel-identical criterion for every channel-originated run.

The test that was supposed to cover this asserted on `store.read()` — the
database, not the stream — and passed happily. That is the same shape as every
other bug above: a check that is correct everywhere except where the product
actually consumes it. The record is now written on first delivery, inside the
run's lifetime, and two tests assert it from the consumer's side; one of them
fails against the old code by exactly one event.

**The fourth, and the only one that was merely noisy:** merging settings with
`model_copy(update=...)` left a list of dicts sitting in a field annotated
`list[ChannelIdentity]` until a `model_dump()` round-trip coerced it, so Pydantic
warned on every settings write. Nothing was lost, and a
`PydanticSerializationUnexpectedValue` in a sidecar log is indistinguishable at a
glance from the kind that precedes real data loss. Merging plain dicts and
validating once has no such intermediate.

### What the live Discord run showed

**The approval prompt said "create" and then "overwrite".** Same tool, same path,
different sentence — Phase 6's decision to build `Prepared.summary` from the
*resolved* call rather than the model's arguments, confirmed for the first time
through a chat channel rather than a browser.

**qwen3:4b wrote the same file twice.** Two `write_file` calls with identical
content, so the user was asked twice and pressed Allow twice. Nothing is broken:
the gate stopped both, the second prompt correctly said "overwrite", and the
supervisor then finished. It is the same plan-quality gap CLAUDE.md already
records for this model, now visible from a phone.

**52 events became a handful of message edits**, which is the one-message-per-run
design doing its job — the throttle never had to be clever.

Next up: **Phase 9 — CI and release.** Do not start it before re-reading
BUILD_SPEC §5 Phase 9. Three things bear on it directly:

- Nothing has been packaged since **migration 004**, and the sidecar now carries
  `discord.py` and `python-telegram-bot`. Both are large trees with their own
  hidden-import behaviour at freeze time, and `discord.py` imports `audioop`,
  which is removed in Python 3.13 — irrelevant on the pinned 3.12 and worth
  knowing. The frozen binary has not been rebuilt since they were added.
- §5 Phase 9 requires the test job to gate the build job. `just ci` is that
  command and it is green: **618 backend, 124 frontend**.
- The macOS build has still never run, and `channels/` is the first code in this
  project with a platform-shaped dependency tree.

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
  untested. **Phase 7 wrote the real client and still did not force this.** It
  did establish the other half of a stream that closes normally: the client
  closes itself on a terminal event, because `EventSource` would otherwise
  treat the ended response as a drop and re-request a finished run every
  second forever. The reconnect proper is still owed a mid-run disconnect.
- ~~**Backpressure against a real client.**~~ **Closed in Phase 4.** A 900-word
  streamed response overflows the 512-event queue while the client reads
  nothing; the subscription is asserted to have actually gone stale, and the
  client still receives a gapless 1..N. Consumed through `run_stream` rather
  than over HTTP — see the Phase 4 bug note for why an in-process HTTP client
  cannot do this.
- **Two simultaneous SSE clients on one run.** **Narrowed in Phase 8, not
  closed.** A Discord-originated run was consumed concurrently by the channel
  adapter and by an HTTP client on `GET /runs/{id}/events`, and both saw all 52
  events — so two consumers of one run through the real cursor is now exercised.
  What has still never happened is two clients over the *HTTP* layer at once:
  the adapter consumes `run_events` in-process, one layer below the framing.

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

Phase 8 specifically:

- **Telegram has never connected.** The adapter is written, typechecked and unit
  tested, and no `python-telegram-bot` `Application` has ever polled a real
  endpoint. This is the deliberate scope of the live verification — Discord was
  the one with a token — and it is exactly the state Phase 3's Ollama
  implementation was in before it turned out to work first try. What that
  precedent does *not* license is assuming this one will: the long-polling
  lifecycle here is hand-assembled from `initialize`/`start`/`start_polling`
  rather than `run_polling`, precisely because the latter owns the event loop,
  and that assembly has never run.
- **No approval has been answered from Telegram**, and `_OWNERS` — the in-memory
  map deciding who may press an inline-keyboard button — has never been read in
  anger. Its Discord counterpart has.
- **The bot has only ever been in one guild, with one user.** Nothing has
  exercised two guilds, a guild joined while running (`on_guild_join`), two
  people using the bot at once, or the mention trigger — the live run used the
  slash command both times. `_on_mention` is covered by nothing but its own
  reading.
- **Nothing has been packaged since `discord.py` and `python-telegram-bot` were
  added**, and they are the two largest dependencies in the tree. PyInstaller
  hidden imports are exactly where Phase 3 predicted an SDK would cost, and the
  frozen binary has not been rebuilt. `discord.py` also imports `audioop`, which
  Python 3.13 removes; the pin is 3.12, so this is a note rather than a problem.
- **The keychain-to-stdin half is still the untested step**, one phase later and
  now carrying two more credential names. The live run used the same
  stand-in-for-Tauri handshake Phases 3-6 used: a real token on a real stdin
  pipe, reported by `GET /channels` as `configured: true`, absent from the
  database and the log. What no test and no run has done is read it out of the
  Windows Credential Manager through `tauri-plugin-keyring`.
- **No run has been watched from a channel and a browser at the same time.**
  The live run was watched from Discord and from an HTTP client consuming the
  same SSE endpoint the browser consumes — which is the acceptance criterion and
  is what makes the claim structural — but no actual webview was open. The
  standing "two simultaneous SSE clients on one run" gap from Phases 2, 6 and 7
  is therefore *narrowed* rather than closed: two consumers did run concurrently,
  and neither was a browser.
- **The throttle has never been under real pressure.** 52 events over a run of a
  couple of minutes is not a stress test, and no run has produced enough events
  fast enough to make a platform return a 429. The retry behaviour on a
  rate-limited edit is `discord.py`'s and has not been observed.
- **A refusal was verified for one shape of stranger.** The account refused was
  the owner's own, with its id removed from the allowlist. Nobody genuinely
  unknown to the workspace has ever addressed the bot, and no second person has
  ever been in the server.

Phase 7 specifically:

- **Nothing has run in the packaged app.** Every browser check this phase used
  Edge — which is WebView2's engine, so the JavaScript, `EventSource` and CORS
  behaviour are the same — against the Vite dev server at
  `http://127.0.0.1:5173`. The shipped app serves from `http://tauri.localhost`,
  a different origin in the same allowlist, and no `tauri build` was produced or
  installed this phase. Phase 1's CORS bug was found by installing the app and
  looking, and Phase 9's acceptance criterion is the real check.
- **The browser's automatic EventSource reconnect is still unforced.** Phase 2
  left this for Phase 7 and Phase 7 did not do it: no run was interrupted
  mid-stream to watch the browser reconnect and supply `Last-Event-ID` itself.
  What *is* now exercised is the client closing itself on a terminal event, and
  the store discarding a whole re-delivered log without changing the screen —
  which is the resume path's effect, reached a different way.
- **The pixel comparison used one scripted run, not a model-driven one.** The
  debug run is 20 events over a fixed script, which is what made attaching to it
  mid-run and replaying it reproducible. A long model-driven run was compared by
  DOM and by the reducer, not by pixels.
- **No run has been watched from two windows at once.** Same standing gap as
  Phase 2's and Phase 6's. Phase 8 watched one run from a chat channel and an
  HTTP SSE client simultaneously, which is the acceptance criterion and is not
  this: no *browser* was open, so the store's duplicate handling under two real
  `EventSource` clients is still untested.
- **The graph has never held more than three agents.** `max_agents_per_run` was 3
  for these runs. The layout is a single row of workers with no wrapping, so a
  run with a dozen agents will overflow horizontally; the camera zooms out to fit
  it, which is not the same as a design that handles it.
- **Long transcripts are still untested for size, and now for rendering too.**
  `llm.request` carries the full message list on every step, and the event log
  renders every row it is given with no virtualisation. The longest run this
  phase rendered was 218 events, which is nothing.

Phase 6 specifically:

- **`run_shell` has no network isolation, and this is not a gap that testing
  closes.** See the Phase 6 notes: the timeout and the process-tree kill are
  real and verified, the scrubbed environment is real, and "no network" is not
  enforceable in-process cross-platform. A shell command that calls `curl`
  reaches the internet. The container wrapper §5 Phase 6's addendum describes is
  the answer and is explicitly not part of the shared build.
- **`http_get` has never fetched a real URL.** Every network test runs against
  an `httpx2.MockTransport`, exactly as the providers do. The *refusals* are
  well covered — scheme, loopback, private, link-local, redirect — and a real
  page has never been retrieved, so a wrong default header or a redirect shape
  the mock does not reproduce would pass. It is also the one built-in no live
  run has called.
- **DNS rebinding defeats `check_url`.** The check resolves the hostname and the
  connection resolves it again, so a name that answers public at check time and
  private at connect time reaches a private address. Closing it means pinning
  the connection to the checked address, which is a property of the HTTP client
  rather than of the sandbox. Recorded in the module docstring rather than
  quietly implied to be handled.
- ~~**No approval has ever been resolved from the webview.**~~ **Closed in
  Phase 7.** A `write_file` call was approved by clicking **Allow** in a real
  browser and the file appeared on disk with the expected content; a second was
  **denied** from the browser and the run continued and completed. Both requests
  were genuinely cross-origin — a `POST` with a JSON content type, so the browser
  sent the preflight — which is what the Phase 1 CORS bug and the Phase 2
  named-event bug were both invisible to from `curl`. The origin exercised was
  `http://127.0.0.1:5173`; the packaged app's `http://tauri.localhost` is in the
  same allowlist and has still not been exercised against these routes.

- **Two clients answering the same approval has only been tested in-process.**
  `test_resolving_twice_is_a_409` and the conditional `UPDATE` cover it, and no
  two real clients have raced. Phase 8 made the race *reachable* — a Discord
  button and the dashboard can now answer the same approval, and the button
  handler is written to render the 409 as "Already answered elsewhere" — but
  both live approvals were answered from Discord alone, so nothing has raced.
- **Nothing has been packaged since migration 004 existed.** Same standing gap
  as Phase 5's, now one migration longer, and the seeded-built-in widening in
  004 makes it slightly more interesting: no real installation has upgraded
  across it. The glob still carries every `*.sql` and the test still passes.
  Phase 9's acceptance criterion is the real check.
- **The sandbox has only ever been rooted at a temp directory or the dev data
  directory.** `AppPaths.workspace_root` resolves under the OS app-data
  directory in the shipped app and a test asserts that, but no *installed* build
  has created it. The Phase 2 lesson about `%APPDATA%` versus `%LOCALAPPDATA%`
  was found by installing and looking, not by reading.
- **A worker-initiated `handoff` still does not re-delegate**, and Phase 6 made
  it visible: after being denied, the escaper handed off to a nonexistent
  `another_agent` and the supervisor did nothing with it. The event is real, the
  follow-through is not implemented, and no test asserts the supervisor behaves
  sensibly. Carried forward unchanged from Phase 4.

Phase 5 specifically:

- ~~**A real model has never been *denied* a tool.**~~ **Closed in Phase 6.**
  `qwen3:4b` called `write_file(path="../../ESCAPED.txt")` and was refused with
  `tool.denied` and `blocked_by: "sandbox"`, and separately had a legitimate
  in-workspace write denied by a user answering the gate. What made the
  difference was not a better prompt but a *plausible* call — the agent was
  offered `write_file` and told to use it, so the refusal came from the boundary
  rather than from the model declining to try. Phase 5's reading, that a small
  local model would probably never produce one, was wrong.
- ~~**`auto_approve` is stored, validated and intersected, and consumed by
  nothing.**~~ **Closed in Phase 6**, and consuming it changed the rule — see
  "The design decision worth not re-litigating (Phase 6)".
- **A definition's `provider`/`model` are honoured at the pool, not through a
  run.** `ProviderPool` is tested directly — inheritance, pinning, caching, and
  the auth failure — but no run has ever had two agents on two different
  providers, because the scripted-provider override deliberately applies to
  every agent so tests stay deterministic. The supervisor's handling of a
  definition whose provider will not build is therefore covered as a unit and
  not end to end.
- ~~**No agent editor exists.**~~ **Closed in Phase 7.** `AgentList.tsx` and
  `AgentEditor.tsx` exist, and a definition was created, edited and run entirely
  through them against a real model. The field-aware 400s are consumed: a
  duplicate name lands on the name input, a `max_steps` rejection on the max-steps
  input, and an unknown tool on the tool list. Deleting a built-in was refused
  with its 409 message rendered inline rather than the button being hidden.

Phase 4 specifically:

- **OpenAI has still never answered a real request.** Anthropic and Ollama both
  now have, and both were correct. OpenAI's `stream_options.include_usage` is
  the remaining one that fails silently in the direction of under-billing — if
  it is wrong, every streamed OpenAI call records as free and the cap stops
  binding while the run works perfectly.
- ~~**No local model has completed a run.**~~ **Closed: `qwen3:4b` does.** See
  "Which local model actually drives the loop" below. What remains open is
  whether a local model can handle a *harder* goal than a two-worker writing
  task — plan quality was visibly weaker than Anthropic's even on a run that
  succeeded.
- ~~**The webview has never seen an orchestrated run.**~~ **Closed in Phase
  7.** A run driven by a real `qwen3:4b` was started from the page and watched to
  completion over a real `EventSource` — 218 events, three agents, six tool calls
  — with the browser console clean throughout. What is still untested is the
  browser *reconnecting* mid-run; see the Phase 2 entry above, which this phase
  did not close.

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

`packages/schemas/` holds the generated TS types and the OpenAPI document they
come from. Both are committed, so `just check` on a clean clone never needs a
Python environment to typecheck the frontend; `just schemas` regenerates them and
`test_openapi_snapshot.py` fails if either drifts from the running app.

The backend now also holds `store/` (SQLite + migrations and workspace
settings), `events/` (types, store, bus), `providers/` (protocol, pricing,
Anthropic/OpenAI/Ollama, factory), `budget/` (the monthly cap) and `api/`
(runs, stream, settings), per the §3 layout. `secrets.py` sits at the package
root because it is process-wide state, not storage — keys never reach the
database.

Phase 4 added `orchestrator/` — `run.py` (lifecycle, the event sequence, the
mailbox), `supervisor.py`, `agent.py`, plus two modules §3 does not name:
`limits.py` (the run ceilings) and `control.py` (the tool vocabulary an agent
may call).

Phase 5 added `orchestrator/registry.py` (the frozen roster, plus `ProviderPool`
for §4's per-definition `provider`/`model`), `store/agents.py` (the `agent_defs`
row and its validation) and `api/agents.py` (CRUD, and `GET /tools`).

Phase 6 filled in `tools/`, which until now held only `catalogue.py`. It now
carries the whole path a tool call travels: `base.py` (the Tool protocol and the
`prepare`/`execute` split), `sandbox.py` (the workspace root and what a call may
reach), `approval.py` (the gate, plus the `approvals` table), `builtin/`
(`filesystem.py`, `network.py`, `shell.py`) and one module §3 does not name —
`runtime.py`. `ToolRuntime` bundles the tools, the sandbox and the gate because
they are not independent: a sandbox without a gate is an ungated path to the
filesystem, and passing them as one value means there is no way to assemble an
agent holding only some of them. Same kind of additive deviation as
`orchestrator/limits.py` and `orchestrator/control.py`.

`RiskLevel` stayed in `catalogue.py` rather than moving to `base.py` as §3
sketches. The catalogue is what `allowed_tools` validates against and what the
Phase 7 editor renders; a tool reads its own risk from there rather than
declaring it, so the level shown next to a checkbox is the level the gate
enforces.

`api/approvals.py` arrived with it — `POST /approvals/{id}` is what resolves the
future an agent is suspended on, plus the `GET`s the Phase 7 dialog needs.

Phase 7 filled in `apps/desktop/src/`, which until now held only the Phase 1
shell. `lib/` gained `api.ts` (typed calls, using the generated types), and
`events.ts` (the `EventSource` client); `state/` holds `reducer.ts` — the fold
that everything on screen is derived from — plus `runStore.ts`, `graph.ts`,
`useRunStream.ts` and `useFetched.ts`; `components/` holds the six modules §3
names, plus `RunPanel.tsx`, `RunSummary.tsx`, `RunsView.tsx` and
`AgentsView.tsx`.

Three of those are not in §3's sketch and each earns its place. `RunPanel` is the
boundary the acceptance criterion lives on — it separates the projection of the
log from the transport control, which is the one thing that legitimately differs
between live and replay. `state/graph.ts` holds the pure `RunView` → nodes/edges/
camera derivations, out of the component both because they are the interesting
part and because a component module that also exports functions defeats React
Fast Refresh. `lib/payload.ts` is shared by the reducer and the log panel, which
read the same payloads and would otherwise grow two opinions about what a missing
field means.

`agentspace/openapi.py` sits at the backend package root: it builds the OpenAPI
document and emits the TypeScript from it, and is what `just schemas` runs.

Phase 8 filled in `channels/`, which §3 sketches as three files and which is
seven. `base.py` (the normalized `InboundMessage` and the two protocols),
`discord_adapter.py` and `telegram_adapter.py` are §3's; the other four each
carry something the adapters would otherwise duplicate. `identity.py` is the
allowlist — the security boundary of the phase, and the one thing that must not
have two implementations. `render.py` is the chat projection: `fold` and
`render`, pure, no I/O. `throttle.py` is the edit cadence. `service.py` holds
both `converse` — one whole conversation, from the allowlist check to the last
edit — and `ChannelService`, which supervises the adapters.

The split between `service.py` and the adapters is the load-bearing one:
Discord and Telegram differ in exactly one thing, which is how you edit a
message you already sent, and that difference is the whole of `ChannelReply`.
Everything else — who may ask, what a refusal says, which object starts the run,
what the reply says at any moment, when an edit is worth spending — is shared,
so a bug fixed in one channel is fixed in both.

`api/channels.py` arrived with it: `GET /channels` reports whether an adapter is
actually connected, which is a question `GET /settings` structurally cannot
answer. Same kind of additive deviation as `tools/runtime.py`.

`orchestrator/launcher.py` is not in §3 either and is the most important of
these. `RunLauncher` is the single place that knows how to start a run, used by
`POST /runs` and by both channels. Phase 4 assembled `execute_run`'s arguments
inline in the HTTP handler, which was right while there was one caller; three
copies of that list would have been the eighth instance of this project's
recurring bug, and this file exists specifically so it cannot be.

`tests/support.py` holds the scripted provider doubles and the event-log
reducer. Phase 4 kept them in `test_orchestrator.py`; three test modules now
drive runs, and two copies of a reducer is two answers to "what does the log
say".

## Decisions made mid-build

Recorded here as they happen, so a later session does not re-litigate them.

- **2026-09-11 — the channel adapters run in-process, supervised, not in their
  own OS process.** §5 Phase 8 says Discord runs in its "own process", and this
  is a deliberate deviation. The benefit of a separate process is crash
  isolation, and `ChannelService._supervise` provides it: an adapter that raises
  takes down its own task, is restarted with backoff, and is left stopped with a
  reason after five consecutive immediate failures. The costs of the literal
  reading are Phase 1's orphan-process trap re-run twice — with `--onefile` the
  PID a parent holds is the bootloader's, not the server's — plus a second
  frozen binary, a second `--onefile` extraction on every launch, and a
  duplicated shutdown handshake. The reason usually given for the separate
  process does not apply: neither `discord.py` nor `python-telegram-bot` needs
  its own event loop. `discord.Client.start()` and PTB's `Application` pieces
  both run as tasks on an existing one; only `run()` and `run_polling()` create
  loops, and neither is used.
- **2026-09-11 — one run owns one chat message, re-rendered, never appended
  to.** It is the Phase 7 live-versus-replay argument on a different surface,
  and it also happens to make both platforms' rate limits nearly moot without
  the throttle having to be clever. The binding limit is not §5's quoted 50/s or
  30/s but the far tighter per-route bucket on editing a message.
- **2026-09-11 — the chat reply is plain text on both platforms.** Telegram's
  MarkdownV2 needs eighteen characters escaped and one miss is a 400 that
  discards the whole message, over content that is arbitrary agent output. One
  plain renderer cannot fail that way. Discord renders plain text fine.
- **2026-09-11 — an unknown sender starts nothing, and an empty allowlist admits
  nobody.** §1 constraint 6 covers ambient ingestion, not deliberate address,
  and a bot in a server can be addressed by everyone in it. See the Phase 8
  notes for why this empty-list default is the opposite of Phase 6's and why
  both are right.
- **2026-09-11 — a refusal is not written to the event log.** §4 gives
  `events.run_id` a NOT NULL foreign key, so it would need a run row that never
  ran — in the user's run list, creatable in unbounded numbers by a stranger.
  It goes to a bounded in-memory list `GET /channels` renders, which survives a
  settings reconcile because it is the only trace that exists.
- **2026-09-11 — `channel_approvals` defaults to `dashboard_only`.** The
  question is shown in chat so a stopped run does not read as a crashed bot;
  answering it happens at the machine the call would run on. Neither value is a
  privileged path — both go through `ApprovalService.resolve` — so the setting
  decides who is asked, never whether the gate applies.
- **2026-09-11 — `channel.outbound` is written on first delivery, not as a tally
  at the end.** §4's terminal events are the ones after which no further event
  can appear, and the SSE stream closes on them; an append in a `finally` is
  delivered to nobody watching live while a replay finds it. See the Phase 8 bug
  notes — this was measured at 38 events against 37 before it was fixed.
- **2026-09-11 — Discord commands are synced per guild, not globally.** Global
  commands are cached by Discord for up to an hour, which for this product means
  a bot that connects, reports itself healthy, and does nothing all afternoon
  with no error anywhere. Guild-scoped registration is immediate and is the
  correct one for an app whose bot lives in one or two servers.
- **2026-09-11 — bot tokens travel the keychain-to-stdin route, not the
  `settings` table.** A bot token authenticates this application to a third
  party and is replayable by whoever reads it, which is what §1 constraint 4 is
  about; the `settings` table sits on disk in the clear beside the event log.
  Adding them to `SECRET_KEYS` meant adding them to `SECRET_NAMES` in `lib.rs`,
  and nothing was comparing those two lists — so a test now does.

- **2026-09-10 — the view is a fold over a prefix of the event array, and live is
  just the cursor at the end.** §5 Phase 7 wants replay to use "the identical
  rendering path as live", and the way that claim usually rots is two paths that
  agree today. There is one: `view === reduceAll(events.slice(0, cursor))`.
  Folding forward is incremental so a long run stays linear; folding backwards
  starts over, because the reducer has no inverse and giving it one would be a
  second definition of what each event means.
- **2026-09-10 — the scrubber is outside the identity boundary, and the graph
  camera is inside it.** The transport control honestly differs between live and
  replay — at event 12 of a finished run you are standing somewhere, and live you
  were at the end. The camera is the opposite case: it looked like view state and
  was really a hidden dependency on *when* nodes arrived, which is why it is
  computed arithmetically now rather than fitted. See the Phase 7 bug note.
- **2026-09-10 — the terminal summary is rendered as a claim, beside a count of
  what executed.** Four live runs have now announced work the log shows never
  happened. The summary and the `tool.called` events are separately observable
  precisely so they can disagree, and the UI would be repeating the confabulation
  if it presented one as the other.
- **2026-09-10 — the SSE client closes itself on a terminal event.** The server
  ends the response when a run ends, and `EventSource` treats every ended response
  as a dropped connection — so without this a finished run is re-requested every
  second for as long as the window stays open. Nothing fails and nothing is
  visible; it just polls forever. This is the one piece of protocol knowledge the
  client cannot get from the frames themselves.
- **2026-09-10 — the API types are generated by this repository, not by
  `openapi-typescript`.** That tool caps its TypeScript peer at `^5.x` against the
  6.0.3 here, and the alternative is `--legacy-peer-deps` on every install,
  weakening peer checking across the whole tree for one dev tool. Same trade Phase
  0 refused with `eslint-plugin-import`; there a maintained fork existed and here
  none does. The emitter raises on any keyword it does not understand rather than
  emitting `unknown`, because a generator that degrades silently produces types
  that check nothing while looking verified.
- **2026-09-10 — the schema and the generated types are committed.** A build step
  that starts the sidecar to read `/openapi.json` makes the frontend's typecheck
  depend on a working Python environment and turns a type error into a startup
  error. Committing both also makes drift visible in a diff. `just schemas`
  regenerates; a test compares them byte for byte against the live app.
- **2026-09-10 — the approval dialog renders the run's decision history.** A
  denial stops a call, not a run, and the supervisor will spawn a second worker
  and ask the same question again — watched live in Phase 6 and again in Phase 7.
  A dialog showing only what is outstanding makes two questions look like one.
- **2026-09-10 — the log panel's filters are component state, not run state.**
  Which rows a person is looking at is a fact about the person. Putting it in
  `RunView` would make the same log fold to different states, which is the one
  thing the whole design is built to prevent.
- **2026-09-10 — no relative timestamps anywhere.** "3 seconds ago" would make
  the same event render differently on every fold and quietly break the replay
  criterion. Times come from the event's own `ts`, which travels in the log.
- **2026-09-10 — a tool call happens in two stages, and the gate sits between
  them.** `Tool.prepare` validates and resolves while touching nothing;
  `Tool.execute` carries out an already-approved call. §5 Phase 6 requires
  traversal to be "rejected before the approval prompt is even shown", and the
  split is what makes that structural instead of an ordering a call site has to
  remember. An approval dialog is a question put to a human, and a question is
  only safe to ask if every answer is survivable — so a call that cannot be
  allowed is never offered as a choice.
- **2026-09-10 — the approval prompt is built from the resolved call, not the
  arguments.** `Prepared.summary` describes what would actually run, so the
  sentence the user reads and the call that executes cannot disagree. Rendering
  raw arguments would describe a different call from the one about to happen,
  which is where a confused-deputy bug lives. It also means `write_file` says
  "overwrite" when the file exists and "create" when it does not, which is a
  different decision for the user and was confirmed live.
- **2026-09-10 — the rendered prompt travels in the `approval.requested`
  payload.** §2 makes the UI a projection of the log, so a client composing its
  own wording could show one thing while the log recorded another. The
  Allow/Deny is the UI's; the sentence is the backend's.
- **2026-09-10 — an auto-approved call still writes its row and emits both
  events.** Skipping them is the obvious optimisation and it destroys the only
  answer to "what did this run do without asking me". `tool.approved` carries
  `automatic` so a person's yes and a policy's yes stay distinguishable.
- **2026-09-10 — the gate blocks on the run's wall-clock budget, not its own
  timeout.** A separate approval deadline is a second limit to configure and
  explain, and the two disagree in the obvious case: a run with five minutes
  left waiting on a ten-minute window is waiting for a decision it can no longer
  act on. `Run.remaining_seconds` is the bound, and expiry settles the row —
  which is what §4's `expired` status is for.
- **2026-09-10 — pending approvals are expired at startup.** Their waiters are
  `asyncio.Future`s in a process that no longer exists, so resolving one would
  update a row and unblock nothing. Left alone they appear in the Phase 7 dialog
  as live questions about runs that ended when the app last closed.
- **2026-09-10 — an empty `auto_approve` on a definition means inherit, not
  none.** §4 defaults the column to `'[]'` and every built-in carries it, so a
  strict intersection makes the workspace policy inert — a setting that reports
  success and changes nothing. The escalation rule is untouched: every branch
  still returns a subset of the workspace policy. Full reasoning in "The design
  decision worth not re-litigating (Phase 6)"; do not restore the strict reading
  without reading it.
- **2026-09-10 — `tool.denied` carries `blocked_by`.** An allowlist refusal, a
  sandbox violation and a user's "no" are all `tool.denied`, and they are very
  different things to see in a run. Without the discriminator a graph UI shows a
  prompt-injected agent probing the boundary and a routine declined write
  identically.
- **2026-09-10 — the sandbox resolves before it compares, and never inspects
  strings.** A search for `".."` rejects the legitimate `reports/../notes.txt`
  and misses a symlink, which is the escape that works. It also means an
  absolute path is judged by where it points rather than refused for being
  absolute.
- **2026-09-10 — `http_get` refuses non-public addresses and does not follow
  redirects.** §1 constraint 3 keeps other machines off the sidecar and does
  nothing about an agent fetching `127.0.0.1:8787/settings` from inside a run.
  A redirect is how a checked public URL becomes an unchecked private one, so
  the target is handed back for the agent to request explicitly — which puts it
  through the check and the gate again.
- **2026-09-10 — `run_shell` claims a hard timeout and does not claim network
  isolation.** The timeout kills the process tree, because killing the direct
  child leaves the real work running — the Phase 1 bootloader lesson. Network
  denial is not enforceable in-process cross-platform and the module says so
  rather than implying otherwise; §5 Phase 6's own addendum already concedes the
  point and puts real isolation in a container outside the shipped build.
- **2026-09-10 — the supervisor is handed no `ToolRuntime` at all.** It has no
  `allowed_tools`, so `_permit` can never route it to a catalogue tool and a
  runtime would be unreachable machinery. The one agent present in every run
  stays the one that touches nothing.
- **2026-09-10 — the workspace approval policy is snapshotted at run start.**
  Same rule as the limits and the roster, and the direction that matters is
  widening: a policy loosened mid-run would stop the gate asking while work was
  already in flight.
- **2026-09-10 — migration 004 widens the seeded built-ins conditionally.** The
  `UPDATE`s are guarded on the row still holding its seeded `'[]'`, so a
  definition the user edited before upgrading survives. The one case it cannot
  distinguish is a user who deliberately emptied a built-in's allowlist; they
  get the default back once. That is the smaller harm than a researcher which
  can read nothing on every fresh install.
- **2026-09-10 — the supervisor picks workers from a roster; it can no longer
  invent one.** §5 Phase 5 says the registry "constructs workers from rows", so
  `spawn_agent` takes an `agent` name from `agent_defs` instead of Phase 4's
  free-form `name` + `role`. An agent's identity stops being whatever a model
  typed. The roster travels in the supervisor's system prompt, not in the tool
  description, because it differs per run — it is whatever the user has defined
  and enabled at the moment the run started.
- **2026-09-10 — the supervisor is not a definition.** §5 Phase 5 says the
  registry constructs *workers* from rows. The supervisor is orchestration
  machinery rather than a role a user would edit, so it stays in code, holds no
  `allowed_tools`, and can never reach the tool catalogue. The one agent present
  in every run and unreachable by the editor is therefore also the one that
  touches nothing.
- **2026-09-10 — built-ins are seeded by migration 003, not by startup code.**
  §5 Phase 5 asks for definitions seeded "on first launch". A startup check has
  to distinguish "never seeded" from "seeded and since edited", and getting that
  wrong silently reverts a user's edit on upgrade. A migration runs exactly once
  by construction, so the question never arises. Their ids are fixed uuid4
  literals so "the built-in researcher" is one identity on every machine.
- **2026-09-10 — every seeded built-in has an empty `allowed_tools`.** Not a
  placeholder: §5 Phase 5 says an empty array means the agent "can reason and
  hand off but touches nothing", which is exactly true while no tool is
  implemented. A built-in seeded with `write_file` would spend a step
  discovering it cannot use it. Phase 6 widens these rows when there is
  something for them to point at.
- **2026-09-10 — a worker's system prompt is the user's text plus a fixed
  protocol addendum, and `agent.spawned` records the composed result.** A
  definition's prompt says what the agent is for; it cannot say how to end a
  turn, because that is a fact about this orchestrator a user has no reason to
  know. The addendum names only `finish` and `handoff`, which every agent holds
  regardless of its allowlist, and grants nothing. The log records what was
  actually sent — that is what explains the model's behaviour on replay — while
  `definition_id` records which row it came from.
- **2026-09-10 — the system prompt is now in the event log at all.** It
  previously appeared in no event: `llm.request` carries the message list, and
  the system prompt travels beside it as a separate provider argument. That was
  a real hole in Phase 4's reconstruction claim, and it became acute once the
  prompt was user-authored data. It goes in `agent.spawned`, once per agent
  rather than once per step.
- **2026-09-10 — the allowlist is enforced against `spec.allowed_tools`, never
  against the offered tool list.** Not offering a tool is not the same as
  blocking it: a model can name any string, which is why `_unknown_tool` exists
  at all. Exposure and enforcement read different sources so neither can quietly
  become the other's proof. `test_a_tool_offered_by_mistake_is_still_refused`
  builds an agent whose two lists disagree, which is the only way to tell them
  apart — everywhere in the product they are built from each other.
- **2026-09-10 — a permitted catalogue tool is still not executed.** Being on an
  agent's allowlist is permission from the *definition*; it is not permission
  from the *user*, which is what Phase 6's gate collects. So the call stops after
  `tool.requested` with a `tool.error`, and no `tool.called` is written —
  `tool.called` means the call executed, and a Phase 5 that emitted it for a
  tool with no implementation would be writing a log entry that is not true.
- **2026-09-10 — a definition's `provider`/`model` are honoured at run time.**
  §4 gives the columns "NULL = inherit workspace default", and `ProviderPool`
  resolves, caches and budget-wraps one provider per distinct pair. Storing the
  columns without honouring them would have been the Phase 4 settings bug again:
  a value the product accepts and silently ignores.
- **2026-09-10 — `max_steps` is clamped at spawn as well as validated on write.**
  The write-time check compares against the workspace cap, and the cap is a
  setting that can be lowered afterwards. A rule enforced only on write stops
  holding the moment the thing it depends on changes.
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
