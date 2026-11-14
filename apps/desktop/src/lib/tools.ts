/**
 * How each tool is presented: one table for the run's file list, the policy sentence, the schedules' notice and the office
 * (Phase 20, brief 7.2 and 7.6). Before it, four files each named tools on
 * their own.
 *
 * This is presentation only. What a tool may do is decided by the sidecar's
 * registry and the approval gate; nothing here grants or refuses anything.
 * `tools.test.ts` holds the table to the tools the backend declares.
 */

/** What kind of work a tool is, which decides the object on an agent's desk. */
export type ToolFamily =
  /** Starting or handing work to another agent, and finishing. */
  | "delegation"
  /** Reading the space's own files. */
  | "reading"
  /** Writing a file in the space. */
  | "writing"
  /** The space's knowledge: searching it, proposing a memory. */
  | "knowledge"
  /** Fetching from a public address. */
  | "network"
  /** Market data from the pipeline's fixed sources. */
  | "market"
  /** Deterministic arithmetic over saved files. */
  | "computation"
  /** A shell command: high risk, always asked. */
  | "shell"
  /** A tool this build does not know. */
  | "unknown";

export const TOOL_FAMILIES: readonly ToolFamily[] = [
  "delegation",
  "reading",
  "writing",
  "knowledge",
  "network",
  "market",
  "computation",
  "shell",
  "unknown",
];

export interface ToolInfo {
  readonly family: ToolFamily;
  /** Reaches the network, so the host list bounds it. */
  readonly fetches: boolean;
  /**
   * Lists the files it wrote in its result's `written` array. Only these are
   * trusted for that: other tools return read or fetched text, where a
   * `written` key must never become a file link.
   */
  readonly reportsWritten: boolean;
}

const tool = (family: ToolFamily, traits: { fetches?: true; reportsWritten?: true } = {}): ToolInfo => ({
  family,
  fetches: traits.fetches ?? false,
  reportsWritten: traits.reportsWritten ?? false,
});

/** The orchestrator's own calls: they pass no gate and touch nothing. */
export const CONTROL_TOOLS = ["spawn_agent", "handoff", "finish"] as const;

/** Every tool the sidecar ships, and the orchestrator's control calls. */
export const TOOLS: Readonly<Record<string, ToolInfo>> = {
  spawn_agent: tool("delegation"),
  handoff: tool("delegation"),
  finish: tool("delegation"),
  read_file: tool("reading"),
  list_dir: tool("reading"),
  write_file: tool("writing"),
  search_knowledge: tool("knowledge"),
  propose_memory: tool("knowledge"),
  http_get: tool("network", { fetches: true }),
  read_feed: tool("network", { fetches: true }),
  read_prices: tool("market", { fetches: true, reportsWritten: true }),
  read_market: tool("market", { fetches: true, reportsWritten: true }),
  read_company_reports: tool("market", { fetches: true, reportsWritten: true }),
  compute_portfolio: tool("computation", { reportsWritten: true }),
  check_limits: tool("computation", { reportsWritten: true }),
  score_predictions: tool("computation", { reportsWritten: true }),
  track_forecasts: tool("computation", { reportsWritten: true }),
  run_shell: tool("shell"),
};

/** A tool's presentation. One this build does not know keeps its own name. */
export function toolInfo(name: string): ToolInfo {
  // The name is a model's: `constructor` must not find `Object.prototype`'s.
  return Object.hasOwn(TOOLS, name) ? (TOOLS[name] ?? tool("unknown")) : tool("unknown");
}

export const toolFamily = (name: string): ToolFamily => toolInfo(name).family;

/** Tools whose calls reach the network. */
export const FETCHING_TOOLS: readonly string[] = Object.keys(TOOLS).filter((name) => TOOLS[name]?.fetches === true);

/** A family in a few words, for the office's labels and accessible names. */
export const FAMILY_LABEL: Readonly<Record<ToolFamily, string>> = {
  delegation: "handing work on",
  reading: "reading a file",
  writing: "writing a file",
  knowledge: "using the space's knowledge",
  network: "fetching from the web",
  market: "reading market data",
  computation: "working out figures",
  shell: "running a shell command",
  unknown: "using a tool",
};
