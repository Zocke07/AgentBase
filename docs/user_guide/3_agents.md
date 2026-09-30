# Agents

[Guide contents](README.md) · [Next: Integrations](4_integrations.md)

## The roster belongs to a space

Choose a space and open **Agents**. Its enabled definitions are workers the
supervisor can delegate to; the orchestrator's supervisor is not editable here.

### The investment roster

Fresh-install **Main** contains a ten-agent investment-research pipeline, and
five schedules that run it on its own once you turn them on (see
[Automations](2_running_tasks.md#automations-work-on-its-own)). Built-ins are
editable, disableable, and movable but not deletable. They exchange files in
`config/`, `raw/`, `knowledge/`, `portfolio/`, `theses/`, `risk/`,
`decisions/`, and `scores/`; **Turn on the daily pipeline** creates any of
`config/watchlist.json`, `config/sources.json`, and `config/limits.json` that
is missing from its template before the first collector run.

| Agent | Model | What it does | Tools |
|---|---|---|---|
| `news-scanner` | Haiku | Collects news about watchlist tickers into `raw/news-*.json`. No analysis. | `read_feed`, `read_file`, `write_file` |
| `research-librarian` | Sonnet | Writes durable concept and company notes under `knowledge/`, sourced to filings. | `read_file`, `list_dir`, `search_knowledge`, `write_file`, `propose_memory` |
| `market-movers` | Haiku | Collects prices, volume and gainers/losers into `raw/movers-*.json`. Numbers only. | `http_get`, `read_file`, `write_file` |
| `event-calendar` | Haiku | Builds a 30-day calendar of earnings, macro releases, corporate events and personnel changes. | `http_get`, `read_file`, `write_file` |
| `portfolio-review` | Haiku | Describes the book from `portfolio/computed.json`. Never recommends. | `read_file`, `list_dir`, `write_file` |
| `bull-architect` | Sonnet | Argues the strongest evidence-based case that named tickers rise, as scored predictions in `theses/bull-*.jsonl`. | `read_file`, `list_dir`, `search_knowledge`, `write_file` |
| `bear-architect` | Sonnet | The mirror: the strongest case that they fall, in `theses/bear-*.jsonl`. | same |
| `risk-manager` | Sonnet | Holds a veto: restates the script's hard-rule results verbatim and adds judgement. | `read_file`, `list_dir`, `write_file` |
| `decision` | Opus | Arbitrates bull, bear and risk into a dated recommendation table for you to approve. Executes nothing. | `read_file`, `list_dir`, `write_file` |
| `review-analyst` | Sonnet | Scores predictions against outcomes and diagnoses misses without hindsight. | `read_file`, `list_dir`, `write_file`, `propose_memory` |

Definitions specify Haiku, Sonnet, or Opus, so the pipeline's cost mix does
not follow the space's model: frequent work is cheap, reasoning mid-tier, and
Opus runs once per decision. The decision agent moved from Opus 5 to Opus 5.5
in an update unless you had edited it. To run the roster on OpenAI, switch the
space's provider in Space settings and keep its agents ticked: collectors move
to GPT-6 Luna, analysts and the decision agent to GPT-6 Sol. On a ChatGPT
plan without GPT-6 Sol, Space settings then offers GPT-5.6 Terra for those
agents; to keep the decision agent at the top level, choose GPT-5.6 Sol in its
editor.
Prompts treat fetched pages and `raw/` files as untrusted; no built-in uses
shell. Each built-in's **Calls this agent may make without asking** names low
and medium, so under the default **Autonomous** policy every stage reads,
writes its own output and fetches from the listed sites by itself. It narrows,
never widens, the app policy: on an install that still asks about everything,
nothing runs unattended until Settings enables a level. (An update moved the
analysts, risk manager, decision and review agents from low to low and medium,
unless you had changed their levels or tools.)

Before the first collector run, create its configuration under **Knowledge →
Data files**. An empty list offers JSON-validated templates for
`config/watchlist.json`, `config/sources.json`, and `config/limits.json`; you
can instead create them under the space's `config/` folder. `watchlist.json`
can be any readable JSON, such as a `watchlist` array of `ticker`,
`company_name`, and `aliases` objects; prompts take tickers only from it.
`sources.json` defines feeds and URL templates: for example, Google News RSS
with `{ticker}` for `news-scanner`, Stooq for `market-movers`, or a keyed URL
for `event-calendar`; sources may include a note. Because agents use
`read_file`, these files must be inside the space, not on the web.
`news-scanner` expands each template and calls `read_feed`, which parses RSS/
Atom locally, returns at most 20 complete entries, normalizes dates/domains,
and supplies deterministic IDs and title-deduplication keys. `limits.json`
contains the hard rules `portfolio-review` and `risk-manager` restate.

#### How the pipeline is meant to work

- **Collectors only collect.** They write what they fetch into `raw/` in
  fixed shapes. They treat everything they fetch as untrusted: an instruction
  inside a news item is ignored and noted, never followed.
- **Models never do the arithmetic.** Prices, P&L, limit checks and accuracy
  come from computed files; an agent only reports figures those files hold.
- **Predictions are scored, not self-reported.** The bull and bear agents give
  each call a confidence before the outcome is known. Calls are then scored
  against what the price did over 1, 3, 5 or 7 trading days, and the review
  agent reads the score. One- and three-day calls from news are close to a
  coin flip; a clearly measured poor result is a useful result.
- **Everything ends with you.** The decision is a recommendation for you to
  review. Nothing is bought or sold, and no broker is connected: you export
  your positions yourself, as `portfolio/positions.csv`.

#### What it needs, and what it cannot do yet

You supply `config/watchlist.json`, `config/sources.json`,
`config/limits.json` and `portfolio/positions.csv`.

As of 2026-09-30 the pipeline does not do the whole job on its own:

- **The arithmetic steps are not in the app.** The prompts expect five
  scripts: `compute_movers.py`, `compute_portfolio.py`, `check_limits.py`,
  `score_predictions.py` and `fetch_keyed.py`. The app neither ships nor runs
  them. So:
  - `portfolio-review` finds no `portfolio/computed.json`;
  - `risk-manager` has no hard-rule results to restate;
  - `review-analyst` has no scored predictions.
  Each reports the missing input and stops.
- **Prices do not arrive.** Stooq, the price source in the
  `config/sources.json` template, now answers programs with a browser check
  instead of data, so `market-movers` collects no prices.
- **Most official calendars cannot be read.** Some pages are too large for an
  agent to see whole, and some sites refuse programs. A site that is not on
  your allowed list asks first. In a scheduled run nobody answers, and the
  question expires after two minutes.
- **Some sources are not collected.** Reddit, SEC filings, market-wide gainers
  and losers, and earnings dates.

Computing these figures in the app is the next planned work.

**Timing from Asia.** The morning collection runs on weekdays at 07:00 your
time, and the US market closes at 04:00 (summer) or 05:00 (winter) Taipei
time. A weekday 07:00 run therefore sees the previous US session, so Monday's
run sees Friday's. To match the US week, set that schedule to Tuesday through
Saturday in Automations.

This is a research and organising tool, not investment advice.

New spaces instead get three editable, deletable **starter roles**:
`researcher` (`read_file`, `list_dir`, `search_knowledge`, `propose_memory`),
`writer` (`read_file`, `write_file`, `search_knowledge`, `propose_memory`),
and `reviewer` (researcher tools). Add them from Home with **Start from the
starter roles**, including in the default space, or define your own.

## Create or edit an agent

Click **New agent** or select an existing agent, then save its fields.

| Field | Meaning |
|---|---|
| **Name** | Unique within this space. Use lowercase letters, digits, `-` or `_`, starting with a letter, up to 40 characters. |
| **Role** | A one-line description the supervisor uses when choosing a worker. |
| **System prompt** | Worker task/behavior instructions; the app supplies coordination. |
| **Provider / Model** | Inherit the space's provider and model, or choose a model for this agent. The list shows current models first, each with its level and price per million tokens. When a space moves to another provider, Space settings offers to move agents that name the old one's models. |
| **Max steps** | Saved ceiling on agent turns. Blank selects the lower of 20 and the current app-wide limit; it does not grow automatically with settings. |
| **Tools this agent may call** | Tools it may request. Without file, shell, or network tools, it can still reason and report. |
| **Calls this agent may make without asking** | Optional automatic-approval restriction. Nothing inherits space policy; selected levels intersect it. |
| **Available to the supervisor** | Disable to keep the definition but remove it from future runs' rosters. |

Errors appear beside their field. Explicit **Max steps** must fit the app-wide
limit on save and is clamped to the effective space limit at run time. Changing
only a space limit does not raise the saved agent ceiling.

Allowing a tool permits requests, not execution; the approval gate still
decides. Agents cannot extend their allowlists. See
[Approvals](2_running_tasks.md#approvals) for effects.

Active runs keep their starting roster/definitions. Editing, disabling, moving,
or deleting changes future runs; historical logs retain their definitions.

## Move, copy or delete

For an open agent, **Move to** transfers it to another active space; **Copy to**
creates an independent definition there. Select the destination. Copies get a
unique destination name and remain deletable even when sourced from a built-in.

Use **Delete** and confirm to remove a definition. Default-space built-ins are
protected; disable them to remove them from supervisor use.

## Custom tools

The app combines registered tools into agent allowlists; it cannot install or
write tools. Adding one requires code; see the
[developer checklist](../developer_guide/5_checklists.md).
