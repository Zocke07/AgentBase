# Running tasks

[Guide contents](README.md) · [Next: Agents](3_agents.md)

## Start a run

1. Select the space that should own the task. If it needs existing files,
   put them in the folder opened by **Space settings → Open folder**.
2. Open **Home** and enter a concrete task, for example:

   > Write a short note explaining SQLite in plain language and save it as
   > sqlite.txt in this space's folder.

3. Click **Start run**, or press **Enter** in the task box. **Shift+Enter**
   inserts a new line. If setup is incomplete, the notice above the box
   explains what needs attention.

The run opens in **Runs**. The supervisor works with the agents enabled in
this space when the run starts. **New run** in the Runs list returns to
Home's task box.

## Watch the work

The run view shows its status and counts of agents, tool calls, denials,
tokens, errors and cost. The sentence above the canvas describes what is
happening now. The canvas reads left to right as a workflow: the **Goal**
card, the supervisor, the workers it handed work to, and the **Outcome**
card. Each agent card carries a state pill (ready, thinking, model, tool,
approval, done), a sentence for what it is doing, its model, and chips that
sum what it did with each tool: a green count for executions, a red one for
denials, and a pulsing chip while a call runs. Arrows carry the handoff task;
a handoff back to the supervisor is drawn beneath the cards. Click a card to
open the inspector beside the canvas: the agent's last message, whom it handed
off to, every tool call with its result or the reason it was refused, and its
system prompt and streamed output. Scroll to zoom and drag to pan; the camera
frames the whole run again when a new agent appears unless you have moved it.

The event log below the graph tells the story in order. Use **Agent** and
**Type** to filter it, **Find** to search, and **show tokens** to include
streaming chunks that are hidden by default. Click a row to inspect its
recorded details; a row that carries an agent's message or the run's summary
shows that prose formatted above the raw payload, with **Save as note**. The
log follows new events while you are at the bottom; **↓ newest** returns
there after you scroll up.

When a run finishes, **The supervisor's account of the run** shows what the
model says it did, with its Markdown rendered; a long account starts folded,
with **Show the whole summary** beneath it, so the canvas and the log stay in
view. Verify the result with the event log and the actual files.
A `tool.called` entry shows that a call executed; inspect `tool.result` or
`tool.error` to see how it ended. Tool-call totals also include coordination
calls, so a nonzero count alone does not prove that a file was written.

Under the account, **Saved as a memory at** names the note the run wrote and
its status: **proposed** until you decide, **approved** once later runs may
retrieve it, **pinned** or **archived**. **Approve** decides it right there;
**Open in the inbox** opens the note beside the Knowledge inbox, where it can
also be pinned, merged or forgotten (see
[The memory inbox](6_knowledge_and_memory.md#the-memory-inbox)).

A model may send text in large chunks, or call tools without sending prose.
The graph and log can show activity even when no text is streaming.

## Approvals

A fresh install asks before every file, shell or network tool call, including
reads. **Approval needed** appears in a panel above the graph, with the risk
level, the requested action, the agent's name and **Deny / Allow** buttons.
The graph, log and replay controls stay available while you consider it.

| Tool | Risk | Effect |
|---|---|---|
| `read_file` | low | Read a file inside this space's folder. |
| `list_dir` | low | List a directory inside this space's folder. |
| `search_knowledge` | low | Retrieve relevant Markdown chunks with note and heading citations. |
| `write_file` | medium | Create or overwrite a file inside this space's folder. |
| `http_get` | medium | Fetch a public URL; local and private network addresses are refused. |
| `run_shell` | high | Run a shell command as your user, starting in this space's folder, with a timeout. |

File-tool attempts outside the space folder are refused before an approval
question appears. That check does not make every requested action harmless:
a permitted write can overwrite your work. **Shell commands can reach the
rest of your disk and the network.** Their starting folder and timeout do
not isolate them from your user account. Read the command before allowing it.

**Deny** stops that call and tells the agent it was refused. The run can
continue. If any agent in the same run repeats the same tool and arguments,
the earlier denial is applied automatically and recorded **by your earlier
answer**. Different arguments can produce a new question. A denial does not
carry over to another run.

An unanswered request expires when the run reaches its time limit. Cancelling
the run also ends its waiting approvals. If the app closes while a question
is pending, it is expired on the next start. No pending call is approved by
waiting or restarting.

The header's approvals indicator covers all spaces. Click it to open a
waiting run. If you are replaying an earlier point, click **Jump to end** to
answer a current question. Old questions in a finished run are read-only.

## Replay, cancel or delete

Select a run in **Runs**, then drag **Replay** to see the graph and log at
an earlier event. **Jump to end** returns to the latest event. Viewing an
earlier point does not pause an active run.

**Cancel run** stops an unfinished run and records why it ended. It does not
undo files or other effects from calls that already ran. Switching sections
or spaces leaves runs running; quitting AgentSpace stops its local server.

A finished run offers **Delete run…** and an inline **Delete / Keep**
confirmation. Deletion removes the run, its event log and approval history.
Its spending stays in the monthly total, and files it wrote stay in the
space folder. Cancel an active run and let it finish stopping before deleting
it.

Discord runs appear under the space selected in
**Settings → Chat channels → Where a chat command runs**. They can be
watched and replayed in the same way.

## Budget and limits

The header's meter shows this month's spending across **all spaces**, against
one cap. Change it at **Settings → Monthly budget → Monthly cap (USD)**.
The default is $20.00. The app records a warning at 80% and checks its price
estimate before a model call, refusing calls that would exceed the remaining
budget. The accounting month uses UTC.

Spending uses token counts and the prices bundled with this build. Your
provider's bill is authoritative. For ChatGPT subscription access, this is an
API-equivalent safety estimate and is not an API charge; it keeps the same
AgentSpace cap in force for both OpenAI access modes. Ollama adds no cost.
Choosing a different space or deleting run history does not reset spending.

| Limit | What happens when it is reached |
|---|---|
| **Steps per agent** | A worker stops and reports what it has. If the supervisor runs out before finishing, the run fails. |
| **Agents per run** | A request for another agent is refused and the supervisor can continue with the agents it has. The count includes the supervisor. |
| **Seconds per run** | The run fails and waiting approvals expire. Time spent waiting for approval counts. |

Set defaults in **Settings → Limits and approvals**, and overrides in
**Space settings**. An agent's own **Max steps** can further restrict its
turns. Local models may need more time or steps, but higher limits do not
make a model capable of finishing every task.

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

- **AgentSpace has to be open.** The local server is part of the app, so a
  time that passes while the app is closed cannot start anything then. Each
  schedule chooses what happens instead: **Run it once when AgentSpace next
  opens** (the default) or **Skip it and wait for the next time**. Either
  way the following time is computed from the clock, so a laptop shut for a
  week runs the schedule once on opening, not seven times.
- **Nobody is there to approve.** A tool call the space's policy does not
  pre-authorize waits for you up to the run's time limit and then fails. The
  Schedules section says what the space can call without asking; tick the
  risk levels you trust under **Limits and approvals** (see
  [Run without answering every call](#run-without-answering-every-call))
  before scheduling work that writes files or fetches pages.

A schedule whose previous run is still going skips that time, and one whose
space is archived turns itself off.

## Follow cost, tokens and context

**Usage** (Ctrl/Cmd+5) is a month of model calls from the same ledger the
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
