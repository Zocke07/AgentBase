# Agents

[Guide contents](README.md) · [Next: Integrations](4_integrations.md)

## The roster belongs to a space

Choose a space and open **Agents**. Its enabled definitions are workers the
supervisor can delegate to; the orchestrator's supervisor is not editable here.

### The investment roster

Fresh-install **Main** contains a ten-agent investment-research pipeline, the
`market-explainer` for market alerts, and five schedules that run the pipeline
once you turn them on (see
[Automations](2_running_tasks.md#automations-work-on-its-own)). Built-ins are
editable, disableable, and movable but not deletable. They exchange ordinary
files in `config/`, `raw/`, `knowledge/`, `portfolio/`, `theses/`, `risk/`,
`decisions/`, `predictions/`, and `scores/`.

**Turn on the daily pipeline** creates nine missing starter files without
replacing an existing file: the sample watchlist and positions, public data
sources, risk limits, four stable chart definitions, and
the investment dashboard. The sample holds one share each of MU, ORCL, CRWV,
MSFT, NOW and AVGO and $2,500 USD cash. It is a research example; replace it
with your real records before relying on the results. Unknown purchase costs
and dates stay blank.

| Agent | Shipped model | What it does | Distinctive tools |
|---|---|---|---|
| `news-scanner` | Claude Haiku 5.5 | Discovers Yahoo movers and headlines, keeps holdings in the universe, and collects annual or quarterly financial facts and available SEC excerpts. No analysis. | `read_market`, `read_company_reports` |
| `research-librarian` | Claude Sonnet 5.5 | Interprets saved financial facts and filing excerpts to maintain company and concept notes. | `search_knowledge`, `propose_memory` |
| `market-movers` | Claude Haiku 5.5 | Collects complete prices for the research universe and updates actual prices in existing forecast workbooks. | `read_prices`, `track_forecasts` |
| `event-calendar` | Claude Haiku 5.5 | Builds a 30-day calendar from the configured Treasury source only. | `http_get` |
| `portfolio-review` | Claude Haiku 5.5 | Computes and describes the current book. Never recommends. | `compute_portfolio` |
| `bull-architect` | Claude Sonnet 5.5 | Writes the strongest evidence-based rise cases as scored predictions. | file and knowledge tools |
| `bear-architect` | Claude Sonnet 5.5 | Writes the strongest evidence-based fall cases as scored predictions. | file and knowledge tools |
| `risk-manager` | Claude Sonnet 5.5 | Restates deterministic rule results and blocks on any failed rule. Otherwise it allows, unless a file it read names a risk specific to that stock, such as its own earnings inside a thesis's horizon. Sharing a sector within the limit, a routine Treasury auction or general caution is no reason to reduce. | `check_limits` |
| `decision` | Claude Opus 5.5 | Arbitrates the two cases and risk checks into a recommendation and records the session's forecasts: the theses' own, or labeled baselines. | `track_forecasts`, file tools |
| `review-analyst` | Claude Sonnet 5.5 | Scores predictions, refreshes forecast actuals and diagnoses misses without hindsight. | `score_predictions`, `track_forecasts`, `propose_memory` |
| `market-explainer` | the news scanner's model | Explains a market alert from the day's headlines and saved research, citing each source; never predicts or recommends. Started by [Market watch](2_running_tasks.md#market-watch-alerts-for-sudden-moves). | `read_feed`, file and knowledge tools |

Definitions use fast, balanced, or strong models independently of the space's
model. On OpenAI, collectors and portfolio review move to GPT-6 Luna, balanced
agents move to GPT-6.1 Sol, and `decision` keeps its strong intended level even
though GPT-6.1 Sol covers both levels. On a ChatGPT plan without that model,
balanced shipped agents move to GPT-5.6 Terra and `decision` moves to GPT-5.6
Sol when you apply the provider switch or plan repair. A model you chose yourself
maps by its catalog level.

Prompts treat fetched pages and `raw/` files as untrusted; no built-in uses
shell. The data and computation tools are medium risk. Under the default
**Autonomous** policy, low- and medium-risk calls can run unattended when their
host and tool are allowed. An upgraded install keeps its saved approval and
host settings.

An install created before the deterministic tools may also have older
collector prompts if an agent's model was changed before the pipeline update.
Migration 022 repairs an agent only when its prompt and tool list still match
that exact older shipped definition. It keeps your chosen model and leaves
genuinely edited instructions alone. Restart the app after updating so the
new scheduler and migration are loaded.

Before the first collector run, review these under **Knowledge → Technical Details → Agent files**:

- `config/watchlist.json`: the starter follows MU, ORCL, CRWV, MSFT, NOW and
  AVGO in the US market. Holdings are followed even when absent from the
  watchlist. Daily discovery adds Yahoo Finance's top gainers, losers and
  most active stocks, up to five from each list. Each configured entry needs
  a `ticker` and non-empty `sector`; `company_name` and `aliases` help news
  matching, and `industry` describes its subsector.
- `portfolio/positions.csv`: keep the header
  `ticker,shares,cost_per_share,opened,sector,currency`. Enter current holdings
  plus a `CASH` row whose `shares` is the cash amount, use one ISO currency
  throughout, and maintain the snapshot yourself. Blank `cost_per_share` and
  `opened` mean unknown, so market value and weights still calculate while
  cost-based P&L and holding age remain unavailable.

The other starter inputs are ready to edit: `config/sources.json` names Yahoo
Finance discovery, headlines, prices and annual or quarterly financial
figures, and the US Treasury auctions
API. Yahoo financial figures are a secondary source, not full filing text.
For optional SEC filings metadata, company facts and bounded filing excerpts, put an identifying
contact such as `Your Name your-email@example.com` in
`reports.sec_user_agent`. Missing sources produce an explicit coverage gap.

`config/limits.json` starts at 10% per stock, 70% per sector, and 3% daily
loss. All six sample holdings belong to Technology; industry labels such as
semiconductors and cloud infrastructure describe diversity but do not create
separate sector allowances. Review these defaults as your own risk policy.
No data-source key is stored in a file or exposed to a model.

The news scanner calls the Yahoo market and reports tools; unavailable Yahoo
sources are reported as gaps. The event collector reads its event URLs.
Deterministic market, prices and reports
tools use checked public sources. The three limit keys are enforced by the
portfolio and risk tools. An arbitrary source URL does not add a new parser
or provider.

The forecast tracker uses 1, 2, 3, 5 and 21 US trading sessions ahead;
5 and 21 sessions approximate one week and one month. Weekends and market
holidays are not forecast sessions. The baseline price repeats the latest
close and is explicitly labeled `random_walk_baseline`.

Each bull or bear thesis becomes that stock's forecast at its horizon,
labeled `analyst_thesis`: the middle of its magnitude band in its direction
(5% for `5%+`), or the analyst's own `expected_return_pct` when that lies
inside the band, with the band as its range. Where bull and bear disagree at
a horizon, where a thesis cites evidence that was not saved, and wherever
there is no thesis, the forecast is the baseline, and the tool says why. A
thesis is a judgement, not a measured prediction skill; the weekly review
scores it once the sessions have traded.

Forecasts are recorded between US sessions. A run during US trading hours,
09:30 to 16:00 New York time on weekdays, updates actual prices but records
no new forecast, because a one-day forecast made then would already see part
of the day it predicts. The next run after the close records them; the
scheduled 07:00 runs fall outside those hours.

`track_forecasts` keeps the original predictions in
`predictions/forecasts.json` and creates `predictions/YYYY-MM.xlsx`, one
workbook per month. Each market session has a sheet with a row per stock:
the prediction for 1 day, 2 days, 3 days, 1 week and 1 month ahead, each
with its actual closing price and error beside it once that session has
traded. The last sheet, **All forecasts**, lists every forecast of the month
with its method, assumption band, rationale and evidence. Later runs fill
actual prices as saved prices reach each target session, including
predictions made in earlier months. In **Knowledge → User Summary**, select the
workbook under **Forecast workbooks** and choose **Open in spreadsheet app** (Excel, Numbers or LibreOffice,
whichever opens `.xlsx` files) or **Show in folder**; in a browser tab it offers
**Download Excel workbook** instead. Reopen it after a run to see new actual
prices. Scheduled updates require AgentBase to be open.

A forecast that cites evidence must cite a record saved before the forecast:
a headline, a movers or screener row, or an annual or quarterly figure, which
counts from when its report was fetched.

More JSON does not by itself create richer research. Add data only where the
pipeline has a defined consumer:

- Replace the sample entries in `watchlist.json` with the real companies
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
  portfolio and risk output more than adding descriptive configuration. An
  empty or missing file still runs the chain, as an empty book worth 0.

#### The stage sequence

1. **Morning collection** discovers gainers, losers, high-volume stocks and
   Yahoo headlines, merges them with the watchlist and holdings, then reads
   prices and updates the forecast workbook's actual values.
   No new market session stops the chain without writing a false daily result.
   A new session is followed by company news, available financial reports,
   Treasury auctions, and `compute_portfolio`.
2. **Theses and risk** runs only when a movers file exists. Its date is the
   market session's, which in an Asian morning is the day before your local
   date, and it dates the stage's files. Bull and bear read the newest news,
   movers and calendar files and the computed portfolio, and may cite a
   movers row by its `id`. Each writes a theses file for the session, left
   empty when the evidence supports no call. Each thesis's direction and
   magnitude band become that stock's recorded forecast at its horizon.
   Then `check_limits` produces the
   hard rule results before the risk manager adds judgement: block for a
   failed rule, reduce for a stock-specific risk a file names, and allow on
   an ordinary day.
3. **Daily decision** writes `decisions/{session date}.md`, a recommendation
   for human review. Its table's **Size (% of portfolio)** is the share of
   the portfolio's total value to hold, 0% for a pass. Every row, a pass
   included, has its reasoning. **SOURCES** names what each row rests on: the
   theses, the news headlines and movers figures they cite, and the risk
   checks. An empty theses file is listed too, because it means that analyst
   found nothing worth a call. It records forecasts for the five horizons
   for every stock the session followed: each thesis's from its band, and
   labeled unchanged-close baselines otherwise. It never trades, submits an
   order, or connects to a broker.
4. **Weekly knowledge** updates concept notes from the space's own knowledge
   and company notes from available financial reports and any filing text
   you supplied. Optional SEC research may include a bounded excerpt;
   partial coverage is stated rather than described as a complete report.
5. **Weekly review** calls `score_predictions` for the current UTC month. The
   tool resolves supported session-based predictions once, appends the
   ledger once, and refreshes stable accuracy and calibration files before the
   reviewer proposes durable methodology lessons.

Models do not calculate portfolio figures, limits, returns, hit rates, Brier
scores, or calibration. They may state only figures emitted by the
deterministic tools. Malformed or missing input is reported rather than
guessed. The decision remains a recommendation for you to review.

For the shipped daily chain, a run marked **completed** is not enough to start
the next stage. Morning collection must have verified new-session price rows
with no failed ticker and a successful portfolio calculation. Theses and risk
must have successful hard-rule checks and the dated risk review file. A
failed tool or model call stops the chain, so a rate-limited Yahoo request
cannot turn into empty theses or a decision presented as if the inputs were
complete. A lookup that found nothing does not: the agent is told and can
look again, and the run lists it as a missed lookup. Neither does a request
the app could not run as written once the agent has sent it again and it
ran. Check the run's error details and tool results before trusting its
summary.

The shipped scope does not include Reddit or other social sources, complete
SEC filing archives, keyed APIs, earnings calendars, FOMC or BLS calendars, a
Taiwan-specific chain, or per-schedule time zones. Yahoo's endpoints are
unofficial and can refuse or change; the run reports failed sources and
partial coverage. You may supply filing text and a calendar as local files.

**Timing from Asia.** The new default morning collection runs Tuesday through
Saturday at 07:00 your
time, and the US market closes at 04:00 (summer) or 05:00 (winter) Taipei
time. A morning run therefore observes the previous US session. Existing
edited schedules keep their days and time; review them in Automations for
your local time zone. AgentBase must stay open for automatic collection and
actual-price updates.

This is a research and organising tool, not investment advice.

New spaces instead get three editable, deletable **starter roles**:
`researcher` (`read_file`, `list_dir`, `search_knowledge`, `propose_memory`),
`writer` (`read_file`, `write_file`, `search_knowledge`, `propose_memory`),
and `reviewer` (researcher tools). Add them from Home with **Start from the
starter roles**, including in the default space, or define your own.

The seven investment tools named in the roster above work only in Main, the
default space. An agent in any other space is offered, and may use, the
general tools alone: `read_file`, `list_dir`, `search_knowledge`,
`propose_memory`, `write_file`, `http_get`, `read_feed` and `run_shell`.

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
An agent that uses one of Main's investment tools stays in Main: moving or
copying it elsewhere is refused with the tools it would lose.

Use **Delete** and confirm to remove a definition. Default-space built-ins are
protected; disable them to remove them from supervisor use.

## Custom tools

The app combines registered tools into agent allowlists; it cannot install or
write tools. Adding one requires code; see the
[developer checklist](../developer_guide/5_checklists.md).
