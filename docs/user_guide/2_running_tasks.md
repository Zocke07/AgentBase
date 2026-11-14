# Running tasks

[Guide contents](README.md) · [Next: Agents](3_agents.md)

AgentBase is built for work that runs on its own. A space's **Automations**
run goals at set times, or one after another, with no one at the window; a
task you want done once, and watched as it happens, is **Run once** on Home.

## Your portfolio

On **Home** in Main, the default space, open **My portfolio → Edit
portfolio**; other spaces have no portfolio. Add or remove stocks you
own, enter share counts, and optionally enter the average purchase price and
first purchase date. Leave unknown prices and dates blank. Each stock needs
its ticker and sector; company name, industry and exchange can also be edited.
Owned stocks are automatically watched, so put only additional stocks under
**Other stocks to watch**.

Enter your available cash, one currency for all amounts, and your three risk
limits as percentages of the whole portfolio including cash. **Save portfolio**
updates the data used by upcoming runs and the market watch. Changing a
currency label does not convert money. The shipped research follows the US
market; use USD for that portfolio. No trades are placed by this editor.

Unsaved edits stay in this window when switching spaces; **Cancel** discards
them. A failed save keeps your edits. If another window or a file edit changed
the saved data, reload it before saving. Finish or cancel an active run before
saving its inputs. Existing files are backed up before replacement.

After changing personal inputs, a manual morning run can review the same
market session again. Existing forecasts stay immutable. Your stocks take
priority over cached discovered stocks within the 50-stock research limit.

Below the summary, the card says when the portfolio was last valued and how
its value changed since the report before. When market sessions went by with
no research, because AgentBase was closed at 07:00, it names them: those days
have no research or forecasts, and none can be made afterwards. The portfolio
review and the decision say the same.

## Automations: work on its own

Open **Automations** (the second item in the rail, Ctrl/Cmd+2). The page says
in one paragraph what an unattended run in this space will do: which calls
run on their own, which sites a fetch may reach, what always asks, what
happens to a question nobody answers, and where a run stops. Below it is the
list of schedules.

The **Main** space ships an investment pipeline as five schedules, switched
off so nothing spends money until you choose. **Turn on the daily pipeline**,
on Home or in Automations, creates nine missing starter inputs and dashboard
files from templates, never overwrites an existing file, and switches the five
on:

| Schedule | When | What it does |
|---|---|---|
| Morning collection | Tuesday through Saturday at 07:00 local time on new defaults | Yahoo market discovery and headlines, prices, forecast actuals, company news and financial reports, Treasury auctions and the current book. No new session stops the daily chain. |
| Theses and risk | After Morning collection completes | The bull and bear cases, then the risk check against your limits. |
| Daily decision | After Theses and risk completes | A dated recommendation table for you to review, and the session's forecasts from the analysts' theses. Nothing is bought or sold. |
| Weekly knowledge | Saturdays at 09:00 | Concept notes from local knowledge and company notes from available financial reports or supplied filing text. |
| Weekly review | Sundays at 18:00 | Scores resolved predictions and proposes durable lessons for Saved context. |

Review the sample in **Home → My portfolio → Edit portfolio** before the first
run. It starts with one share
each of MU, ORCL, CRWV, MSFT, NOW and AVGO plus $2,500 USD cash; purchase
prices and dates stay unknown. Replace this sample with your real holdings
and cash. The sample limits are 10% per stock, 70% per sector and 3% daily
loss.

The same data remains available in **Knowledge → Technical Details → Agent
files** as `portfolio/positions.csv`, `config/watchlist.json` and
`config/limits.json`. Advanced edits there are reflected when the portfolio
form reloads; extra CSV columns and custom JSON metadata are preserved.

Monthly workbooks in `predictions/` keep one sheet per market session with
1-, 2-, 3-, 5- and 21-session forecast prices and later actuals. Open them
from **Knowledge → User Summary → Forecast workbooks** after updates. AgentBase must be open when
a scheduled run is due to collect data and update actual prices.
[Agents](3_agents.md#the-investment-roster)
describes their required fields and the files each deterministic tool writes.

To add your own, click **New schedule**, give it a name and a goal, and choose
when: **Every day** or **On chosen days** at a time of day (your computer's
local time), **Every few hours**, or **After another schedule**, which starts
it as soon as the chosen schedule's run completes. The editor shows the
sidecar's own reading of the choice ("Weekdays at 09:00", "After Morning
collection completes") and the next three times before you save. A chain can
have up to four stages, all in one space, and cannot loop. If a stage's run
fails or is cancelled, the chain stops there and the next stage says so.

Each row can be switched off, run now, edited or deleted, and shows the next
time, the last time, what happened then and a link to that run. **Run now**
starts it at once with the same limits as a timed start and opens the run;
it does not move the next time, and a stage started this way is followed by
the stages after it. A manual start appears in **Runs** as **started with Run
now**; a timed start says **from schedule**. Both are ordinary runs in every
other way: the space's agents, folder, rules, approval policy and the shared
budget all apply.

Four things to know before relying on one:

- **AgentBase has to be open.** A time that passes while the app is closed
  cannot start anything then. Each schedule chooses what happens instead:
  **Run it once when AgentBase next opens** (the default) or **Skip it and
  wait for the next time**. The same choice applies when the app closed while
  one of its runs was going: that run is failed at the next launch, and the
  schedule runs again once or is noted and left. Either way the following
  time is computed from the clock, so a laptop shut for a week runs the
  schedule once on opening, not seven times.
- **The computer has to be awake.** A time that passes while it sleeps starts
  once it has been awake for two minutes; the few seconds a closed laptop
  wakes now and then to check mail do not count. While a run is going,
  AgentBase keeps the computer from going to sleep on its own, but closing
  the lid still puts it to sleep and pauses the run.
- **Nobody is there to answer.** Calls the approval policy answers run on
  their own (see [Approvals](#approvals)). Anything else is still a question;
  in a scheduled run it waits **Seconds a scheduled run waits for an answer**
  (Settings, 120 by default) and then expires: the call does not happen and
  the run carries on without it. A question never turns into a yes.
- **Limits bound it.** Each run stops at its time limit and before a model
  call that could pass its **Dollars per run**, and the monthly cap still
  holds. A schedule can carry its own **Time limit for its runs**, so an
  overnight pipeline gets the hours it needs while runs you start in the same
  space keep the space's limit.

Different automations in the same space wait for the active automation and
its following stages to finish. This also applies when several missed jobs
are due at launch. The waiting jobs keep their due time; a failed or cancelled
run releases the space so the next job can continue. **Run now** is available when
that space has no other automation running. Different spaces remain separate.

A schedule whose previous run is still going skips that time, one whose space
is archived turns itself off, and a stage whose schedule is deleted is
switched off and says why.

## Market watch: alerts for sudden moves

**Market watch**, at the bottom of Main's **Automations**, keeps an eye on
prices between schedules; like the portfolio, it belongs to the default
space. Choose **Turn on**. While AgentBase is open, from 04:00 to
20:00 New York time on weekdays, it reads quotes every five minutes for your
holdings, your watchlist and the S&P 500, Nasdaq Composite and Dow Jones. No
model is used to watch, so watching costs nothing.

An alert fires when a stock moves 5% from the previous close, or 2.5% within
15 minutes; for an index, 1.5% and 1%. After hours, a move is measured from
that day's close, so an earnings reaction is its own alert. The same move
alerts again only when it grows by another 3% that day. **Change what raises an
alert** opens `config/monitor.json` in Knowledge, where every number can be
changed and other symbols added; quotes on a holiday alert nothing.

Each alert reaches you three ways:

- **Home** lists recent alerts, newest first, and the **Home** item in the
  sidebar counts the ones you have not seen.
- A **desktop notification**, unless Settings → Market alerts turns it off.
- A **Discord message**, when Settings → Market alerts names a channel (see
  [Integrations](4_integrations.md#market-alerts-in-a-channel)).

Then a short run, the `market-explainer`, reads that day's headlines for the
symbols and your saved research and writes `alerts/{date}-{time}.md`: the
likely reason with its sources, or a plain "No clear reason found". Home
shows the reason with **Read the sources** and **Open its run**, and a second
notification and message carry it. At most ten explanations start a day,
counted in New York time; past that, alerts arrive without one. An explanation
waits while another run in the space is going, and like any run its calls pass
your approval policy. It explains what happened; it never predicts or
recommends. Runs it starts are listed in **Runs** under **Market alerts**.

The watch stops when AgentBase closes: nothing is watched while the app is
closed, and it does not catch up on moves that happened then. After the
computer wakes, it waits two minutes before its next check.

## Run a task once

1. Select the task's space. Put needed files in **Space settings → Open folder**.
2. Open **Home**. Under **Run once**, enter a concrete task, for example:

   > Write a short note explaining SQLite in plain language and save it as
   > sqlite.txt in this space's folder.

3. Click **Start run** or press **Enter**. **Shift+Enter** adds a line. If setup
   is incomplete, the notice explains what to fix.

The run opens in **Runs** with agents enabled in that space at start. **New
run** returns to Home.

**Step through: ask me before every call** is the manual and debug path: every
tool call in that run waits for your answer, whatever the policy would do; a
tool the policy never allows is still refused. **Make this recurring** opens
Automations with a new schedule for the same goal.

Home also leads with one line on what runs here on its own: how many
automations are on and which is next, or **Automate a task** when none is.

## Watch the work

The left list shows selected-space runs, newest first. **Show** narrows by UI,
schedule, or Discord origin; cards label schedule/Discord runs. A run an
automation started is named after it, such as **Morning collection**, or
**Market alert: MU** for an explanation, with the start of its goal beneath.
Its header shows the same name, and **What it was asked to do** opens the
whole goal.

The run view shows status and agent/tool/denial/token/error/cost counts; the
sentence above the canvas gives current activity. Errors count failed tool
and model calls. A lookup that found nothing, such as a folder that does not
exist, is listed apart as a missed lookup: nothing was changed and the agent
was told. So is a request that could not be run as written, such as one with
garbled details, once the agent has sent it again and it ran: the run lists
it as a call sent again.

Under the sentence the run is drawn, as an **Office** or as a **Diagram**;
the switch is at the canvas's top left, and the window remembers the choice.

A run opens on the **Office**: a room with the supervisor's desk in front,
a desk for each worker behind it, and **You** at the reception, which says
where the run came from. The face on each character says what it is doing: a
dot (ready), moving dots (asking its model), a tool's symbol, a question
mark (waiting for your answer), a tick (done), or a warning. A desk at work
shows its state in words and the call in hand as a slip, stamped once it is
answered (allowed, denied, refused by the sandbox); a desk with nothing
going on, and nothing refused or gone wrong, shows its name alone until
you point at it or select it. A folder
travels from the supervisor to the worker it hands work to. The card on the
back wall holds the goal, what the supervisor said, in italics because it is
a claim, and the files the run wrote; the wall also shows the run's time
against its limit and its cost. Select a desk for the same inspector the
diagram opens. Drag to pan and scroll or pinch to zoom; the buttons at the
bottom right follow the work, show the whole room, zoom, and fill the
window. A run that is over shows the whole room. A question is answered in
the panel above the run, never in the room.

Beside the office the summary keeps the title, the counts and anything that
went wrong, with the first few files the run wrote and why it stopped,
and **More about this run** opens the rest: where it came from, what it
could do without asking, the notes it was given and the supervisor's
account. The event log starts folded to its latest step;
**Event log** opens it. The diagram keeps the whole summary and an open log,
and each drawing remembers its own log.

Read the **Diagram** left to
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
and inspector until Esc/reselect, in either drawing; in the diagram its
adjacent control fits the run.

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

Under the run's totals, **Wrote N files** lists every file the run's tools
wrote, from its log rather than from what an agent said. Select one to open it
in Knowledge where it belongs: a report, workbook or chart in **User Summary**,
in Preview; raw data and settings in **Technical Details**. A long
list shows six and folds the rest behind a count.

At finish, **The supervisor's account of the run** renders its summary; long
ones fold behind **Show the whole summary**. Verify it against files and the
event log. `tool.called` proves execution; inspect `tool.result` / `tool.error`
for outcome. Tool totals include coordination calls, so they do not prove writes.

**Saved a run summary at** names the note and whether it is available to later
runs, needs attention, is always included, or is history. In the default
**Automatic** mode, the space model manages it after a successful run and
records why. **Saved context** opens it for keeping, archiving, pinning,
combining, editing, or forgetting (see
[Saved context](6_knowledge_and_memory.md#saved-context)).

Models can send large text chunks or call tools without prose, so graph/log
activity need not stream text.

## Approvals

Every file, shell and network call passes the approval gate. On a fresh
install the gate answers low and medium risk itself (**Autonomous**, see
[The approval policy](#the-approval-policy)): reads, writes inside the space
folder, memory proposals, and fetches from the listed sites run on their own,
and each answer is recorded in the log with the rule that gave it. A shell
command, a fetch from any other site, and anything a narrower space or agent
policy does not answer still asks: **Approval needed** above the graph shows
risk, action and agent, with **Deny / Allow / Allow for this run**; graph, log
and replay remain available.

An install upgraded from 0.4.8 or earlier keeps the answers it had, asking
about everything until you choose **Autonomous** in Settings.

| Tool | Risk | Effect |
|---|---|---|
| `read_file` | low | Read a file inside this space's folder. |
| `list_dir` | low | List a directory inside this space's folder. |
| `search_knowledge` | low | Retrieve relevant Markdown chunks with note and heading citations. |
| `write_file` | medium | Create or overwrite a file inside this space's folder, except the app's own records. |
| `propose_memory` | medium | Propose durable saved context; its management mode decides whether the model handles it or it waits for you. |
| `http_get` | medium | Fetch a public URL; local and private network addresses are refused. |
| `read_feed` | medium | Fetch public RSS or Atom and return bounded, complete entries; local and private network addresses are refused. |
| `read_prices` | medium | Fetch one year of Yahoo daily prices for watchlist symbols and write stable price and mover files. |
| `read_market` | medium | Collect Yahoo gainers, losers, high-volume stocks and headlines, keeping configured holdings and watchlist stocks in the research universe. |
| `read_company_reports` | medium | Collect annual and quarterly Yahoo financial figures, with optional SEC filings metadata, company facts and bounded excerpts when an identifying contact is configured. |
| `track_forecasts` | medium | Record immutable forecast prices, fill due actual prices from saved US trading sessions, and maintain monthly Excel workbooks. |
| `compute_portfolio` | medium | Compute value, P&L, weights, concentration and limit crossings from saved positions and prices. |
| `check_limits` | medium | Check the book and thesis tickers against saved position, sector and daily-loss limits. |
| `score_predictions` | medium | Resolve predictions against saved trading sessions and write the ledger, scorecard, accuracy and calibration files. |
| `run_shell` | high | Run a shell command as your user, starting in this space's folder, with a timeout. Always asks. |

File calls outside the space folder are refused before approval, and so is
an agent's write into the space's `memory` folder, a hidden folder such as
`.obsidian`, or a note typed as a memory: memories reach the inbox only
through `propose_memory`. Permitted writes can still overwrite work. **Shell
commands can reach the rest of your disk and network.** Their start folder
and timeout do not isolate them from your account, which is why no policy can
answer them for you. Read them before allowing.

**Deny** stops that call and tells the agent; the run may continue. Any agent's
same-run repeat of identical tool/arguments is automatically denied and logged
**by your earlier answer**. Different arguments can ask again. Denials never
carry to another run.

**Allow for this run** permits this tool's later calls in this run from any
agent, regardless of arguments. They are logged as **allowed by your yes for
this run**. Other tools and next runs still ask. It is not offered for a
high-risk call: each shell command is asked about on its own.

In a run you started, an unanswered request waits until the run's time limit;
in a scheduled run it expires after the unattended wait (see
[Automations](#automations-work-on-its-own)), and the same call is not asked
again in that run. Cancelling ends waiting approvals. Pending requests at app
close expire on next start. Waiting, expiry and restart never approve them.

The header's all-space approvals indicator opens waiting runs. The window
checks for new runs, questions and schedule times every 30 seconds while
nothing is going. While replaying, use **Jump to end** to
answer a current request. Finished-run questions are read-only.

## Replay, cancel or delete

Select a run, then drag **Replay** to view graph/log at earlier events.
**Jump to end** returns latest; replay never pauses active work.

**Cancel run** stops unfinished work and records why; it does not undo prior
effects. Switching sections/spaces leaves runs active; quitting stops the local
server.

Finished runs offer **Delete run…** with **Delete / Keep** confirmation.
Deletion removes run, event log, and approvals but keeps monthly spend and
written files. Cancel active runs and wait for them to stop before deleting.

Discord runs appear in the space named in **Settings → Chat channels → Where
a chat command runs** and support the same watching/replay.

## Budget and limits

The header meter shows all-space monthly spending against one cap. Set it in
**Settings → Monthly budget → Monthly cap (USD)** (default $20.00). At 80%,
the app warns; before each model call it refuses estimates over remaining
budget. Accounting uses UTC months.

Spending uses this build's token prices; provider bills are authoritative.
Each step an agent takes re-sends its conversation so far, and providers keep
recently sent text in a cache: text read back from it costs a small fraction of
the normal price and text written to it a little more, at each provider's
published rates. Spending counts both, as the provider reports them.
ChatGPT subscription usage is an API-equivalent safety estimate, not an API
charge, enforcing the same AgentBase cap. Ollama costs zero. Changing space or
deleting history does not reset spend.

ChatGPT requests share a queue across all runs and models, with one request
active at a time and at least five seconds between starts. Temporary model
rate limits can retry twice after cooldowns of about 60 and 120 seconds,
respecting a longer server wait up to 180 seconds and the remaining run time.
A model that is at capacity for everyone ("Selected model is at capacity") is
waited out longer, about one, two and then four minutes, with the same model;
the log says the model is at capacity and how long it waits. If it is still
busy after that, the run stops with that reason. Choose another model for the
space or the agent in Space settings, or press **Run now** on the stopped
automation later; a stage started that way continues the chain.
The log shows the wait, and **Cancel run** also stops a cooldown. Requests
that already produced visible output and confirmed account usage or billing
limits do not retry. An account limit needs its allowance to reset or billing
to be resolved; switching models cannot guarantee that it will clear.

| Limit | What happens when it is reached |
|---|---|
| **Steps per agent** | A worker stops and reports what it has. If the supervisor runs out before finishing, the run fails. |
| **Agents per run** | A request for another agent is refused and the supervisor can continue with the agents it has. The count includes the supervisor. |
| **Seconds per run** | The run fails and waiting approvals expire. Time spent waiting for approval counts. |
| **Dollars per run** | The run fails before a model call that could carry it past this much: the ledger's total so far plus the most that call could cost. The default is $2.00; 0 leaves only the monthly cap. |

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

## The approval policy

**Settings → Limits and approvals → Calls that run without asking** sets the
policy every run acts under, and above all the runs nobody is watching.

| Choice | Calls that run on their own |
|---|---|
| **Autonomous** (recommended, the default) | Reads, folder listings and knowledge searches; writes inside the space folder; memory proposals; fetches from the listed sites. |
| **Supervised** | None; every call asks. Automations then do little on their own. |
| **Custom** | The risk levels you tick (**low**, **medium**) and the answers by tool below. |

High risk is not offered: `run_shell` runs commands as your user with no
isolation, so every call to it asks, whatever else is chosen.

**Sites a fetch may reach without asking** lists the hosts a web fetch may
reach on the policy's word (`news.google.com, stooq.com` on a fresh install;
an upgraded install starts at `*`, any public site, so nothing it did before
starts asking). Separate them with commas; `.stooq.com` covers that domain
and every name under it. A fetch from any other site asks, so a page an agent
reads cannot send your files to a site nobody chose.

**Seconds a scheduled run waits for an answer** (120 by default, 0 refuses at
once) is how long a question in a scheduled run waits before it expires. A run
you start keeps waiting for you.

Space and agent settings can narrow this permission, never widen it. A
space's own policy with nothing ticked is **Supervised** for that space; an
agent definition with nothing ticked inherits the space's effective policy.
Every automatic decision is recorded in the log with its reason, and the run
summary says what the run could do without asking.

### Answers by tool

Beneath the risk levels, **Answers by tool** lists every tool with one of
three answers. **Ask, by risk level** is the default: the levels above
decide. **Always allow** runs that tool without asking whatever its level
(a fetch still only to the listed sites). **Never allow** refuses it without
asking; the agent is told the app's policy never allows the tool, and the
refusal is recorded like a denial. An answer here comes before the levels, so
a **low** tick with `read_file` set to **Never allow** still refuses reads.
`run_shell` can be set to **Never allow** but never to **Always allow**.

A space can make an answer stricter in **Space settings → Answers by tool**:
an always-allowed tool can be made to ask or be refused there, and a tool
that asks can be refused. A space cannot loosen an answer. An agent
definition's own **Calls this agent may make without asking** narrows an
**Always allow** the same way: if the definition names risk levels and the
tool's level is not among them, that agent is asked. The surest way to keep
a tool away from an agent altogether is still to leave it out of the agent's
allowed tools.

## Follow cost, tokens and context

**Usage** (Ctrl/Cmd+6) is a month of model calls from the same ledger the
monthly cap is enforced on, so it agrees with the meter in the header; while it
is open, a run that spends refreshes it. The cards show what was spent
(against the cap, when every space is shown), how many model calls were made
across how many runs, and the input and output tokens. Below them: a place for
every day of the month with a bar on each day that spent (days are counted in
UTC, as the ledger records them), a table per model, a table per space, and
the costliest runs with their calls, tokens and **context**: the most tokens
any one call in that run sent, and the mean per call. A goal in that table
opens the run. The period picker offers every month the ledger has; **This
space** and **All spaces** narrow or widen the view.

Inside a run, click an agent's card to see its own model calls, tokens and
cost, and the context it carried on its last call and at most. Deleting a run
keeps its spend with the run cleared, listed under **deleted runs**, so the
month's total never shrinks by deletion.
