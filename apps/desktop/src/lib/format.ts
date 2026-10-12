import type { ModelEntry } from "@agentbase/schemas";

/**
 * Pure dashboard rendering helpers. Use each event's absolute `ts`; relative
 * timestamps would change every render.
 */

/** `12:00:05`: the event's own clock time, in the viewer's timezone. */
export function clockTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "--:--:--";

  return [at.getHours(), at.getMinutes(), at.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

/** `2026-09-11 19:03`: the day and the minute, for a list of past runs. */
export function clockDate(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "-";

  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${String(at.getFullYear())}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ` +
    `${pad(at.getHours())}:${pad(at.getMinutes())}`
  );
}

/** `Tue 22 Sep, 09:00` in the viewer's zone: a moment a schedule names, ahead or behind. */
export function whenLabel(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "-";
  return at.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `2026-09` as `September 2026`: a ledger period, for a picker. */
export function periodLabel(period: string): string {
  const [year, month] = period.split("-");
  const index = Number(month) - 1;
  const at = new Date(Number(year), Number.isNaN(index) ? 0 : index, 1);
  if (year === undefined || Number.isNaN(at.getTime())) return period;
  return at.toLocaleString(undefined, { month: "long", year: "numeric" });
}

/** Format a span between two log timestamps: `27s`, `1m 32s`, or `1h 23m`. */
export function formatDuration(milliseconds: number): string {
  const total = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${String(hours)}h ${String(minutes)}m`;
  if (minutes > 0) return `${String(minutes)}m ${String(seconds)}s`;
  return `${String(seconds)}s`;
}

/** Format integer micros as money, matching backend `format_micros`. */
export function formatMicros(micros: number): string {
  return `$${(Math.round(micros) / 1_000_000).toFixed(4)}`;
}

/** `1,234`: thousands separated, for token counts. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** Truncate a single line with an ellipsis. */
export function ellipsise(value: string, limit: number): string {
  const collapsed = value.replace(/\s+/gu, " ").trim();
  return collapsed.length <= limit ? collapsed : `${collapsed.slice(0, limit - 1)}…`;
}

/** Explain how a run began without conflating a timed schedule with Run now. */
export function runOriginLabel(origin: string | null): string | null {
  switch (origin) {
    case null:
    case "ui":
      return null;
    case "schedule":
      return "from schedule";
    case "automation":
      return "started with Run now";
    case "discord":
      return "from Discord";
    case "monitor":
      return "explaining a market alert";
    default:
      return `from ${origin}`;
  }
}

/** `JSON.stringify`, typed as it behaves: `undefined` for a value it cannot serialise. */
const stringify = (value: unknown): string | undefined => JSON.stringify(value);

/** A one-line rendering of a tool call's arguments, for the log. */
export function summariseArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args).map(([key, value]) => {
    const rendered = typeof value === "string" ? value : (stringify(value) ?? String(value));
    return `${key}=${ellipsise(rendered, 40)}`;
  });
  return parts.join(" ");
}

/** The CSS modifier for an event type, used to colour the log and the graph. */
export function eventFamily(type: string): string {
  return type.split(".")[0] ?? "other";
}

/**
 * Format glanceable dollars with cents except for whole values. Usage and the
 * meter tooltip retain the ledger's exact four-place figure.
 */
export function moneyShort(micros: number): string {
  const cents = Math.round(micros / 10_000);
  const dollars = cents / 100;
  return Number.isInteger(dollars) ? `$${String(dollars)}` : `$${dollars.toFixed(2)}`;
}

/** How each provider is named to a person. */
export function providerLabel(provider: string): string {
  switch (provider) {
    case "anthropic":
      return "Anthropic";
    case "openai":
      return "OpenAI";
    case "ollama":
      return "Ollama";
    default:
      return provider;
  }
}

/** GPT variants that name a size rather than a model. */
const SIZE_VARIANTS: ReadonlySet<string> = new Set(["mini", "nano"]);

/**
 * Format known model IDs as vendor names, dropping dated Anthropic snapshots.
 * Preserve unknown user-supplied (for example, Ollama) names unchanged.
 */
export function modelLabel(model: string): string {
  const claude = /^claude-([a-z]+)-(\d+(?:-\d+)?)(?:-\d{8})?$/.exec(model);
  if (claude !== null) {
    const [, family = "", version = ""] = claude;
    return `Claude ${family.charAt(0).toUpperCase()}${family.slice(1)} ${version.replace("-", ".")}`;
  }
  const gpt = /^gpt-([\d.]+[a-z]?)(?:-(.+))?$/.exec(model);
  if (gpt !== null) {
    const [, version = "", variant] = gpt;
    if (variant === undefined) return `GPT-${version}`;
    // Sizes stay lower case, as OpenAI writes them; names (Astra, Sol) do not.
    const shown = SIZE_VARIANTS.has(variant) ? variant : `${variant.charAt(0).toUpperCase()}${variant.slice(1)}`;
    return `GPT-${version} ${shown}`;
  }
  return model;
}

/** Where a model sits in its provider's lineup, in words. */
export const TIER_LABEL: Record<ModelEntry["tier"], string> = {
  frontier: "flagship",
  strong: "high",
  balanced: "balanced",
  fast: "fast",
};

const MICROS_PER_DOLLAR = 1_000_000;

/** "$4", "$0.10", "$1.25": dollars per million tokens, cents only when there are some. */
export function perMillion(micros: number): string {
  const dollars = micros / MICROS_PER_DOLLAR;
  return Number.isInteger(dollars) ? `$${String(dollars)}` : `$${dollars.toFixed(2)}`;
}

/** "Claude Opus 5.5 · high · $4 in / $20 out". */
export function modelOptionLabel(entry: ModelEntry): string {
  return `${modelLabel(entry.id)} · ${TIER_LABEL[entry.tier]} · ${perMillion(entry.input_micros_per_million)} in / ${perMillion(entry.output_micros_per_million)} out`;
}
