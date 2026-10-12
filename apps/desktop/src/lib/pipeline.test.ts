import { describe, expect, it } from "vitest";

import { STARTERS } from "./pipeline";
import {
  DASHBOARD_SCHEMA,
  parseDashboardSpec,
  parseVisualizationSpec,
  VISUALIZATION_SCHEMA,
} from "./visualization";

const starter = (path: string): string => {
  const found = STARTERS.find((entry) => entry.path === path);
  if (found === undefined) throw new Error(`Missing starter ${path}`);
  return found.content;
};

describe("investment pipeline starters", () => {

  it("starts with the requested US holdings, cash and explicit unknown purchase data", () => {
    expect(STARTERS.map((entry) => entry.path)).toEqual([
      "config/watchlist.json",
      "config/sources.json",
      "config/limits.json",
      "portfolio/positions.csv",
      "visualizations/daily-change.viz.json",
      "visualizations/portfolio-weights.viz.json",
      "visualizations/prediction-accuracy.viz.json",
      "visualizations/prediction-calibration.viz.json",
      "visualizations/pipeline.dashboard.json",
    ]);

    const tickers = ["MU", "ORCL", "CRWV", "MSFT", "NOW", "AVGO"];
    const watchlist = JSON.parse(starter("config/watchlist.json")) as {
      watchlist: { ticker: string; company_name: string; aliases: string[]; sector: string; industry: string; exchange: string }[];
    };
    expect(watchlist.watchlist.map((entry) => entry.ticker)).toEqual(tickers);
    expect(watchlist.watchlist.map((entry) => entry.aliases)).toEqual([
      ["Micron"], ["Oracle"], ["CoreWeave"], ["Microsoft"], ["ServiceNow"], ["Broadcom"],
    ]);
    for (const entry of watchlist.watchlist) {
      expect(entry.company_name).not.toBe("");
      expect(entry.sector).toBe("Technology");
      expect(entry.industry).not.toBe("");
      expect(entry.exchange).toBe("US");
    }
    const rows = starter("portfolio/positions.csv").trim().split("\n").slice(1).map((row) => row.split(","));
    expect(rows.slice(0, 6)).toEqual(tickers.map((ticker) => [ticker, "1", "", "", "Technology", "USD"]));
    expect(rows[6]).toEqual(["CASH", "2500", "", "", "Cash", "USD"]);
    expect(JSON.parse(starter("config/limits.json"))).toEqual({
      max_position_pct: 10,
      max_sector_pct: 70,
      max_daily_loss_pct: 3,
    });
  });

  it("configures market discovery, Yahoo headlines and company-report coverage", () => {
    const sources: unknown = JSON.parse(starter("config/sources.json"));
    expect(sources).toMatchObject({
      market: {
        provider: "yahoo",
        screeners: ["day_gainers", "day_losers", "most_actives"],
        limit_per_list: 5,
        headlines: "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbols}&region=US&lang=en-US",
      },
      prices: {
        yahoo_chart: {
          url_template:
            "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d",
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
    });
    expect(starter("config/sources.json").toLowerCase()).not.toContain("stooq");
  });

  it("ships four valid charts over stable tool outputs in one dashboard", () => {
    const expected = {
      "visualizations/daily-change.viz.json": {
        source: "raw/prices/summary.csv",
        chart: "bar",
        x: "ticker",
        y: ["change_pct"],
        series: null,
      },
      "visualizations/portfolio-weights.viz.json": {
        source: "portfolio/weights.csv",
        chart: "pie",
        x: "ticker",
        y: ["weight_pct"],
        series: null,
      },
      "visualizations/prediction-accuracy.viz.json": {
        source: "scores/accuracy.csv",
        chart: "bar",
        x: "horizon_days",
        y: ["hit_rate"],
        series: "agent",
      },
      "visualizations/prediction-calibration.viz.json": {
        source: "scores/calibration.csv",
        chart: "line",
        x: "confidence_bucket",
        y: ["observed_hit_rate"],
        series: "agent",
      },
    } as const;

    for (const [path, fields] of Object.entries(expected)) {
      expect(parseVisualizationSpec(starter(path))).toMatchObject({
        $schema: VISUALIZATION_SCHEMA,
        ...fields,
      });
    }

    expect(parseDashboardSpec(starter("visualizations/pipeline.dashboard.json"))).toEqual({
      $schema: DASHBOARD_SCHEMA,
      title: "Investment pipeline",
      visualizations: Object.keys(expected),
      columns: 2,
    });
  });
});
