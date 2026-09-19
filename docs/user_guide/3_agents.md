# Agents

[Guide contents](README.md) · [Next: Integrations](4_integrations.md)

## The roster belongs to a space

Choose a space, then open **Agents** in the left rail. Its enabled definitions
are the workers the supervisor can delegate to. The supervisor itself is
part of the orchestrator and is not a row you edit here.

A fresh install's default space, **Main**, holds a ten-agent investment
research pipeline. Every one of them is a built-in: editable, disableable
and movable, but not deletable. They pass work to each other through files
in the space folder (`config/`, `raw/`, `knowledge/`, `portfolio/`,
`theses/`, `risk/`, `decisions/`, `scores/`), so read each system prompt
before the first run and create `config/watchlist.json`, `config/sources.json`
and `config/limits.json` for the collectors to read.

| Agent | Model | What it does | Tools |
|---|---|---|---|
| `news-scanner` | Haiku | Collects news and social discussion about watchlist tickers into `raw/news-*.json`. No analysis. | `http_get`, `read_file`, `write_file` |
| `research-librarian` | Sonnet | Writes durable concept and company notes under `knowledge/`, sourced to filings. | `read_file`, `list_dir`, `search_knowledge`, `write_file`, `propose_memory` |
| `market-movers` | Haiku | Collects prices, volume and gainers/losers into `raw/movers-*.json`. Numbers only. | `http_get`, `read_file`, `write_file` |
| `event-calendar` | Haiku | Builds a 30-day calendar of earnings, macro releases, corporate events and personnel changes. | `http_get`, `read_file`, `write_file` |
| `portfolio-review` | Haiku | Describes the book from `portfolio/computed.json`. Never recommends. | `read_file`, `list_dir`, `write_file` |
| `bull-architect` | Sonnet | Argues the strongest evidence-based case that named tickers rise, as scored predictions in `theses/bull-*.jsonl`. | `read_file`, `list_dir`, `search_knowledge`, `write_file` |
| `bear-architect` | Sonnet | The mirror: the strongest case that they fall, in `theses/bear-*.jsonl`. | same |
| `risk-manager` | Sonnet | Holds a veto: restates the script's hard-rule results verbatim and adds judgement. | `read_file`, `list_dir`, `write_file` |
| `decision` | Opus | Arbitrates bull, bear and risk into a dated recommendation table for you to approve. Executes nothing. | `read_file`, `list_dir`, `write_file` |
| `review-analyst` | Sonnet | Scores predictions against outcomes and diagnoses misses without hindsight. | `read_file`, `list_dir`, `write_file`, `propose_memory` |

Each definition names its provider and model (Anthropic's Haiku, Sonnet or
Opus), so the pipeline's cost shape does not depend on the app-wide default:
what runs often is cheap, reasoning is mid-tier, and Opus runs once per
decision. Change a model in the agent's editor if you use another provider.
The prompts treat fetched pages and files under `raw/` as untrusted text, and
no built-in can run a shell command. Their **Calls this agent may make
without asking** lists narrow the app-wide policy (the collectors to low and
medium risk, the analysts to low) and never widen it, so nothing runs
unattended until you tick a level in Settings.

Before the first collector run, create the configuration the prompts read,
under **Knowledge → Data files**: the empty list offers `config/watchlist.json`,
`config/sources.json` and `config/limits.json` as templates to edit and save,
and JSON is checked before it is written. (The same files can be put in the
space folder by hand, under a `config` folder.) `config/watchlist.json` lists the tickers:
any JSON the prompt can read works, for example a `watchlist` array of
objects with `ticker`, `company_name` and `aliases`, since the prompt says to
take tickers only from this file. `config/sources.json` names the feeds and
their URL templates, for example a Google News RSS template with `{ticker}`
in it for `news-scanner`, a Stooq template for `market-movers`, and any keyed
endpoint with its key in the query string for `event-calendar`; a note field
per source is fine, the agent reads the file as text. The agents read these
with `read_file`, so the files must be inside the space folder, not on the
web. `config/limits.json` holds the hard risk rules `portfolio-review` and
`risk-manager` restate.

Two things the prompts assume that AgentSpace does not provide: scripts
(`scripts/compute_movers.py`, `compute_portfolio.py`, `check_limits.py`,
`score_predictions.py`, `fetch_keyed.py`) that do the arithmetic and the
header-requiring fetches, and a `portfolio/positions.csv` you export by
hand. Arithmetic is deliberately never done by a model. Until those exist,
an agent that finds its input missing is told to say so and stop.

A new space is seeded with three **starter roles** instead: `researcher`
(`read_file`, `list_dir`, `search_knowledge`, `propose_memory`), `writer`
(`read_file`, `write_file`, `search_knowledge`, `propose_memory`) and
`reviewer` (as the researcher). These copies are editable and deletable. An
empty space can add them with **Start from the starter roles** on Home, and
so can the default space, or you can define your own agents.

## Create or edit an agent

Click **New agent**, or select an existing agent in the list. Fill in its
fields and save the definition.

| Field | Meaning |
|---|---|
| **Name** | Unique within this space. Use lowercase letters, digits, `-` or `_`, starting with a letter, up to 40 characters. |
| **Role** | A one-line description the supervisor uses when choosing a worker. |
| **System prompt** | Instructions for the worker's task and behavior. The app supplies the coordination instructions. |
| **Provider / Model** | Inherit the space's provider and model, or choose a model for this agent. |
| **Max steps** | A saved ceiling on this agent's turns. Blank selects the lower of 20 and the current app-wide step limit; it is not a value that grows automatically when settings change. |
| **Tools this agent may call** | The tools the agent is permitted to request. An agent with no file, shell or network tools can still reason and report back. |
| **Calls this agent may make without asking** | Optional restriction on automatic approvals. Nothing ticked inherits the space policy; selected levels are intersected with that policy. |
| **Available to the supervisor** | Disable to keep the definition but remove it from future runs' rosters. |

Errors appear beside the relevant field. An explicit **Max steps** must fit
within the app-wide limit when saved; at run time it is also clamped to the
space's effective step limit. Changing only a space's limit does not raise
an agent's saved ceiling.

Allowing a tool lets an agent request it; the approval gate still decides
whether the call may execute. An agent cannot add tools to its own allowlist.
See [Approvals](2_running_tasks.md#approvals) for each tool's effects.

An active run keeps the roster and definitions it started with. Editing,
disabling, moving or deleting a definition changes future runs, while old
runs retain the definitions recorded in their event logs.

## Move, copy or delete

With an existing agent open, **Move to** transfers its definition to another
active space. **Copy to** creates an independent definition there. Choose the
destination in the dropdown to perform the action. A copy receives a unique
name if that name is already used in the destination and is deletable even
when its source is a built-in.

Use the list's **Delete** control and confirmation to remove a definition.
Attempting to delete one of the default space's built-ins reports that it is
protected; disable it instead if you do not want the supervisor using it.

## Custom tools

The app lets you combine the five registered tools into an agent's allowlist.
It has no UI for installing or writing another tool. Adding a tool requires
a code change; see the
[developer checklist](../developer_guide/5_checklists.md).
