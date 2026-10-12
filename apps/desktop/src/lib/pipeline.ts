import type { ScheduleResponse } from "@agentbase/schemas";

import * as api from "./api";
import {
  DASHBOARD_SCHEMA,
  dashboardJson,
  VISUALIZATION_SCHEMA,
  visualizationJson,
  type DashboardSpec,
  type VisualizationSpec,
} from "./visualization";

/**
 * The shipped investment pipeline: the data files its agents read, and the
 * five schedules migration 019 seeds switched off in the default space. Home
 * and Automations turn it on with one click, which writes any missing file
 * from its template through the same file API a person uses, then enables
 * every stage. Nothing here spends until that click.
 */

const DAILY_CHANGE: VisualizationSpec = {
  $schema: VISUALIZATION_SCHEMA,
  title: "Daily change by ticker",
  source: "raw/prices/summary.csv",
  chart: "bar",
  x: "ticker",
  y: ["change_pct"],
  series: null,
  aggregate: "none",
  sort: "value-descending",
  limit: 50,
};

const PORTFOLIO_WEIGHTS: VisualizationSpec = {
  $schema: VISUALIZATION_SCHEMA,
  title: "Portfolio weights",
  source: "portfolio/weights.csv",
  chart: "pie",
  x: "ticker",
  y: ["weight_pct"],
  series: null,
  aggregate: "none",
  sort: "value-descending",
  limit: 100,
};

const PREDICTION_ACCURACY: VisualizationSpec = {
  $schema: VISUALIZATION_SCHEMA,
  title: "Prediction hit rate",
  source: "scores/accuracy.csv",
  chart: "bar",
  x: "horizon_days",
  y: ["hit_rate"],
  series: "agent",
  aggregate: "none",
  sort: "x-ascending",
  limit: 100,
};

const PREDICTION_CALIBRATION: VisualizationSpec = {
  $schema: VISUALIZATION_SCHEMA,
  title: "Prediction calibration",
  source: "scores/calibration.csv",
  chart: "line",
  x: "confidence_bucket",
  y: ["observed_hit_rate"],
  series: "agent",
  aggregate: "none",
  sort: "x-ascending",
  limit: 100,
};

const PIPELINE_DASHBOARD: DashboardSpec = {
  $schema: DASHBOARD_SCHEMA,
  title: "Investment pipeline",
  visualizations: [
    "visualizations/daily-change.viz.json",
    "visualizations/portfolio-weights.viz.json",
    "visualizations/prediction-accuracy.viz.json",
    "visualizations/prediction-calibration.viz.json",
  ],
  columns: 2,
};

/** The requested US technology sample; source metadata also aids news matching. */
const WATCHLIST_TEMPLATE = `${JSON.stringify({
  watchlist: [
    { ticker: "MU", company_name: "Micron Technology, Inc.", aliases: ["Micron"], sector: "Technology", industry: "Semiconductors", exchange: "US" },
    { ticker: "ORCL", company_name: "Oracle Corporation", aliases: ["Oracle"], sector: "Technology", industry: "Software - Infrastructure", exchange: "US" },
    { ticker: "CRWV", company_name: "CoreWeave, Inc.", aliases: ["CoreWeave"], sector: "Technology", industry: "Cloud Infrastructure", exchange: "US" },
    { ticker: "MSFT", company_name: "Microsoft Corporation", aliases: ["Microsoft"], sector: "Technology", industry: "Software - Infrastructure", exchange: "US" },
    { ticker: "NOW", company_name: "ServiceNow, Inc.", aliases: ["ServiceNow"], sector: "Technology", industry: "Software - Application", exchange: "US" },
    { ticker: "AVGO", company_name: "Broadcom Inc.", aliases: ["Broadcom"], sector: "Technology", industry: "Semiconductors", exchange: "US" },
  ],
}, null, 2)}\n`;

/** Starter research inputs; existing user files always take precedence. */
export const STARTERS: readonly { path: string; content: string; why: string }[] = [
  {
    path: "config/watchlist.json",
    why: "The sample follows MU, ORCL, CRWV, MSFT, NOW and AVGO, plus your saved holdings and daily market candidates. Every entry needs a ticker and sector; company_name and aliases improve news matching. Industry describes subsectors while Technology remains the shared concentration limit.",
    content: WATCHLIST_TEMPLATE,
  },
  {
    path: "config/sources.json",
    why: "Yahoo Finance supplies daily gainers, losers, high-volume stocks, headlines, prices and annual or quarterly financial figures. Yahoo figures are a secondary source. Optional SEC filings metadata, company facts and bounded filing excerpts require an identifying contact in sec_user_agent; unavailable sources are recorded as coverage gaps.",
    content: `${JSON.stringify({
      market: {
        provider: "yahoo",
        screeners: ["day_gainers", "day_losers", "most_actives"],
        limit_per_list: 5,
        headlines: "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbols}&region=US&lang=en-US",
      },
      prices: {
        yahoo_chart: {
          url_template: "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d",
          auth: "none",
          unofficial: true,
        },
      },
      reports: { provider: "yahoo", sec_user_agent: "" },
      events: {
        treasury_auctions: {
          url: "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",
          auth: "none",
        },
      },
    }, null, 2)}\n`,
  },
  {
    path: "config/limits.json",
    why: "Sets the deterministic guardrails checked before a recommendation: maximum position weight, sector weight and daily loss, all as percentages. Extra keys are not used.",
    content: '{\n  "max_position_pct": 10,\n  "max_sector_pct": 70,\n  "max_daily_loss_pct": 3\n}\n',
  },
  {
    path: "portfolio/positions.csv",
    why: "The sample has one share each of MU, ORCL, CRWV, MSFT, NOW and AVGO and $2,500 cash, all USD. Cost and purchase date are unknown and left blank; value and risk still calculate, while cost-based P&L stays unavailable. Replace the sample with your actual holdings and keep one currency per portfolio.",
    content: "ticker,shares,cost_per_share,opened,sector,currency\nMU,1,,,Technology,USD\nORCL,1,,,Technology,USD\nCRWV,1,,,Technology,USD\nMSFT,1,,,Technology,USD\nNOW,1,,,Technology,USD\nAVGO,1,,,Technology,USD\nCASH,2500,,,Cash,USD\n",
  },
  {
    path: "visualizations/daily-change.viz.json",
    why: "the chart of the latest price change by ticker",
    content: visualizationJson(DAILY_CHANGE),
  },
  {
    path: "visualizations/portfolio-weights.viz.json",
    why: "the chart of current portfolio weights",
    content: visualizationJson(PORTFOLIO_WEIGHTS),
  },
  {
    path: "visualizations/prediction-accuracy.viz.json",
    why: "the chart of hit rate by agent and horizon",
    content: visualizationJson(PREDICTION_ACCURACY),
  },
  {
    path: "visualizations/prediction-calibration.viz.json",
    why: "the chart of observed results by confidence bucket",
    content: visualizationJson(PREDICTION_CALIBRATION),
  },
  {
    path: "visualizations/pipeline.dashboard.json",
    why: "the four-chart investment pipeline dashboard",
    content: dashboardJson(PIPELINE_DASHBOARD),
  },
];

/** The seeded pipeline schedules, by the fixed ids migration 019 gives them. */
export const PIPELINE_SCHEDULE_IDS: readonly string[] = [
  "a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11",
  "b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22",
  "c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33",
  "dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44",
  "ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55",
];

/** The seeded pipeline schedules still present in a space's list, in stage order. */
export function pipelineOf(schedules: readonly ScheduleResponse[]): ScheduleResponse[] {
  return PIPELINE_SCHEDULE_IDS.flatMap((id) => schedules.filter((row) => row.id === id));
}

/** Whether a space holds the seeded pipeline with none of it switched on yet. */
export function pipelineWaiting(schedules: readonly ScheduleResponse[]): boolean {
  const seeded = pipelineOf(schedules);
  return seeded.length > 0 && seeded.every((row) => row.enabled === false);
}

/** What turning the pipeline on did: files written, and stages that refused. */
export interface PipelineResult {
  written: string[];
  /** A stage and the sidecar's reason, such as one whose schedule was deleted. */
  failed: { name: string; reason: string }[];
}

/**
 * Write any missing data file from its template, then enable every seeded
 * stage. An existing file is never overwritten, whatever the case of its name
 * (Windows and macOS folders ignore case). A stage that refuses does not stop
 * the others; the result names it.
 */
export async function turnOnPipeline(spaceId: string, schedules: readonly ScheduleResponse[]): Promise<PipelineResult> {
  const present = new Set((await api.listFiles(spaceId)).files.map((file) => file.path.toLowerCase()));
  const written: string[] = [];
  for (const starter of STARTERS) {
    if (present.has(starter.path.toLowerCase())) continue;
    await api.writeFile(spaceId, starter.path, starter.content);
    written.push(starter.path);
  }
  const failed: PipelineResult["failed"] = [];
  for (const row of pipelineOf(schedules)) {
    if (row.enabled !== false) continue;
    try {
      await api.updateSchedule(row.id, { enabled: true });
    } catch (failure) {
      failed.push({ name: row.name, reason: failure instanceof Error ? failure.message : String(failure) });
    }
  }
  return { written, failed };
}

/** The notice after an attempt; `null` when the offer shows its own error. */
export function pipelineNotice(result: PipelineResult | null): string | null {
  if (result === null) return null;
  const created = result.written.length > 0
    ? ` Created ${String(result.written.length)} starter ${result.written.length === 1 ? "file" : "files"}.`
    : "";
  if (result.failed.length === 0) return `The pipeline is on.${created}`;
  const refused = result.failed.map((stage) => `${stage.name} (${stage.reason})`).join("; ");
  return `Part of the pipeline is on.${created} Not turned on: ${refused}.`;
}
