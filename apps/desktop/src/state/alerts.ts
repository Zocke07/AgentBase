import type { MarketAlert } from "@agentbase/schemas";

/**
 * Market alerts (Phase 18) as the window shows them: grouped by the check
 * that found them, which one run explains, and turned into desktop notices
 * once each. Which notices were already raised is a per-window convenience,
 * kept in browser storage; the alerts themselves live in the sidecar.
 */

/** One check's alerts, explained together. */
export interface AlertBatch {
  readonly batchId: string;
  readonly spaceId: string;
  readonly createdAt: string;
  readonly alerts: readonly MarketAlert[];
  readonly status: MarketAlert["explanation_status"];
  readonly explanation: string | null;
  readonly notePath: string | null;
  readonly runId: string | null;
}

/** Batches in the order their newest alert arrived, newest first. */
export function alertBatches(alerts: readonly MarketAlert[]): AlertBatch[] {
  const batches = new Map<string, MarketAlert[]>();
  for (const alert of alerts) {
    const batch = batches.get(alert.batch_id);
    if (batch === undefined) batches.set(alert.batch_id, [alert]);
    else batch.push(alert);
  }
  return [...batches.values()].flatMap((members) => {
    const [first] = members;
    if (first === undefined) return [];
    return [
      {
        batchId: first.batch_id,
        spaceId: first.space_id,
        createdAt: first.created_at,
        alerts: members,
        status: first.explanation_status,
        explanation: first.explanation ?? null,
        notePath: first.explanation_path ?? null,
        runId: first.explanation_run_id ?? null,
      },
    ];
  });
}

/** `MU down 5.5%`. */
export function moveLabel(alert: MarketAlert): string {
  return `${alert.symbol} ${alert.direction} ${Math.abs(alert.change_pct).toFixed(1)}%`;
}

/** What the move is measured from, in words. */
export function moveBasis(alert: MarketAlert): string {
  if (alert.reference === "window") return `in ${String(alert.window_minutes ?? 15)} minutes`;
  if (alert.reference === "regular_close") return "since today's close, after hours";
  return "since the previous close";
}

export interface Notice {
  readonly key: string;
  readonly title: string;
  readonly body: string;
}

/** Notices for alerts and explanations not yet raised, oldest first. */
export function pendingNotices(alerts: readonly MarketAlert[], raised: ReadonlySet<string>): Notice[] {
  const notices: Notice[] = [];
  for (const batch of alertBatches(alerts).reverse()) {
    const moves = batch.alerts.map(moveLabel).join(", ");
    const symbols = batch.alerts.map((alert) => alert.symbol).join(", ");
    const looking = batch.status === "queued" || batch.status === "running";
    const alertKey = `alert:${batch.batchId}`;
    if (!raised.has(alertKey)) {
      notices.push({
        key: alertKey,
        title: "Market alert",
        body: `${moves}${looking ? ". Looking for the reason." : "."}`,
      });
    }
    const whyKey = `why:${batch.batchId}`;
    if (batch.status === "done" && batch.explanation !== null && !raised.has(whyKey)) {
      notices.push({ key: whyKey, title: `Why ${symbols} moved`, body: batch.explanation });
    }
  }
  return notices;
}

/** Every notice key the alerts could raise now, for a first load to mark as raised. */
export function noticeKeys(alerts: readonly MarketAlert[]): string[] {
  return alertBatches(alerts).flatMap((batch) => [`alert:${batch.batchId}`, `why:${batch.batchId}`]);
}

const RAISED_KEY = "agentbase.alerts.raised";
/** Enough to remember every alert the list returns, and then some. */
const RAISED_LIMIT = 400;

/** Raised notice keys, or `null` when this window has never stored any. */
export function readRaised(): Set<string> | null {
  try {
    const stored = localStorage.getItem(RAISED_KEY);
    if (stored === null) return null;
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? new Set(parsed.filter((key): key is string => typeof key === "string")) : null;
  } catch {
    return null;
  }
}

export function writeRaised(keys: Iterable<string>): void {
  try {
    localStorage.setItem(RAISED_KEY, JSON.stringify([...keys].slice(-RAISED_LIMIT)));
  } catch {
    // Browser storage is optional: at worst a notice is raised again.
  }
}
