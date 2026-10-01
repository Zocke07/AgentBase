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

/** An illustrative research universe across six sectors, not a holding list. */
const WATCHLIST_TEMPLATE = `${JSON.stringify({
  watchlist: [
    { ticker: "AAPL", company_name: "Apple Inc.", sector: "Information Technology" },
    { ticker: "JPM", company_name: "JPMorgan Chase & Co.", sector: "Financials" },
    { ticker: "JNJ", company_name: "Johnson & Johnson", aliases: ["J&J"], sector: "Health Care" },
    { ticker: "XOM", company_name: "Exxon Mobil Corporation", aliases: ["ExxonMobil"], sector: "Energy" },
    { ticker: "PG", company_name: "The Procter & Gamble Company", aliases: ["P&G"], sector: "Consumer Staples" },
    { ticker: "CAT", company_name: "Caterpillar Inc.", sector: "Industrials" },
  ],
}, null, 2)}\n`;

/** The files the investment pipeline starts with, without inventing a holding. */
export const STARTERS: readonly { path: string; content: string; why: string }[] = [
  {
    path: "config/watchlist.json",
    why: "An illustrative six-company research list across sectors, not a holding list or investment advice. The daily collectors follow these tickers; replace them with companies you actually want followed. Every entry needs a ticker and sector; company_name and aliases improve news matching.",
    content: WATCHLIST_TEMPLATE,
  },
  {
    path: "config/sources.json",
    why: "Lists news feeds and event URLs for the collectors. The Yahoo entry documents the price source; read_prices uses its own fixed Yahoo endpoint. Add only a feed or event format an agent understands.",
    content:
      '{\n  "news": {\n    "google_news_rss": {\n      "url_template": "https://news.google.com/rss/search?q={ticker}+when:1d&hl=en-US&gl=US&ceid=US:en",\n      "auth": "none"\n    }\n  },\n  "prices": {\n    "yahoo_chart": {\n      "url_template": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d",\n      "auth": "none",\n      "unofficial": true\n    }\n  },\n  "events": {\n    "treasury_auctions": {\n      "url": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",\n      "auth": "none"\n    }\n  }\n}\n',
  },
  {
    path: "config/limits.json",
    why: "Sets the deterministic guardrails checked before a recommendation: maximum position weight, sector weight and daily loss, all as percentages. Extra keys are not used.",
    content: '{\n  "max_position_pct": 10,\n  "max_sector_pct": 30,\n  "max_daily_loss_pct": 3\n}\n',
  },
  {
    path: "portfolio/positions.csv",
    why: "Holds the current positions and cash snapshot used for value, P&L, weights and concentration. Keep every holding in one currency and update it yourself.",
    content: "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,USD\n",
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
