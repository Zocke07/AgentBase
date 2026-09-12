# AgentSpace — User Guide

This guide is for the person who installed AgentSpace and wants to use it. It
assumes Windows and no programming background. If you want to run or build the
app from source instead, see the [Developer Guide](DEVELOPER_GUIDE.md).

AgentSpace runs a small team of AI agents on your machine. You type a task; a
supervisor agent breaks it into pieces, hands each piece to a worker agent, and
you watch the whole thing happen on a live graph. Every time an agent wants to
touch a file, run a command or fetch a web page, the app stops and asks you
first. Nothing leaves your computer except the calls to the AI model you chose.

**Version covered:** 0.1.0.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install and open the app](#2-install-and-open-the-app)
3. [Connect a model](#3-connect-a-model)
4. [Change settings](#4-change-settings)
5. [Your first run](#5-your-first-run)
6. [Approvals — the Allow / Deny dialog](#6-approvals--the-allow--deny-dialog)
7. [Agents](#7-agents)
8. [Budget and limits](#8-budget-and-limits)
9. [Running unattended](#9-running-unattended)
10. [Discord](#10-discord)
11. [Telegram](#11-telegram)
12. [Troubleshooting](#12-troubleshooting)
13. [Uninstall or start over](#13-uninstall-or-start-over)
14. [Reference](#14-reference)

---

## 1. What you need

- **Windows 10 or 11, 64-bit.** No administrator account needed.
- **One AI model provider.** Pick one:
  - an **Anthropic** API key, or
  - an **OpenAI** API key, or
  - **[Ollama](https://ollama.com)** installed on this machine, for a free local
    model with no key at all (slower and noticeably less capable — see §3).
- **Internet access** for the cloud providers. Ollama works offline.

### What this version can and cannot do from its own window

Be aware of this before you start. The app window has two screens — **Runs**
and **Agents** — and **no Settings screen yet**. Two setup steps therefore
happen outside the window:

| Step | Where you do it |
|---|---|
| Storing an API key or bot token | Windows **Credential Manager** (§3) |
| Changing any setting — provider, model, budget, limits, Discord/Telegram | The app's built-in **settings page in your browser**, at `http://127.0.0.1:8787/docs` (§4) |

Both are done once. Everything after that — starting runs, approving tool
calls, creating and editing agents, replaying old runs — is in the window.

---

## 2. Install and open the app

1. Download `AgentSpace_0.1.0_x64-setup.exe` from the project's
   [latest release](../../../releases/latest), or from the artefacts of any
   green [build run](../../../actions/workflows/build.yml).
2. Run it. **Windows will warn you once** — *"Windows protected your PC"*. This
   is because the installer is not code-signed, not because anything is wrong.
   Click **More info**, then **Run anyway**. It does not reappear.
3. The installer needs no administrator rights and installs for your user
   account only. If your PC lacks the WebView2 runtime (some Windows 10
   machines), the installer sets it up.
4. Open **AgentSpace** from the Start menu.

On every launch the window first shows *Connecting to the sidecar (attempt N)*
for a second or two. That is normal: the app starts a small local server
behind the scenes and waits for it. When it connects you will see two tabs,
**Runs** and **Agents**, and in the top-right corner the current provider and
model (`anthropic · claude-opus-5` on a fresh install) plus a budget meter.

### Where things live

| What | Where |
|---|---|
| The application | `%LOCALAPPDATA%\AgentSpace` |
| Your data — runs, agents, settings | `%LOCALAPPDATA%\dev.agentspace.desktop\agentspace.sqlite3` |
| **The agents' workspace** — the only folder agents can read or write | `%LOCALAPPDATA%\dev.agentspace.desktop\workspace` |

Paste either path into the File Explorer address bar to open it. Your data sits
outside the installation, so upgrading or uninstalling the app leaves it alone.

---

## 3. Connect a model

A fresh install is set to **Anthropic** and the model **claude-opus-5**, with no
key. If you start a run now it fails immediately with *"No API key for
anthropic"*. Choose one of the three options below.

### Option A — Anthropic or OpenAI (cloud, needs a key)

Your key goes in **Windows Credential Manager**, the same place Windows keeps
saved network passwords. AgentSpace reads it from there each time it starts and
never writes it to a file, a database or a log.

1. Get a key from [console.anthropic.com](https://console.anthropic.com) or
   [platform.openai.com](https://platform.openai.com).
2. Open **Credential Manager**: press the Windows key, type `Credential
   Manager`, open it, and choose the **Windows Credentials** tab.
3. Click **Add a generic credential** and fill in the three fields **exactly**:

   | Field | For Anthropic | For OpenAI |
   |---|---|---|
   | Internet or network address | `anthropic_api_key.dev.agentspace.desktop` | `openai_api_key.dev.agentspace.desktop` |
   | User name | `anthropic_api_key` | `openai_api_key` |
   | Password | your key | your key |

   The address is the part that matters — the app looks the credential up by
   that name and nothing else. Copy it rather than retyping it.

4. Click **OK**.
5. **Close and reopen AgentSpace.** Keys are read only at startup, so a key
   added while the app is open is not seen until the next launch.

If you chose OpenAI, you also need to switch the provider — see §4.

<details>
<summary>Alternative: add the credential from PowerShell</summary>

```powershell
cmdkey /generic:anthropic_api_key.dev.agentspace.desktop /user:anthropic_api_key /pass:<paste your key here>
```

This works identically, but the key is then saved in your PowerShell history
file. Prefer the Credential Manager window unless you know how to clear that
history.
</details>

### Option B — Ollama (local, free, no key)

1. Install [Ollama](https://ollama.com) and let it run in the background.
2. Download a model. The one this project has verified to complete runs is
   `qwen3:4b` (about 2.5 GB, needs roughly 5 GB of free GPU memory to run at
   a usable speed):

   ```powershell
   ollama pull qwen3:4b
   ```

3. Tell AgentSpace to use it — see §4, and send:

   ```json
   {"provider": "ollama", "model": "qwen3:4b"}
   ```

What to expect: local models are slower (a simple two-agent task takes a few
minutes rather than under one), they plan less well, and they may need a higher
step or agent limit than a cloud model to finish the same task. Runs cost
$0.00 and the budget meter will stay at zero. Not every model works: in
testing, `gemma4:e4b` never finished a run because it never decided the work
was done. Stick with `qwen3:4b` unless you want to experiment.

### Check it worked

Open `http://127.0.0.1:8787/docs` in your browser while the app is running,
find **POST /settings/verify**, click **Try it out**, then **Execute**. You want
to see `"ok": true`. If you see `"ok": false`, the `reason` tells you what is
missing — usually the key name, or a restart you have not done yet.

---

## 4. Change settings

Every setting lives behind one address that the running app serves to your
browser. **AgentSpace must be open** — the page disappears when you close the
app. The page loads its styling from the internet, so if you are fully offline
use the PowerShell alternative at the end of this section.

1. Open `http://127.0.0.1:8787/docs` in any browser.
2. Find **PATCH /settings** and click it, then click **Try it out**.
3. Replace the example body with **only the fields you want to change**, for
   example:

   ```json
   {"provider": "openai", "model": "gpt-5.4-mini"}
   ```

4. Click **Execute**. A `200` response shows the complete resulting settings.

Fields you leave out are untouched. A misspelled field is refused with a `422`
naming it, and **nothing changes** — so a typo cannot silently do the wrong
thing.

Two things about timing:

- A change applies to the **next run you start**. A run that is already going
  keeps the settings it started with.
- The provider and model shown in the window's header refresh when the next run
  finishes or when you reopen the app, so it may briefly show the old value.

### The settings

| Setting | Default | What it does |
|---|---|---|
| `provider` | `"anthropic"` | `"anthropic"`, `"openai"` or `"ollama"`. |
| `model` | `"claude-opus-5"` | Must be a priced model (see §14) or, for Ollama, any model you have pulled. |
| `monthly_cap_micros` | `20000000` ($20.00) | Monthly spending cap. **Dollars × 1,000,000.** $5 is `5000000`; $50 is `50000000`. |
| `ollama_base_url` | `"http://127.0.0.1:11434"` | Where Ollama listens. Leave alone unless you changed Ollama's port. |
| `auto_approve` | `[]` (ask about everything) | Risk levels that run without asking — see §9. |
| `max_steps_per_agent` | `20` | How many turns one agent gets before it must stop. |
| `max_agents_per_run` | `5` | How many agents one run may create. |
| `max_run_seconds` | `600` (10 min) | Hard time limit per run. Also how long an unanswered approval waits. |
| `discord_enabled` | `false` | See §10. |
| `telegram_enabled` | `false` | See §11. |
| `channel_identities` | `[]` (nobody) | Who may give the bots tasks — see §10. |
| `channel_approvals` | `"dashboard_only"` | Whether chat users may answer approvals — see §10. |

To see your current settings, use **GET /settings** on the same page. To see
which models are accepted, use **GET /settings/providers**.

<details>
<summary>Alternative: change settings from PowerShell</summary>

```powershell
Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:8787/settings `
  -ContentType 'application/json' `
  -Body '{"provider": "ollama", "model": "qwen3:4b"}'
```

Read them back with `Invoke-RestMethod http://127.0.0.1:8787/settings`.
</details>

---

## 5. Your first run

1. On the **Runs** tab, type a task into the **New run** box. Be concrete about
   the result you want. A good first task for a fresh install:

   > Write a short note about what SQLite is, in plain language, and save it to
   > sqlite.txt in the workspace.

2. Click **Start run**.

What you will see:

- **The graph** at the top: a supervisor node, and a worker node for each agent
  it brings in. Node colour shows whether the agent is thinking, calling a
  tool, waiting for your approval, or done. Arrows show work being handed
  between agents.
- **The event log** below it: every single thing that happens, in order — each
  model call, each tool call, each approval. Filter it by agent or event type.
- **The status line** above the graph: *live* while the run is going, *run
  finished — stream closed* when it ends.
- **An Allow / Deny dialog** whenever an agent wants to use a tool (next
  section). With the task above you will be asked at least once, when the
  writer wants to create `sqlite.txt`.

When the run finishes, a block appears headed **The supervisor's account of the
run**. Read that heading literally: **it is what the agent said it did, not a
record of what happened.** Beside it is a count of the tool calls that actually
ran. In testing, models have several times reported "saved to notes.txt" in
runs where no file was ever written — the count said *0 tool calls* and the
workspace folder was empty. If the result matters, check the workspace folder
(§2) or the `tool.called` entries in the log, not the summary.

### Replaying a run

Every past run is in the list on the left. Click one to see it exactly as it
appeared live, then drag the **Replay** slider to step through it event by
event. This is the same rendering as the live view — nothing is reconstructed
differently.

### Runs started from chat

If you connect Discord or Telegram (§10, §11), runs started there appear in the
same list and can be watched live here at the same time.

---

## 6. Approvals — the Allow / Deny dialog

Any time an agent wants to read or write a file, fetch a web page or run a
shell command, the app stops the agent and shows you a dialog:

- a **risk badge** — `low`, `medium` or `high`;
- **a plain-English sentence** describing exactly what will happen, for example
  *"create the file sqlite.txt (412 characters)"* — and it will say
  *overwrite* instead of *create* if the file already exists;
- which agent asked, and which tool;
- **Deny** and **Allow**.

Things worth knowing:

- **By default you are asked about everything**, including reads. That is
  deliberate: nothing touches your disk unless you said so. §9 explains how to
  relax it.
- **Denying stops that one call, not the run.** The agent is told no and
  carries on. The supervisor may then hand the same work to another agent,
  which asks you the same question again. This is normal, and the dialog shows
  the run's earlier decisions so you can see it happening.
- **An unanswered question expires when the run's time limit is reached**
  (10 minutes by default), and the run then fails. Walking away from a dialog
  is safe — the call never runs.
- **Some calls are refused before you are ever asked.** If an agent tries to
  reach a path outside the workspace folder — `..\..\Desktop\something.txt`,
  say — it is blocked outright and shows in the log as `tool.denied` with
  `[sandbox]`. You are only ever asked about calls that are safe to allow.
- **If you close the app with a question open**, that question is marked
  expired on the next start rather than shown again.

### The tools and their risk

| Tool | Risk | What it does |
|---|---|---|
| `read_file` | low | Read a file inside the workspace folder. |
| `list_dir` | low | List a folder inside the workspace folder. |
| `write_file` | medium | Create or overwrite a file inside the workspace folder. |
| `http_get` | medium | Fetch a public web page. Addresses on your own machine or network are refused. |
| `run_shell` | high | Run a command, in the workspace folder, with a time limit. |

`run_shell` deserves a sentence of its own. It runs as *you*, and although the
command starts in the workspace folder and has a hard timeout, **it is not
prevented from reaching the network or the rest of your disk** — a command
that says `curl` or `del C:\...` will do what it says. The only protection is
that it always stops to ask. Read those prompts carefully, and do not give the
tool to agents that do not need it.

---

## 7. Agents

The **Agents** tab lists every agent the supervisor may use. A fresh install
has three built-ins:

| Agent | Role | Tools |
|---|---|---|
| `researcher` | Gathers facts and figures, and reports them without embellishment | `read_file`, `list_dir` |
| `writer` | Turns findings into clear prose for the reader | `read_file`, `write_file` |
| `reviewer` | Checks work against the task it was meant to do, and says what is wrong | `read_file`, `list_dir` |

Built-ins can be edited but not deleted (the Delete button is there and will
tell you so).

### Creating or editing an agent

Click **New agent**, or click an existing one. The editor has:

- **Name** — must be unique; the supervisor refers to agents by name.
- **Role** — one line, shown in the list and to the supervisor when it decides
  who should do what.
- **System prompt** — the instructions the agent works from. Say what it is
  for and how it should behave. You do not need to explain the tools or how to
  finish; the app adds that.
- **Provider / Model** — leave on *inherit the workspace default* unless you
  want this one agent on a different model (a cheap one for summarising, say).
- **Max steps** — how many turns it gets. Blank means the workspace limit.
- **Tools** — tick what the agent may use. **The risk level is printed beside
  every checkbox**, so you can see what ticking `run_shell` means as you tick
  it. An agent with no tools can still think and report back.
- **Available to the supervisor** — untick to keep the agent defined but out
  of the roster.

Validation errors appear next to the field they are about — a duplicate name
on the name box, an over-limit step count on the steps box.

Two rules that are easy to miss:

- **Ticking a tool is permission from you to the agent to *ask*.** It does not
  skip the Allow / Deny dialog. An agent can only ever call tools on its own
  list; if its instructions tell it to use something else, the attempt is
  refused and logged.
- **Editing an agent does not change a run that is already going.** Runs take
  a snapshot of the agents when they start.

---

## 8. Budget and limits

### Spending

The meter in the top-right shows this month's spend against the cap, which is
**$20.00 by default**. The app knows each model's list price, adds up every
call, and:

- logs a warning when you pass 80% of the cap;
- **refuses to make a call that would go over the cap**, failing the run with
  *"This call would exceed the monthly budget. Spent $X of $Y this month…"*
  before any money is spent.

Raise or lower the cap with `monthly_cap_micros` (§4). The count resets at the
start of each calendar month. This is the app's own accounting from list
prices, so treat your provider's dashboard as the final word on what you were
billed.

If the header shows **"unpriced — runs will be refused"**, the model name you
set is not one the app knows the price of. Pick one from §14, or switch to
Ollama, whose models are always priced at zero.

### Limits

| When | What happens |
|---|---|
| An agent uses all its steps (`max_steps_per_agent`) | It stops and reports back with what it has; the run continues. If it was the *supervisor* that ran out, the run fails and says so. |
| The supervisor asks for one agent too many (`max_agents_per_run`) | That request is refused and the supervisor is told; the run continues with the agents it has. |
| The run hits `max_run_seconds` | The run fails, and any approval still waiting expires. |

Local models generally need more steps and agents than cloud models for the
same task. If Ollama runs keep ending with *"supervisor stopped after N steps
with no result"*, raising `max_steps_per_agent` is the first thing to try.

---

## 9. Running unattended

By default every tool call waits for you. To let a run proceed while you are
away, pre-approve risk levels with `auto_approve` (§4):

```json
{"auto_approve": ["low"]}
```

lets reads and folder listings inside the workspace proceed without asking,
while writes, web fetches and shell commands still stop. Sensible combinations,
in increasing order of trust:

- `[]` — ask about everything (the default);
- `["low"]` — reads are automatic;
- `["low", "medium"]` — file writes inside the workspace and web fetches are
  automatic too. Only do this for runs whose worst case is losing files in the
  workspace folder.

**Do not add `"high"`.** That lets any agent run any shell command as you with
nobody watching.

Auto-approved calls are still written to the run's log and marked *by policy*
in the dialog's history, so afterwards you can see exactly what ran without
asking. A run that finishes unattended is still just a run — replay it (§5) to
check what happened. An individual agent can be given a narrower
`auto_approve` than the workspace, never a wider one.

---

## 10. Discord

You can give the agents tasks from a Discord server and watch the reply update
in place as the run progresses. Only Discord accounts you list may do so.

### 10.1 Create the bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications),
   click **New Application**, and name it.
2. Open the **Bot** page, click **Reset Token**, and copy the token. You will
   not be shown it again.
3. On the same page, **leave all three Privileged Gateway Intents off.**
   AgentSpace does not use them — it is designed so that Discord never sends it
   the contents of ordinary channel messages at all.
4. Open **OAuth2 → URL Generator**. Tick the scopes **`bot`** and
   **`applications.commands`**, then the bot permission **Send Messages**.
   Open the generated URL and add the bot to your server.

### 10.2 Store the token

In Credential Manager (§3, Option A), add a generic credential:

| Field | Value |
|---|---|
| Internet or network address | `discord_bot_token.dev.agentspace.desktop` |
| User name | `discord_bot_token` |
| Password | the token |

Then **close and reopen AgentSpace**.

### 10.3 Allow yourself

A bot in a server can be addressed by anyone in it, so the app refuses everyone
until you say otherwise. You need your Discord **user ID** (a long number, not
your username):

- In Discord: **User Settings → Advanced → Developer Mode** on. Then
  right-click your name anywhere and choose **Copy User ID**.
- Or skip that: enable the bot (next step), type `/agent hello` once, get the
  refusal, then look at **GET /channels** on the settings page — the `refused`
  list shows your name and ID.

Now, on the settings page (§4), send:

```json
{
  "discord_enabled": true,
  "channel_identities": [
    {"channel": "discord", "external_user_id": "123456789012345678", "identity": "me"}
  ]
}
```

`identity` is just a label for the log — your name is fine. Add one entry per
person you trust. Sending `"channel_identities": []` revokes everyone.

Unlike other settings, channel changes take effect **immediately** — no
restart. Check **GET /channels**: `running: true` means the bot is connected.
If it is not, `last_error` says why.

### 10.4 Use it

In any channel the bot can see, type:

```
/agent Summarise the three files in the workspace into one paragraph
```

The bot posts one message and keeps editing it as the run progresses — agents
appearing, tools being called, the final result. The same run also shows up
live on the **Runs** tab.

**Approvals from Discord.** When an agent needs permission, the bot's status
message shows a **⏸ Waiting for approval** line with the request. By default
(`channel_approvals: "dashboard_only"`) that is all it shows: the run waits,
and the answer has to be given on the desktop, at the machine the file or
command would run on. To be able to answer from Discord as well, set:

```json
{"channel_approvals": "originator"}
```

The bot then also posts each request as its own message with **Allow** and
**Deny** buttons. Only the person who started the run can press them. An
approval that was already answered on the desktop shows *Already answered
elsewhere*.

`/agent` is the trigger that has been tested end to end. The code also
recognises an @mention of the bot, but that path has not been verified against
a real server; use the slash command.

---

## 11. Telegram

The Telegram setup is the same shape as Discord's. **Note:** in this version
the Telegram connection has been verified as far as authenticating with
Telegram; a full run driven from a Telegram chat has not yet been observed.
Expect it to work, and report what you see if it does not.

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and
   copy the token. Leave the bot's **privacy mode on** (the default) — it is
   what keeps the bot from seeing ordinary group chatter.
2. In Credential Manager, add a generic credential with address
   `telegram_bot_token.dev.agentspace.desktop`, user name `telegram_bot_token`,
   and the token as the password. **Close and reopen AgentSpace.**
3. Find your Telegram user ID (a number). Message **@userinfobot**, or send
   `/agent hello` to your bot and read the `refused` list from **GET
   /channels**.
4. On the settings page, send:

   ```json
   {
     "telegram_enabled": true,
     "channel_identities": [
       {"channel": "telegram", "external_user_id": "123456789", "identity": "me"}
     ]
   }
   ```

   If you already have Discord entries, include them in the list too — the
   list you send replaces the old one.

5. Send `/agent <your task>` to the bot. It replies with one message that it
   keeps editing. Approvals follow the same `channel_approvals` rule as
   Discord: shown as a *Waiting for approval* line by default, answerable
   with **Allow / Deny** buttons only if you set `"originator"`.

---

## 12. Troubleshooting

**The window stays on "Connecting to the sidecar" and then says "Sidecar
unreachable".**
The local server did not start, or something else on your PC is already
using port 8787. Close the app, open Task Manager and end any
`agentspace-sidecar` process you find, then reopen. If it persists, another
program is holding the port — the app cannot use a different one.

**Every run fails at once with "No API key for anthropic" (or openai).**
The key is not in Credential Manager under the exact address in §3, or you
have not restarted the app since adding it. Check with **GET /settings** on
the settings page: `configured_secrets` lists the names of the keys the app
received at startup. If your key is not there, fix the credential and
restart.

**The header says "unpriced — runs will be refused".**
The `model` you set is not in the price table. Use **GET /settings/providers**
to see the accepted names, or see §14.

**A run failed with "This call would exceed the monthly budget".**
You are at the cap. Raise `monthly_cap_micros` (§4) or wait for the new
month.

**A run "completed" but nothing is in the workspace folder.**
Read §5 — the summary is the agent's claim. Look at the tool-call count next to
it and at `tool.called` in the log. If there are no `write_file` calls, no file
was written, whatever the summary says. This is a model behaviour, not a
saving problem.

**The same approval question keeps coming back.**
You denied it, the agent gave up, and the supervisor gave the work to a fresh
agent, which asked again (§6). Deny again, or let the run hit its time limit.
The run will not loop forever: the agent and step limits end it.

**Ollama runs are slow or never finish.**
Check `ollama list` shows the model you set, and that Ollama is running. Use
`qwen3:4b`. Raise `max_steps_per_agent` and `max_agents_per_run` a little.
Some models never call the work done and cannot complete a run at all.

**The Discord bot is online but `/agent` does nothing.**
Look at **GET /channels**. If `running` is `false`, `last_error` explains —
*Improper token* means the credential is wrong. If `running` is `true` and the
command does not appear when you type `/`, the bot was added without the
`applications.commands` scope: generate a new invite URL (§10.1) with both
scopes and open it. Commands are registered per server the moment the bot
joins.

**The bot replies "This agent workspace is not configured to accept requests
from this Discord account."**
Your account is not in `channel_identities`. **GET /channels** shows the
refused account and its ID; add it (§10.3).

**An approval dialog is about a run from yesterday.**
Approvals left open when the app closed are marked expired at the next start.
If you see one, it is read-only history on a finished run.

**Where is the log file?**
There is no log file in this version. The event log inside each run — visible
in the window, and replayable — is the record of what happened.

---

## 13. Uninstall or start over

- **Uninstall:** Windows **Settings → Apps → Installed apps → AgentSpace →
  Uninstall**. Your data folder is left in place.
- **Wipe all data** (runs, agents, settings): close the app and delete
  `%LOCALAPPDATA%\dev.agentspace.desktop`. The next launch starts fresh with
  the three built-in agents.
- **Remove your keys:** open Credential Manager and remove the entries ending
  in `.dev.agentspace.desktop`.

---

## 14. Reference

### Priced models

These are the `model` values the app accepts for each cloud provider. Any
other name is refused as unpriced. (Prices are list prices recorded in the
app; your provider's bill is authoritative.)

| Provider | Models |
|---|---|
| `anthropic` | `claude-fable-5-1`, `claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5` |
| `openai` | `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.2`, `gpt-5.1`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, `gpt-4o`, `gpt-4o-mini`, `o3`, `o3-mini` |
| `ollama` | Any model shown by `ollama list`. All are priced at $0. |

### Credential Manager entries

All are *generic* credentials. The **address** is what the app looks up.

| Address | User name | Holds |
|---|---|---|
| `anthropic_api_key.dev.agentspace.desktop` | `anthropic_api_key` | Anthropic API key |
| `openai_api_key.dev.agentspace.desktop` | `openai_api_key` | OpenAI API key |
| `discord_bot_token.dev.agentspace.desktop` | `discord_bot_token` | Discord bot token |
| `telegram_bot_token.dev.agentspace.desktop` | `telegram_bot_token` | Telegram bot token |

Changes to any of these need an app restart.

### The settings page

`http://127.0.0.1:8787/docs`, available while the app is running. The
addresses you will actually use:

| Address | Use |
|---|---|
| `GET /settings` | Current settings, which keys were received, whether the model is priced |
| `PATCH /settings` | Change settings |
| `GET /settings/providers` | Accepted providers and model names |
| `POST /settings/verify` | Check the current provider can be used |
| `GET /budget` | This month's spend and cap |
| `GET /channels` | Whether Discord / Telegram are connected, and who was refused |
| `GET /tools` | The tools and their risk levels |

Everything here is only reachable from this computer. The app never listens on
any other address.
