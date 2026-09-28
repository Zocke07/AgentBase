# Running tasks

[Guide contents](README.md) · [Next: Agents](3_agents.md)

## Start a run

1. Select the task's space. Put needed files in **Space settings → Open folder**.
2. Open **Home** and enter a concrete task, for example:

   > Write a short note explaining SQLite in plain language and save it as
   > sqlite.txt in this space's folder.

3. Click **Start run** or press **Enter**. **Shift+Enter** adds a line. If setup
   is incomplete, the notice explains what to fix.

The run opens in **Runs** with agents enabled in that space at start. **New
run** returns to Home's task box.

## Watch the work

The left list shows selected-space runs, newest first. **Show** narrows by UI,
schedule, or Discord origin; cards label schedule/Discord runs.

The run view shows status and agent/tool/denial/token/error/cost counts; the
sentence above the canvas gives current activity. Read the canvas left to
right: **Goal**, supervisor, delegated workers, **Outcome**. Agent cards show
state (ready, thinking, model, tool, approval, done), activity, model, and
tool chips: green executions, red denials, pulsing active calls. Arrows label
handoffs; return handoffs run beneath cards and label their source. Hover
truncated canvas text for all content. Select a card for its last message,
handoffs, tool results/refusals, system prompt, and streamed output. Scroll to
zoom, drag to pan; new agents refit the camera unless you moved it.

Resize the list/run, supervisor account, canvas/log, and inspector edges by
dragging or arrow keys; double-click/Home resets them. Sized accounts scroll
instead of folding; sizes persist in the window. **Full screen** shows canvas
and inspector until Esc/reselect; its adjacent control fits the run.

The graph's event log is chronological. Filter by **Agent**/**Type**, search
with **Find**, or **show tokens** for hidden streaming chunks. Select a row for
details; message/summary rows render prose above raw payload and offer **Save
as note**. It follows events at bottom; **↓ newest** returns there.

To follow only what is happening, click **Event log** at the log's top left.
The log folds to one line naming the latest step (never a streamed fragment)
and the number of events, and the canvas takes its room; the sentence above
the canvas still says what the run is doing now. Click **Event log** again to
unfold it where you left it, with its filters as they were. The window
remembers the choice.

At finish, **The supervisor's account of the run** renders its summary; long
ones fold behind **Show the whole summary**. Verify it against files and the
event log. `tool.called` proves execution; inspect `tool.result` / `tool.error`
for outcome. Tool totals include coordination calls, so they do not prove writes.

**Saved as a memory at** names the note and status: **proposed**, **approved**
(retrievable), **pinned**, or **archived**. **Approve** acts in place; **Open
in the inbox** opens it for pinning, merging, or forgetting (see
[The memory inbox](6_knowledge_and_memory.md#the-memory-inbox)).

Models can send large text chunks or call tools without prose, so graph/log
activity need not stream text.

## Approvals

A fresh install asks before all file, shell, and network calls, including
reads. **Approval needed** above the graph shows risk, action, agent, and
**Deny / Allow / Allow for this run**; graph, log, and replay remain available.

| Tool | Risk | Effect |
|---|---|---|
| `read_file` | low | Read a file inside this space's folder. |
| `list_dir` | low | List a directory inside this space's folder. |
| `search_knowledge` | low | Retrieve relevant Markdown chunks with note and heading citations. |
| `write_file` | medium | Create or overwrite a file inside this space's folder. |
| `http_get` | medium | Fetch a public URL; local and private network addresses are refused. |
| `read_feed` | medium | Fetch public RSS or Atom and return bounded, complete entries; local and private network addresses are refused. |
| `run_shell` | high | Run a shell command as your user, starting in this space's folder, with a timeout. |

File calls outside the space folder are refused before approval. Permitted
writes can still overwrite work. **Shell commands can reach the rest of your
disk and network.** Their start folder and timeout do not isolate them from
your account. Read them before allowing.

**Deny** stops that call and tells the agent; the run may continue. Any agent's
same-run repeat of identical tool/arguments is automatically denied and logged
**by your earlier answer**. Different arguments can ask again. Denials never
carry to another run.

**Allow for this run** permits this tool's later calls in this run from any
agent, regardless of arguments. They remain logged **by your earlier answer**;
the originating answer is **for the rest of the run**. Other tools and next
runs still ask. Use **Answers by tool** for every-run policy.

Unanswered requests expire at the run time limit; cancelling ends waiting
approvals. Pending requests at app close expire on next start. Waiting/restart
never approves them.

The header's all-space approvals indicator opens waiting runs. While replaying,
use **Jump to end** to answer a current request. Finished-run questions are
read-only.

## Replay, cancel or delete

Select a run, then drag **Replay** to view graph/log at earlier events.
**Jump to end** returns latest; replay never pauses active work.

**Cancel run** stops unfinished work and records why; it does not undo prior
effects. Switching sections/spaces leaves runs active; quitting stops the local
server.

Finished runs offer **Delete run…** with **Delete / Keep** confirmation.
Deletion removes run, event log, and approvals but keeps monthly spend and
written files. Cancel active runs and wait for them to stop before deleting.

Discord runs appear in **Settings → Chat channels → Where a chat command runs**
and support the same watching/replay.

## Budget and limits

The header meter shows all-space monthly spending against one cap. Set it in
**Settings → Monthly budget → Monthly cap (USD)** (default $20.00). At 80%,
the app warns; before each model call it refuses estimates over remaining
budget. Accounting uses UTC months.

Spending uses this build's token prices; provider bills are authoritative.
ChatGPT subscription usage is an API-equivalent safety estimate, not an API
charge, enforcing the same AgentBase cap. Ollama costs zero. Changing space or
deleting history does not reset spend.

| Limit | What happens when it is reached |
|---|---|
| **Steps per agent** | A worker stops and reports what it has. If the supervisor runs out before finishing, the run fails. |
| **Agents per run** | A request for another agent is refused and the supervisor can continue with the agents it has. The count includes the supervisor. |
| **Seconds per run** | The run fails and waiting approvals expire. Time spent waiting for approval counts. |
| **Dollars per run** | The run fails once its model calls have cost this much, checked before each call from the ledger. The default is $2.00; 0 leaves only the monthly cap. |

Set defaults in **Settings → Limits and approvals**, and overrides in
**Space settings**. An agent's own **Max steps** can further restrict its
turns. Local models may need more time or steps, but higher limits do not
make a model capable of finishing every task.

Two more guards need no setting. An answer the model could not finish
within the output limit (16,384 tokens, typically a tool call that tried to
write a very large file in one go) is not run as a broken call: the log says
the call was cut off, and the model is told to do less in one answer. And an
agent that fails the same way three times in a row, or makes the identical
call three times in a row, is stopped with the reason **stopped after
failing the same way three times**, since each retry costs a whole context
window and learns nothing; the supervisor sees the reason and can finish
without it, and if the supervisor itself is the one repeating, the run
fails with that reason.

## Run without answering every call

In **Settings → Limits and approvals → Calls that run without asking**, tick
risk levels you want to authorize automatically and click **Save settings**.

| Selection | Calls that proceed automatically |
|---|---|
| Nothing | None; every tool asks. |
| **low** | Reads, folder listings and knowledge searches inside the space folder. |
| **low** and **medium** | Also writes inside the folder and public web requests. |
| **high**, with any other selection | Shell commands, with your user account's access to files and the network. |

The setting is an explicit grant for future calls at those levels. Automatic
writes may overwrite files, and web requests can carry data in their URLs.
Leave **high** unticked when you want to review each shell command.

Space and agent settings can narrow this permission. A space's own policy
with nothing ticked asks for everything; an agent definition with nothing
ticked inherits the space's effective policy. Automatic decisions are still
recorded in the log, with approvals marked **by policy**.

### Answers by tool

Beneath the risk levels, **Answers by tool** lists every tool with one of
three answers. **Ask, by risk level** is the default: the levels above
decide. **Always allow** runs that tool without asking whatever its level.
**Never allow** refuses it without asking; the agent is told the app's
policy never allows the tool, and the refusal is recorded like a denial.
An answer here comes before the levels, so a **low** tick with `read_file`
set to **Never allow** still refuses reads.

A space can make an answer stricter in **Space settings → Answers by tool**:
an always-allowed tool can be made to ask or be refused there, and a tool
that asks can be refused. A space cannot loosen an answer. An agent
definition's own **Calls this agent may make without asking** narrows an
**Always allow** the same way: if the definition names risk levels and the
tool's level is not among them, that agent is asked. The surest way to keep
a tool away from an agent altogether is still to leave it out of the agent's
allowed tools.

## Schedule a run

A space can run a goal on its own at set times. Open **Space settings →
Schedules**, click **New schedule**, give it a name and the goal to run, and
choose when: **Every day** or **On chosen days** at a time of day (your
computer's local time), or **Every few hours**. The editor shows the
sidecar's own reading of the choice ("Weekdays at 09:00") and the next three
times before you save. Each schedule can be switched off, run now, edited or
deleted, and its row shows the next time, the last time, what happened then,
and a link to the run it started. A scheduled run appears in **Runs** marked
**from schedule** and is an ordinary run in every other way: the space's
agents, folder, rules, approval gate and the shared budget all apply.

Two things to know before relying on one:

- **AgentBase has to be open.** The local server is part of the app, so a
  time that passes while the app is closed cannot start anything then. Each
  schedule chooses what happens instead: **Run it once when AgentBase next
  opens** (the default) or **Skip it and wait for the next time**. Either
  way the following time is computed from the clock, so a laptop shut for a
  week runs the schedule once on opening, not seven times.
- **Nobody is there to approve.** A tool call the space's policy does not
  pre-authorize waits for you up to the run's time limit and then fails. The
  readout at the top of the Schedules section says, in one paragraph, what an
  unattended run in this space will do on its own (the risk levels it may
  call, the tools always allowed or refused) and where it stops (steps per
  agent, agents per run, seconds per run). Tick the risk levels you trust or
  set the tools the work needs to **Always allow** under **Limits and
  approvals** (see [Run without answering every call](#run-without-answering-every-call))
  before scheduling work that writes files or fetches pages.

Set these per space, not app-wide: the space is the unit you schedule in,
and keeping the app defaults conservative means a run you start by hand
elsewhere still stops to ask. A schedule can also carry its own **Time limit
for its runs**, so an overnight pipeline gets the hours it needs while runs
you start in the same space keep the space's limit; the row says when a
schedule has one.

A schedule whose previous run is still going skips that time, and one whose
space is archived turns itself off.

## Follow cost, tokens and context

**Usage** (Ctrl/Cmd+6) is a month of model calls from the same ledger the
monthly cap is enforced on, so it always agrees with the meter in the header.
The cards show what was spent (against the cap, when every space is shown),
how many model calls were made across how many runs, and the input and output
tokens. Below them: a bar per day, a table per model, a table per space, and
the costliest runs with their calls, tokens and **context**: the most tokens
any one call in that run sent, and the mean per call. A goal in that table
opens the run. The period picker offers every month the ledger has; **This
space** and **All spaces** narrow or widen the view.

Inside a run, click an agent's card to see its own model calls, tokens and
cost, and the context it carried on its last call and at most. Deleting a run
keeps its spend with the run cleared, listed under **deleted runs**, so the
month's total never shrinks by deletion.
