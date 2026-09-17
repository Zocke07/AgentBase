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
tokens, errors and cost. The sentence above the graph describes what is
happening now. Graph nodes show the supervisor and workers, and arrows show
handoffs. Click a node to inspect that agent's model, steps, allowed tools,
system prompt and any streamed output.

The event log below the graph tells the story in order. Use **Agent** and
**Type** to filter it, **Find** to search, and **show tokens** to include
streaming chunks that are hidden by default. Click a row to inspect its
recorded details. The log follows new events while you are at the bottom;
**↓ newest** returns there after you scroll up.

When a run finishes, **The supervisor's account of the run** shows what the
model says it did. Verify the result with the event log and the actual files.
A `tool.called` entry shows that a call executed; inspect `tool.result` or
`tool.error` to see how it ended. Tool-call totals also include coordination
calls, so a nonzero count alone does not prove that a file was written.

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
