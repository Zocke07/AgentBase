# Agents

[Guide contents](README.md) · [Next: Integrations](4_integrations.md)

## The roster belongs to a space

Choose a space and open **Agents**. Its enabled definitions are workers the
supervisor can delegate to; the orchestrator's supervisor is not editable here.

### The investment roster

Fresh-install **Main** contains a ten-agent investment-research pipeline and
five schedules that run it once you turn them on (see
[Automations](2_running_tasks.md#automations-work-on-its-own)). Built-ins are
editable, disableable, and movable but not deletable. They exchange ordinary
files in `config/`, `raw/`, `knowledge/`, `portfolio/`, `theses/`, `risk/`,
`decisions/`, and `scores/`.

**Turn on the daily pipeline** creates nine missing starter files without
replacing an existing file: an illustrative six-company watchlist, keyless
sources, risk limits, a zero-cash positions template, four stable chart
definitions, and the investment dashboard. The list is a research example,
not a portfolio or a recommendation to buy those shares.

| Agent | Shipped model | What it does | Distinctive tools |
|---|---|---|---|
| `news-scanner` | Claude Haiku 4.5 | Collects bounded news entries into `raw/news-*.json`. No analysis. | `read_feed` |
| `research-librarian` | Claude Sonnet 5.5 | Maintains concept notes from local knowledge and company notes when you supplied filing text. | `search_knowledge`, `propose_memory` |
| `market-movers` | Claude Haiku 4.5 | Collects and computes watchlist prices and movers into stable and dated files. | `read_prices` |
| `event-calendar` | Claude Haiku 4.5 | Builds a 30-day calendar from the configured Treasury source only. | `http_get` |
| `portfolio-review` | Claude Haiku 4.5 | Computes and describes the current book. Never recommends. | `compute_portfolio` |
| `bull-architect` | Claude Sonnet 5.5 | Writes the strongest evidence-based rise cases as scored predictions. | file and knowledge tools |
| `bear-architect` | Claude Sonnet 5.5 | Writes the strongest evidence-based fall cases as scored predictions. | file and knowledge tools |
| `risk-manager` | Claude Sonnet 5.5 | Restates deterministic rule results, keeps its veto, then adds qualitative risks. | `check_limits` |
| `decision` | Claude Opus 5.5 | Arbitrates the two cases and risk checks into a recommendation for you. | file tools |
| `review-analyst` | Claude Sonnet 5.5 | Scores predictions and diagnoses misses without hindsight. | `score_predictions`, `propose_memory` |

Definitions use fast, balanced, or strong models independently of the space's
model. On OpenAI, collectors and portfolio review move to GPT-6 Luna, balanced
agents move to GPT-6 Sol, and `decision` keeps its strong intended level even
though GPT-6 Sol covers both levels. On a ChatGPT plan without GPT-6 Sol,
balanced shipped agents move to GPT-5.6 Terra and `decision` moves to GPT-5.6
Sol automatically. A model you chose yourself maps by its catalog level.

Prompts treat fetched pages and `raw/` files as untrusted; no built-in uses
shell. The four computation tools are medium risk. Under the default
**Autonomous** policy, low- and medium-risk calls can run unattended when their
host and tool are allowed. An upgraded install keeps its saved approval and
host settings.

An install created before the deterministic tools may also have older
collector prompts if an agent's model was changed before the pipeline update.
Migration 022 repairs an agent only when its prompt and tool list still match
that exact older shipped definition. It keeps your chosen model and leaves
genuinely edited instructions alone. Restart the app after updating so the
new scheduler and migration are loaded.

Before the first collector run, review these under **Knowledge → Agent files**:

- `config/watchlist.json`: the starter follows AAPL, JPM, JNJ, XOM, PG and CAT,
  one from each of six sectors. Replace any you do not want followed, or add
  others up to 50 entries. Each needs a `ticker` and non-empty `sector`;
  `company_name` and `aliases` help news matching.
- `portfolio/positions.csv`: keep the header
  `ticker,shares,cost_per_share,opened,sector,currency`. Enter current holdings
  plus a `CASH` row, use one ISO currency throughout, and maintain the snapshot
  yourself.

The other starter inputs are ready to edit: `config/sources.json` names Google
News, Yahoo's unofficial keyless chart endpoint, and the US Treasury auctions
API; `config/limits.json` holds the position, sector, and daily-loss limits.
Its 10%, 30%, and 3% values are software defaults, not a personal risk policy.
No data-source key is stored in a file or exposed to a model.

The news scanner reads the feed URL templates in `sources.json`, and the event
collector reads its event URLs. `read_prices` uses a fixed, checked Yahoo URL;
the Yahoo entry in `sources.json` describes that source but cannot switch the
price tool to another host. The three limit keys are enforced by the portfolio
and risk tools. Extra keys in either file do not add data or rules.

More JSON does not by itself create richer research. Add data only where the
pipeline has a defined consumer:

- Replace the illustrative entries in `watchlist.json` with the real companies
  you want followed.
  `company_name` and `aliases` improve news matching; `sector` is required for
  deterministic risk grouping. Do not add a sample ticker you would not want
  discussed in a recommendation.
- Keep `sources.json` to source formats the shipped collectors understand.
  Adding an arbitrary URL gives no parser for it and may only create a failed
  fetch or an approval question.
- Tune the three numbers in `limits.json` to the person's actual policy. Extra
  keys are ignored until a deterministic rule is implemented for them.
- Add current holdings and cash to `positions.csv`. This usually enriches the
  portfolio and risk output more than adding descriptive configuration.

#### The stage sequence

1. **Morning collection** reads the watchlist and calls `read_prices` first.
   No new market session stops the chain without writing a false daily result.
   A new session is followed by news, Treasury auctions, and
   `compute_portfolio`.
2. **Theses and risk** runs only when that session's movers file exists. Bull
   and bear write their predictions, then `check_limits` produces the hard
   rule results before the risk manager adds judgement.
3. **Daily decision** writes a dated recommendation for human review. It never
   trades, submits an order, or connects to a broker.
4. **Weekly knowledge** updates concept notes from the space's own knowledge.
   It updates a company note only when you placed filing text in
   `raw/filings/{TICKER}/`; it does not fetch a filing.
5. **Weekly review** calls `score_predictions` for the current UTC month. The
   tool resolves 1-, 3-, 5-, and 7-session predictions once, appends the
   ledger once, and refreshes stable accuracy and calibration files before the
   reviewer proposes durable methodology lessons.

Models do not calculate portfolio figures, limits, returns, hit rates, Brier
scores, or calibration. They may state only figures emitted by the
deterministic tools. Malformed or missing input is reported rather than
guessed. The decision remains a recommendation for you to review.

For the shipped daily chain, a run marked **completed** is not enough to start
the next stage. Morning collection must have verified new-session price rows
with no failed ticker and a successful portfolio calculation. Theses and risk
must have successful hard-rule checks and the dated risk review file. Tool or
model errors stop the chain, so a rate-limited Yahoo request cannot turn into
empty theses or a decision presented as if the inputs were complete. Check
the run's error details and tool results before trusting its summary.

The shipped keyless scope does not include Reddit or other social sources,
SEC fetching, keyed APIs, market-wide gainers and losers, earnings dates, FOMC
or BLS calendars, a Taiwan-specific chain, per-schedule time zones, or a full
market-holiday calendar. Yahoo's endpoint is unofficial. You may supply filing
text and a calendar as local files.

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
