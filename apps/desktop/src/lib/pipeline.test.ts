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
  it("ships the person-supplied inputs and the current keyless sources", () => {
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

    expect(JSON.parse(starter("config/watchlist.json"))).toEqual({ watchlist: [] });
    expect(starter("portfolio/positions.csv")).toBe(
      "ticker,shares,cost_per_share,opened,sector,currency\nCASH,0,,,Cash,USD\n",
    );

    const sources: unknown = JSON.parse(starter("config/sources.json"));
    expect(sources).toEqual({
      news: {
        google_news_rss: {
          url_template:
            "https://news.google.com/rss/search?q={ticker}+when:1d&hl=en-US&gl=US&ceid=US:en",
          auth: "none",
        },
      },
      prices: {
        yahoo_chart: {
          url_template:
            "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d",
          auth: "none",
          unofficial: true,
        },
      },
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
