# Verification and remaining work

Updated 2026-09-19. This is the current record; the
[historical session notes](history/README.md) retain earlier evidence and
superseded gaps. A test result below is scoped to what was actually executed.

## After 0.4.0: the Obsidian button, the investment roster, the canvas, panels and per-tool answers

On 2026-09-19 the maintainer clicked **Open in Obsidian** on a Mac without
Obsidian and got the launcher's exit status as the error. The shell now has
an `obsidian_available` command that looks for Obsidian where its installer
puts it (`/Applications` and `~/Applications` on macOS, `%LOCALAPPDATA%`'s
`Programs\Obsidian` and `Obsidian` on Windows), the Knowledge toolbar offers
the button only when it answers yes, and a failed open reports what still
works (the folder in Obsidian's own picker) while the launcher's error goes
to the shell's stderr. Executed: `cargo test` (3, including the candidate
paths per platform), `cargo clippy --all-targets -D warnings`, `cargo fmt
--check`, `just check`, and `KnowledgeView.test.tsx` (18, two new: the
button absent when the shell says no, and the shell's refusal shown in
words). **Not exercised:** a Mac or Windows machine with Obsidian installed,
so the positive path (button shown, vault opened) rests on the earlier 0.3.x
check of the URI and on the path list.

The same day, at the maintainer's request, migration 010 made the default
space's built-ins the ten definitions of the investment research pipeline
(`store/010_investment_roster.sql`), with the three generic roles kept as
the starter roles a new space is seeded from. Executed:
`test_investment_roster.py` (15) covers the fresh roster's models, tools,
step ceilings and narrowed approval lists, the no-shell and collectors-only
fetch properties, the bear prompt mirroring the bull, an upgrade from a
version-9 database in which an edited writer survives as a deletable row, an
untouched researcher and reviewer are retired, and a user's own `decision`
agent keeps its row while the shipped one is skipped, and an untouched
researcher moved to another space staying there, deletable. The rest of the
backend suite passes with the shared `agents` fixture seeding the starter
roles beside the roster (764 passed, 11 skipped, the DNS-bound sandbox and
tools files deselected here), `just check` passes and the OpenAPI snapshot
was regenerated for one docstring. **Not exercised:** a run of the pipeline
against a model, which needs the config files and scripts the prompts assume
and the user guide lists; and the migration against the maintainer's own
0.4.0 database, which happens at the next launch of a build carrying it.

Later that day, three more of the maintainer's requests. The run canvas's
handoff labels moved into React Flow's HTML label layer (`HandoffEdge` in
`RunGraph.tsx`): every forward handoff turned on one vertical run between
the columns and a label at a path's centre was crossed by its siblings, so a
forward label now sits over the last stretch into its card and a return
label under the card it leaves, each with the whole task as its tooltip, and
cut-short card text carries its full text as a title. The run list, the
canvas and the inspector gained drag handles (`Splitter.tsx`, sizes kept per
browser by `useStoredSize`). And the gate gained per-tool answers: the
settings' `tool_policies` (ask / allow / deny, validated against the
catalogue), a space's stricter copy (migration 011 adds `spaces.tool_policies`
and `approvals.scope`), `ToolRuntime.policy_for` (an allow narrowed by a
definition's levels), `ApprovalService` refusing by policy or allowing by a
run-wide precedent, `POST /approvals/{id}` taking `scope`, and the dialog's
**Allow for this run**. Executed: `just check`; **777 backend tests** pass
(`test_approval_gate.py` gained five: refusal without asking, an allow
running unasked, a definition narrowing an allow, a run-wide yes answering
a later write but not a read, and a no never being for a run;
`test_tool_runtime_policy.py`, the settings, spaces and approvals API tests
cover the rest); **424 frontend tests** (39 files) pass, with the reducer
keeping `policy`, `precedent` and `scope` apart, the dialog's third button,
the Settings table dropping an answer set back to ask, and the space table
offering only stricter answers. Exercised in Chrome against the scratch
sidecar (migrated 9 to 11 on a database with runs): a seeded three-worker
run showed every handoff label clear of the lines, the three handles were
dragged with real mouse events, clamped so the log kept its minimum, and
the sizes survived a reload; the Settings table showed `read_file` allowed
and `run_shell` refused after a PATCH, the space table offered ask or deny
for the allowed tool, deny alone for the asking ones and nothing for the
refused one; a slow demo run's dialog showed Deny, Allow and Allow for this
run. **Not exercised:** the gate against a live model (the demo run's
approval events bypass the store, so its third button answers a 404); a
space's stricter answer changing what a real run does, covered by
`test_per_tool_answers_only_get_stricter` and the API tests only.

## 0.4.0: scheduled runs, Usage, the tour, and two layout fixes

Phase 13, on 2026-09-19, in seven commits after 0.3.3. The sidecar gained
migration 009 and `store/schedules.py` (three cadences, `LocalZone`,
`next_occurrence`, a store that keeps `next_run_at` consistent with
`enabled`), `orchestrator/scheduler.py` (one task: a catch-up pass at launch,
then sleep until the earliest time or a 60 s poll, launching through
`RunLauncher` with origin `schedule`), `api/schedules.py` (CRUD, run-now,
preview) and `budget/usage.py` behind `GET /usage`; `RunOrigin` gained
`schedule`, the settings response gained `version`, `data_dir` and the
`onboarding_completed` setting. The window gained the Schedules section in
Space settings, the Usage section, the tour and About box, per-agent usage in
the run inspector, the folded summary with the memory row, and the Agents and
canvas fixes.

Executed: `ruff`, `ruff format --check`, `mypy --strict` over `src` and
`tests`, and **747 backend tests** pass with 11 skipped (the 74 deselected are
`test_sandbox.py` and `test_tools.py`, whose `example.com` lookups fail on this
Mac's DNS; CI runs them). `test_schedules.py` (19) covers the cadence
arithmetic with a hand-written summer-time zone, including 09:00 the morning
after a DST switch landing at 07:00 UTC, `LocalZone` against the C library
under `TZ=Europe/Amsterdam`, the store, and the scheduler's passes: a due
schedule fires once with origin `schedule`; a schedule three days overdue at
launch runs once or is skipped per its policy and moves to tomorrow either
way; a schedule whose previous run is still going is skipped; an archived
space turns its schedule off; the loop fires on time and wakes for an edit.
`test_api_schedules.py` (9) and `test_api_usage.py` (3) cover the endpoints,
including the space-narrowed and prior-period reports and a deleted run's
spend listed as such. `tsc`, `eslint --max-warnings 0` and **408 frontend
tests** (37 files) pass, including `replayIdentity.test.tsx` over the reducer's
new per-agent fields, and `test_repo_hygiene.py` passes.

Exercised in Chrome against a scratch sidecar on port 8790 (the maintainer's
own 0.3.3 held 8787; the page's requests were rewritten over CDP) with
screenshots read back: on a fresh data directory the tour opened on the
sidecar's flag, every step spotlit its target with the section switched
beneath it, the keys step scrolled its target into view after a fix, **Try a
demo run** from the last step started the scripted run, closed the tour and
opened the run, and `onboarding_completed` read `true` afterwards; a weekly
schedule was created from the picker with the preview reading "Weekdays at
09:00. Next: Mon, Sep 21, 09:00 AM, ..."; **Run now** started a run and the row
read "Started by hand." with a link to it; with `next_run_at` set into the
past in SQLite the poll started a run with origin `schedule` within 70 s and
moved the schedule to Monday; after the sidecar was stopped, the schedule set
three days overdue and the sidecar restarted, the row read "Started a run:
the app was closed at 01:23 on Wednesday 16 September, so it ran at launch."
and the next time was again Monday, not three runs. The Usage page rendered
seeded spend rows (ten calls across three runs and a deleted run) with the
cards, the day bars, both tables and the run table, narrowed to the space and
widened to all spaces. With a second space, the Agents editor showed the
move-or-copy bar above the editor and the tools list cut short with ellipses
(a second overflow, the fieldset's min-content width, was found here and
fixed). A completed demo run showed the "read 1" chip, the Outcome title with
its pill, the handoff label between the cards and the return handoff beneath
them; the inspector listed the researcher's one model call, 412 in, 38 out,
and 412 tokens of context.

**Not exercised:** the Tauri window itself (no screen access here); a
scheduled run against a real model (every scratch run failed at once for want
of a key, as expected, which is also how a schedule's failure reads in Runs);
a DST switch on the real clock rather than the injected zone; the memory row
against a run that wrote a memory (the demo run writes none; the row is
covered by `RunSummary.test.tsx`); and the Usage bars past a month with rows
on every day, which the flex layout would compress to about 30 bars.

## 0.3.3: Obsidian-flavoured vault, workflow canvas, shell shortcuts

Frontend-only work on 2026-09-18, released as 0.3.3, in four commits. The vault
gained a parser for the Obsidian dialect (`lib/markdown.ts`: frontmatter
properties, wikilinks with aliases and headings, embeds, tags, highlights,
strikethrough, callouts with fold state, nested and task lists, tables, code
fences, a single newline as a break) and a renderer (`components/Markdown.tsx`)
that builds elements from the tree and never from strings; `Markdown.test.tsx`
asserts that a `<script>` and an `<img onerror>` in a note stay text and that
only `http`, `https` and `mailto` become links. The Knowledge section is laid
out as a vault: a folding folder tree, the note head with path, tags and
properties, source and preview, a links pane, a status line, `[[` completion,
a formatting bar, a quick switcher (Ctrl/Cmd+O) that creates missing notes,
Ctrl/Cmd+S and Ctrl/Cmd+E, an unsaved-changes guard, task boxes that write
back to the source, tags that filter the tree, a force-directed graph with a
local scope, and toasts. The run canvas draws goal, supervisor, workers and
outcome as cards with state pills and per-tool chips, routes return handoffs
beneath the cards, and opens an inspector with the agent's last message,
handoffs and tool calls. Citations on Home and in a run open their note; the
rail badges approvals and proposed memories; Ctrl/Cmd+1..6 switch sections.

`tsc`, `eslint --max-warnings 0` and **384 frontend tests** (34 files) pass,
including `replayIdentity.test.tsx` against the new canvas and inspector, and
`test_repo_hygiene.py` passes. Exercised in Chrome against a scratch sidecar
(`AGENTSPACE_DATA_DIR` under the session scratchpad, Vite on 5173, headless
Chrome over CDP with screenshots read back): a seeded note with callouts,
highlights, nested tasks, a table and a fenced block renders in split,
preview, light and dark; a `[[note#heading|alias]]` link opens the target;
the whole-vault and local graphs draw their edges; Ctrl+O finds a note and
offers to create one; typing `[[ret` in the source lists notes and Enter
inserts `[[Retention policy]]` and marks the note unsaved; the demo run's
canvas shows the four cards, both handoff edges with their labels and the
`read_file` chip, and clicking the supervisor opens the inspector; **Preview
context** on Home renders each excerpt and its citation opens the note in
Knowledge. Two collisions found only in the browser were fixed before the
commit: the quick switcher's `.switcher` class had restyled the space
switcher, and the editor's `.editor` class the agent editor. **Not
exercised:** the Tauri window itself (no screen access on this machine), the
external-link behaviour inside the shell (an `http` link copies its address
there, since the webview is granted no opener), and a vault near the
10,000-note limit, where the graph falls back to a circle past 600 nodes.

## 0.3.2: disk image, restart from Settings, dated snapshot prices

Checked on Apple Silicon macOS on 2026-09-18, from the first macOS field
report. Launch Services on this machine explained the report's "two
AgentSpace icons": the zipped app had only ever been opened from Downloads,
so Gatekeeper had registered six translocated copies under
`AppTranslocation`, and no copy sat in Applications for Spotlight to list.

The macOS download is now Tauri's `dmg` target, built with `CI=true` so the
Finder AppleScript is skipped on every host. The local
`AgentSpace_0.3.2_aarch64.dmg` is **24,571,117 bytes**, SHA-256
`cb5ddb4ac47284f79ea3afe9f3f0b300737942b0a72b8334f7aeab6b04a0da22`; mounted,
it holds exactly `AgentSpace.app`, `Applications -> /Applications` and the
volume icon. The sidecar froze at **22,130,976 bytes**, SHA-256
`99e9fec643199c8dca0eeb2e666d97448176827deea0608935ee84ab8240f8a1`.
`just build-installer`, `just verify-build` (**18 release checks passed**,
four Windows-only skipped: the rewritten `test_macos_dmg.py` mounts the image,
checks its two entries, copies the app out with `ditto`, and runs the earlier
version, executable-mode, strict-signature and sidecar launch checks on that
copy) and `just check-tauri` passed. The `test_ci_workflow.py` pins now
require the `bundle/dmg/*.dmg` upload and `dist/*.dmg` release asset and
refuse any `.app.zip`.

The shell gained `restart_app`, which stops the sidecar and then calls
Tauri's `AppHandle::restart` from a thread of its own, so Tauri's exit path
runs the `RunEvent::Exit` callback before it execs the new copy. Settings
shows **Restart AgentSpace** under the key list once a key has been written
or cleared, only inside Tauri; the Settings tests cover the offer appearing
after a change, the call to the shell, the disabled "Restarting…" state and
a refused restart, and `lib/shell.test.ts` covers the browser case. **The
relaunch itself has not been exercised live:** this machine has no screen or
accessibility access to click the button in the packaged app, and there is no
other way to invoke the command. The mechanism is the one
`tauri-plugin-process` exposes as `relaunch`, read from Tauri's source, and
clippy is clean.

`pricing._lookup` resolves an Anthropic `-YYYYMMDD` snapshot to its alias
price; `claude-haiku-4-5-20251001` now costs what `claude-haiku-4-5` costs,
and a snapshot of an unpriced family or an OpenAI-shaped date stays refused
(two new tests). `just ci` passed lint, formatting, mypy on both platforms
and the TypeScript checks with **787 backend tests** (12 skipped) and **338
frontend tests**; the five remaining backend failures were
`test_sandbox.py` and `test_tools.py` cases that resolve `example.com`, which
this machine's router resolver answered with AAAA records only during the
session, and they fail identically on the committed 0.3.1 tree. They are
network state, not code, and the tag workflow's test job re-runs them on
both runners.

## 0.3.1: the Codex runtime is fetched, not frozen

Checked on Apple Silicon macOS on 2026-09-18. The 0.3.0 sidecar carried the
Codex App Server runtime through `--collect-all codex_cli_bin`; measured
launch-to-healthy for three sidecar variants on the same machine, three runs
each, was 2.1 to 2.3 s for that 133 MB build, about 1.75 s for a 111 MB build
without the unused `codex-code-mode-host`, and 1.0 to 1.1 s for a 22 MB build
with no runtime. The `codex` binary itself is already arm64-only and stripped,
so nothing smaller than fetching it separately was available.

The sidecar now excludes `codex_cli_bin` and freezes at **22,131,376 bytes**,
SHA-256 `ad441a7ba41a3c1799e57b5e39e09d93089b8d997599311b4d2f5a41efe54ef2`;
`AgentSpace_0.3.1_aarch64-apple-darwin.app.zip` is **24,427,920 bytes**,
SHA-256 `c0c453c8dbdf0554f45bb19a55b3950755729ef6eb3d235af239c89d79a56d07`,
down from 135 MB. `just build-installer`, `just package-macos`,
`just verify-build` (**17 release checks passed**, four Windows-only skipped)
and `just check-tauri` passed.
Unit tests drive the installer against an in-process ASGI server with a
fake wheel: fetch, size and SHA-256 verification, unpacking only the members
the SDK uses with the wheel's own executable bits, atomic commit, reuse
without a second request, refusal of a hash mismatch, a short or oversized
body, an HTTP error, an unsafe member path and a wheel with no executable,
one shared task for concurrent callers, the development-checkout shortcut,
and an unsupported platform. A pinning test keeps `codex_runtime.json` equal
to the wheels in `uv.lock`. The frozen-sidecar tests now assert that
`/auth/chatgpt` reports the runtime as `missing` and that the binary stays
under 60 MB. The Settings tests cover fetch-then-sign-in with progress and a
refused download.

Live, with the frozen binary on a scratch data directory: `POST
/auth/chatgpt/runtime` fetched the real 112,690,061-byte macOS wheel from
PyPI in 15 s, the status went `preparing` then `disconnected` with the runtime
`ready`, the install held `bin/codex`, `codex-path/rg` and `codex-resources`
(217 MB, no wheel or helper binary left behind), `POST /auth/chatgpt/login`
through the fetched runtime returned a real `auth.openai.com` authorization
URL and was cancelled, and a relaunch reported the runtime ready with no
download. No account was signed in. `just ci` passed with **790 backend
tests** (11 skipped, the three archive checks waiting for the packaged
build) and **334 frontend tests**.

## 0.3.0: memory inbox, incremental retrieval and the inspector

The 0.3.0 additions were checked on Apple Silicon macOS on 2026-09-17. At
10,000 notes on disk, measured with a scratch vault: a cold index took 1.5 s,
a warm index 0.04 s (down from 0.84 s before chunk signals were precomputed
and the scan stopped resolving every path), and a query 0.02 to 0.11 s (down
from 0.33 to 0.54 s). `test_ten_thousand_notes_on_disk_index_and_search_within_bounds`
pins loose bounds of 5 s and 3 s against real files and took 6.4 s including
writing them. Focused tests cover citations on run memories and proposals,
merge with archived originals and a backup, pinning any note, unresolved
links and orphan counts, the merge and pin endpoints, the reducer's fold of
`run.started` excerpts and exclusions and `run.completed.memory_path`, the
Home preview's terms, token totals, model label and exclusion, the inbox's
provenance and merge flow, browser filters, daily notes, templates and
capture from the event log.

The Knowledge, Home and Runs sections were driven in headless Chrome against
the Vite dev server and a sidecar on a scratch data directory: a seeded vault
showed 3 orphans and 1 unresolved link, pinning wrote `pinned: true`, the
inbox showed a run memory's citation and **Open run**, merging two memories
produced a proposed `memory/merged/` note with both outcomes and citations
and archived the originals with `merged_into`, a note was created from
`templates/meeting.md` with `{{date}}` filled in, today's daily note opened,
**Preview context** listed two excerpts with 42 tokens sent to
`anthropic · claude-opus-5`, a run started over the API with one excluded
citation recorded it in `run.started` and the run view showed it struck
through, and **Save as note** wrote `captures/<run>-20.md` from the scripted
demo run. No real model was called; the Tauri window was not opened.

`just ci` passed with **774 backend tests** (11 skipped) and **332 frontend
tests**, with `ruff`, `ruff format`, `mypy --strict` on both platform targets,
ESLint and `tsc` clean. `just build-installer`, `just package-macos`,
`just verify-build` and `just check-tauri` then passed: the frozen sidecar is
**132,951,760 bytes**, SHA-256
`45d83b0863c3253e0a6f9a44e9985da38bf0689a21c861224d280b97836e0830`, and
`AgentSpace_0.3.0_aarch64-apple-darwin.app.zip` is **135,034,138 bytes**,
SHA-256 `285fafb2912bbad527297ec9740bb815d17ad6f096b1310eb973e2fffba52663`,
with **16 release checks passed** and the four Windows-only NSIS checks
skipped. The archive is five times 0.2.0's because the sidecar has bundled
the Codex App Server runtime (`--collect-all codex_cli_bin`) since the ChatGPT
subscription change; that size was recorded below but its effect on the
download was not called out until now. `replayIdentity.test.tsx`'s intermediate-position
test, which renders 58 panels in one test, exceeded its 5 s timeout in some
full-suite runs while the machine reported a load average above 100 from
system processes; it passed in isolation and in other full runs.

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
- **Restart AgentSpace** from Settings in the packaged app on either
  platform: the sidecar stopping, the window reopening, and the new sidecar
  binding port 8787 with the changed key in its handshake.
- Installing 0.3.2 from the disk image on a Mac by hand, and confirming
  Spotlight lists the app afterwards.
- A schedule firing in the packaged app against a real model with a
  pre-authorized policy, and its catch-up after the app was closed overnight.

The first Mac session already closed automatic browser SSE reconnect,
two simultaneous browser streams, clicking run deletion, both-theme replay
comparison, packaged startup/shutdown and the native keychain round trip.
See the history for the measured limits, including small graph measurement
differences in the pixel comparison.
