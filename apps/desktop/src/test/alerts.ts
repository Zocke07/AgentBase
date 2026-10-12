import type { MarketAlert } from "@agentbase/schemas";

/** One recorded market alert (Phase 18), its fields overridden per test. */
export function marketAlert(overrides: Partial<MarketAlert> = {}): MarketAlert {
  return {
    id: "alert-1",
    space_id: "space-main",
    batch_id: "batch-1",
    symbol: "MU",
    name: "Micron Technology, Inc.",
    instrument: "stock",
    kind: "move",
    direction: "down",
    change_pct: -5.5,
    level_pct: 5,
    price: 94.5,
    reference_price: 100,
    reference: "previous_close",
    window_minutes: null,
    session: "regular",
    market_date: "2026-10-13",
    quoted_at: "2026-10-13T15:00:00+00:00",
    created_at: "2026-10-13T15:00:05+00:00",
    explanation_status: "running",
    explanation_run_id: "run-9",
    explanation_path: "alerts/2026-10-13-1100.md",
    explanation: null,
    seen_at: null,
    ...overrides,
  };
}
