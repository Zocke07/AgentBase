import type {
  AgentDef,
  AlertsResponse,
  ApprovalResponse,
  BudgetResponse,
  ChannelStatusResponse,
  ChatGPTAuthResponse,
  ChatGPTLoginResponse,
  CreateAgentRequest,
  CreateScheduleRequest,
  CreateSpaceRequest,
  Event,
  KnowledgeEvaluation,
  KnowledgeEvaluationCase,
  KnowledgeFolderDeleteResult,
  KnowledgeGraph,
  KnowledgeImportResult,
  KnowledgeIndex,
  KnowledgeMoveResult,
  KnowledgeNote,
  KnowledgeSearch,
  MemoryIndex,
  MemoryItem,
  MemoryMergeResult,
  MemoryStatus,
  MonitorStatus,
  PortfolioResponse,
  PortfolioValuation,
  SavePortfolioRequest,
  ProviderCatalogueResponse,
  ProviderSwitchPlan,
  Run,
  SchedulePreview,
  ScheduleResponse,
  SearchFilters,
  SeenResponse,
  SettingsResponse,
  SpaceResponse,
  TextFile,
  TextFileIndex,
  ToolResponse,
  UpdateAgentRequest,
  UpdateScheduleRequest,
  UpdateSettingsRequest,
  UpdateSpaceRequest,
  UsageReport,
  VerifyResponse,
} from "@agentbase/schemas";

import { resolveSidecarBaseUrl } from "./sidecar";

/**
 * Typed sidecar calls using OpenAPI-generated `@agentbase/schemas` types, so
 * backend model changes fail typechecking. Run events and fetched history both
 * flow through the stream and reducer, never directly into the run store.
 */

/** A 4xx from the sidecar, carrying the field it blames when it named one. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly field: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * A request that got no answer at all: the engine is starting, restarting or
 * gone. The browser's own words for this ("Failed to fetch", "Load failed")
 * reached people as the reason a save or a delete did not happen.
 */
export class ConnectionError extends Error {
  constructor(options?: ErrorOptions) {
    super("AgentBase's engine did not answer. It may be starting or restarting; try again in a moment.", options);
    this.name = "ConnectionError";
  }
}

export { failureMessage, isMissing } from "./errors";

let cachedBaseUrl: Promise<string> | null = null;

/** Cached sidecar origin, resolved once per page load. */
export function baseUrl(): Promise<string> {
  cachedBaseUrl ??= resolveSidecarBaseUrl();
  return cachedBaseUrl;
}

/** Clear the cached origin to isolate tests. */
export function resetBaseUrl(): void {
  cachedBaseUrl = null;
}

/**
 * Convert FastAPI `{message, field}`, string `detail`, or Pydantic
 * `[{loc, msg}]` errors into {@link ApiError}.
 */
function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string") {
    return new ApiError(status, detail);
  }

  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown; msg?: unknown } | undefined;
    const loc = Array.isArray(first?.loc) ? first.loc : [];
    // Pydantic `loc` ends with the field name.
    const field = loc.length > 0 ? String(loc[loc.length - 1]) : null;
    const message = typeof first?.msg === "string" ? first.msg : `HTTP ${String(status)}`;
    return new ApiError(status, message, field);
  }

  if (typeof detail === "object" && detail !== null) {
    const shaped = detail as { message?: unknown; field?: unknown };
    return new ApiError(
      status,
      typeof shaped.message === "string" ? shaped.message : `HTTP ${String(status)}`,
      typeof shaped.field === "string" ? shaped.field : null,
    );
  }

  return new ApiError(status, `HTTP ${String(status)}`);
}

type TransportListener = () => void;
const transportListeners = new Set<TransportListener>();

/**
 * Subscribe to connection failures only, excluding sidecar 4xx/5xx responses.
 * The shell uses these to resume reconnecting.
 */
export function onTransportFailure(listener: TransportListener): () => void {
  transportListeners.add(listener);
  return () => {
    transportListeners.delete(listener);
  };
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  // Avoid spreading `init.headers`: its tuple-array variant creates numeric keys.
  const headers: Record<string, string> =
    init?.body === undefined ? {} : { "Content-Type": "application/json" };

  let response: Response;
  try {
    response = await fetch(`${await baseUrl()}${path}`, { ...init, headers });
  } catch (failure) {
    // `fetch` rejects only when no response arrives.
    for (const listener of transportListeners) listener();
    throw new ConnectionError({ cause: failure });
  }

  if (!response.ok) {
    // Retain the status code when the body is not JSON.
    const body: unknown = await response.json().catch(() => null);
    throw toApiError(response.status, body);
  }

  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

/** For the endpoints that answer 204, where there is nothing to parse. */
async function requestNoContent(path: string, init?: RequestInit): Promise<void> {
  await send(path, init);
}

const asJson = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

/** `?a=1&b=2` from the entries that have a value; `""` when none do. */
function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered === "" ? "" : `?${rendered}`;
}

// --- spaces -----------------------------------------------------------------

/** Every space, archived ones included, their runs are still viewable. */
export const listSpaces = (): Promise<SpaceResponse[]> => request<SpaceResponse[]>("/spaces");

export const createSpace = (body: CreateSpaceRequest): Promise<SpaceResponse> =>
  request<SpaceResponse>("/spaces", { method: "POST", ...asJson(body) });

/**
 * PATCH a space: omitted fields stay unchanged and `null` restores app-wide
 * inheritance, so unlike `updateSettings`, nulls are retained. The provider
 * is the exception: a space names its own, and a null one is refused.
 */
export const updateSpace = (id: string, body: UpdateSpaceRequest): Promise<SpaceResponse> =>
  request<SpaceResponse>(`/spaces/${id}`, { method: "PATCH", ...asJson(body) });

/**
 * What moving a space to `provider` would change, before anything is saved:
 * its model mapped by tier, and the agents left naming the old provider.
 */
export const planProviderSwitch = (spaceId: string, provider: string): Promise<ProviderSwitchPlan> =>
  request<ProviderSwitchPlan>(`/spaces/${spaceId}/provider-switch${query({ provider })}`);

/** Delete an empty space and its agents; 409 identifies a default space or runs. */
export const deleteSpace = (id: string): Promise<void> =>
  requestNoContent(`/spaces/${id}`, { method: "DELETE" });

/** Add fresh copies of the three starter roles to a space's roster. */
export const seedSpace = (id: string): Promise<AgentDef[]> =>
  request<AgentDef[]>(`/spaces/${id}/seed`, { method: "POST" });

// --- schedules --------------------------------------------------------------

/** One space's schedules, by name. */
export const listSchedules = (spaceId: string): Promise<ScheduleResponse[]> =>
  request<ScheduleResponse[]>(`/schedules${query({ space_id: spaceId })}`);

export const createSchedule = (body: CreateScheduleRequest): Promise<ScheduleResponse> =>
  request<ScheduleResponse>("/schedules", { method: "POST", ...asJson(body) });

/** A PATCH: fields left out are untouched. A cadence or enabled change recomputes the next time. */
export const updateSchedule = (id: string, body: UpdateScheduleRequest): Promise<ScheduleResponse> =>
  request<ScheduleResponse>(`/schedules/${id}`, { method: "PATCH", ...asJson(body) });

export const deleteSchedule = (id: string): Promise<void> =>
  requestNoContent(`/schedules/${id}`, { method: "DELETE" });

/** Start the schedule's run now, leaving its next time as it was. */
export const runScheduleNow = (id: string): Promise<Run> =>
  request<Run>(`/schedules/${id}/run`, { method: "POST" });

/** The cadence in words and its next few times, before it is saved. */
export const previewSchedule = (cadence: CreateScheduleRequest["cadence"]): Promise<SchedulePreview> =>
  request<SchedulePreview>("/schedules/preview", { method: "POST", ...asJson({ cadence }) });

// --- knowledge -------------------------------------------------------------

/** Rebuild the live Markdown vault index so external Obsidian edits appear. */
export const listKnowledge = (spaceId: string): Promise<KnowledgeIndex> =>
  request<KnowledgeIndex>(`/spaces/${spaceId}/knowledge`);

export const getKnowledgeNote = (spaceId: string, path: string): Promise<KnowledgeNote> =>
  request<KnowledgeNote>(`/spaces/${spaceId}/knowledge/note${query({ path })}`);

/** `create` refuses a path that is taken, rather than replacing a note nobody opened. */
export const saveKnowledgeNote = (
  spaceId: string,
  path: string,
  content: string,
  options: { create?: boolean } = {},
): Promise<KnowledgeNote> =>
  request<KnowledgeNote>(`/spaces/${spaceId}/knowledge/note`, {
    method: "PUT",
    ...asJson({ path, content, ...(options.create === true ? { create: true } : {}) }),
  });

export const deleteKnowledgeNote = (spaceId: string, path: string): Promise<void> =>
  requestNoContent(`/spaces/${spaceId}/knowledge/note${query({ path })}`, { method: "DELETE" });

/** Editable text files and downloadable Excel workbooks beside the notes. */
export const listFiles = (spaceId: string): Promise<TextFileIndex> => request<TextFileIndex>(`/spaces/${spaceId}/knowledge/files`);

export const getFile = (spaceId: string, path: string): Promise<TextFile> =>
  request<TextFile>(`/spaces/${spaceId}/knowledge/file${query({ path })}`);

/** Personal stock inputs saved in the same files read by runs. */
export const getPortfolio = (spaceId: string): Promise<PortfolioResponse> =>
  request<PortfolioResponse>(`/spaces/${spaceId}/portfolio`);

/** The newest valuation a run saved, or null before the first. */
export const getPortfolioValuation = (spaceId: string): Promise<PortfolioValuation | null> =>
  request<PortfolioValuation | null>(`/spaces/${spaceId}/portfolio/valuation`);

export const savePortfolio = (spaceId: string, body: SavePortfolioRequest): Promise<PortfolioResponse> =>
  request<PortfolioResponse>(`/spaces/${spaceId}/portfolio`, { method: "PUT", ...asJson(body) });

/** Keep workbook bytes intact; the download route uses the space's file rules. */
export const downloadFile = async (spaceId: string, path: string): Promise<Blob> =>
  (await send(`/spaces/${spaceId}/knowledge/download${query({ path })}`)).blob();

/** `create` refuses a path that is taken, rather than replacing a file nobody opened. */
export const writeFile = (
  spaceId: string,
  path: string,
  content: string,
  options: { create?: boolean } = {},
): Promise<TextFile> =>
  request<TextFile>(`/spaces/${spaceId}/knowledge/file`, {
    method: "PUT",
    ...asJson({ path, content, ...(options.create === true ? { create: true } : {}) }),
  });

export const deleteFile = (spaceId: string, path: string): Promise<void> =>
  requestNoContent(`/spaces/${spaceId}/knowledge/file${query({ path })}`, { method: "DELETE" });

/** Back up then delete a folder and all descendants. */
export const deleteKnowledgeFolder = (spaceId: string, path: string): Promise<KnowledgeFolderDeleteResult> =>
  request<KnowledgeFolderDeleteResult>(`/spaces/${spaceId}/knowledge/folder${query({ path })}`, { method: "DELETE" });

export const searchKnowledge = (
  spaceId: string,
  search: string,
  limit = 8,
  filters?: SearchFilters,
): Promise<KnowledgeSearch> =>
  request<KnowledgeSearch>(`/spaces/${spaceId}/knowledge/search`, {
    method: "POST",
    ...asJson({ query: search, limit, filters }),
  });

export const getKnowledgeGraph = (spaceId: string): Promise<KnowledgeGraph> =>
  request<KnowledgeGraph>(`/spaces/${spaceId}/knowledge/graph`);

export const moveKnowledgeNote = (
  spaceId: string,
  source: string,
  target: string,
): Promise<KnowledgeMoveResult> =>
  request<KnowledgeMoveResult>(`/spaces/${spaceId}/knowledge/move`, {
    method: "POST",
    ...asJson({ source, target, update_links: true }),
  });

export const importKnowledge = (
  spaceId: string,
  files: { path: string; content: string }[],
  overwrite: boolean,
): Promise<KnowledgeImportResult> =>
  request<KnowledgeImportResult>(`/spaces/${spaceId}/knowledge/import`, {
    method: "POST",
    ...asJson({ files, overwrite }),
  });

export const listMemories = (spaceId: string): Promise<MemoryIndex> =>
  request<MemoryIndex>(`/spaces/${spaceId}/knowledge/memories`);

export const updateMemory = (
  spaceId: string,
  path: string,
  changes: { status?: MemoryStatus; pinned?: boolean },
): Promise<MemoryItem> =>
  request<MemoryItem>(`/spaces/${spaceId}/knowledge/memory`, {
    method: "PATCH",
    ...asJson({ path, ...changes }),
  });

/** Merge memories into one note; archive originals with a backup. */
export const mergeMemories = (
  spaceId: string,
  paths: string[],
  title?: string,
): Promise<MemoryMergeResult> =>
  request<MemoryMergeResult>(`/spaces/${spaceId}/knowledge/memories/merge`, {
    method: "POST",
    ...asJson({ paths, title: title ?? null }),
  });

/** Pin or unpin any note; pinned notes pass every retrieval filter. */
export const pinKnowledgeNote = (
  spaceId: string,
  path: string,
  pinned: boolean,
): Promise<KnowledgeNote> =>
  request<KnowledgeNote>(`/spaces/${spaceId}/knowledge/pin`, {
    method: "PATCH",
    ...asJson({ path, pinned }),
  });

export const evaluateKnowledge = (
  spaceId: string,
  cases: KnowledgeEvaluationCase[],
  limit = 5,
): Promise<KnowledgeEvaluation> =>
  request<KnowledgeEvaluation>(`/spaces/${spaceId}/knowledge/evaluate`, {
    method: "POST",
    ...asJson({ cases, limit }),
  });

// --- runs -------------------------------------------------------------------

/** Where a run was started from, as the `runs` table records it. */
export type RunOrigin = Run["origin"];

export const listRuns = (limit = 50, spaceId?: string, origin?: RunOrigin): Promise<Run[]> =>
  request<Run[]>(`/runs${query({ limit, space_id: spaceId, origin })}`);

export const getRun = (runId: string): Promise<Run> => request<Run>(`/runs/${runId}`);

/** Start a run in a space. Omitting the space means the default one. */
export const createRun = (
  goal: string,
  spaceId?: string,
  excludedCitations: string[] = [],
  /** Step through: every call asks, the manual and debug path. */
  supervised = false,
): Promise<Run> =>
  request<Run>("/runs", {
    method: "POST",
    ...asJson({
      goal,
      space_id: spaceId ?? null,
      excluded_citations: excludedCitations,
      ...(supervised ? { supervised: true } : {}),
    }),
  });

/**
 * Request cancellation. The 202 returns the current row; the run stops at its
 * next check and streams `run.cancelled`. A 409 reports an ineligible status.
 */
export const cancelRun = (runId: string): Promise<Run> =>
  request<Run>(`/runs/${runId}/cancel`, { method: "POST" });

/**
 * Delete a finished run, log, and approvals while preserving monthly spend. A
 * 409 reports a nonterminal run or sidecar cleanup still in progress.
 */
export const deleteRun = (runId: string): Promise<void> =>
  requestNoContent(`/runs/${runId}`, { method: "DELETE" });

/** Fetch a run log before resuming its stream from the final event. */
export const getRunHistory = (runId: string): Promise<Event[]> =>
  request<Event[]>(`/runs/${runId}/events/history`);

export const startDebugRun = (): Promise<Run> =>
  request<Run>("/debug/fake_run", { method: "POST" });

// --- agents -----------------------------------------------------------------

/** One space's roster, or every definition when no space is named. */
export const listAgents = (spaceId?: string): Promise<AgentDef[]> =>
  request<AgentDef[]>(`/agents${query({ space_id: spaceId })}`);

export const createAgent = (body: CreateAgentRequest): Promise<AgentDef> =>
  request<AgentDef>("/agents", { method: "POST", ...asJson(body) });

export const updateAgent = (id: string, body: UpdateAgentRequest): Promise<AgentDef> =>
  request<AgentDef>(`/agents/${id}`, { method: "PATCH", ...asJson(body) });

/** Copy a definition to another roster as a new row with a new ID. */
export const copyAgent = (id: string, spaceId: string): Promise<AgentDef> =>
  request<AgentDef>(`/agents/${id}/copy`, { method: "POST", ...asJson({ space_id: spaceId }) });

export const deleteAgent = (id: string): Promise<void> =>
  requestNoContent(`/agents/${id}`, { method: "DELETE" });

/**
 * Every tool, or the ones a space's agents may use: a space other than the
 * default is offered the general tools only, since the investment pipeline's
 * stay in the default space.
 */
export const listTools = (spaceId?: string | null): Promise<ToolResponse[]> =>
  request<ToolResponse[]>(`/tools${query({ space_id: spaceId })}`);

// --- approvals --------------------------------------------------------------

/** Fetch unanswered approvals, including those raised before window connection. */
export const listApprovals = (runId?: string): Promise<ApprovalResponse[]> =>
  request<ApprovalResponse[]>(runId === undefined ? "/approvals" : `/approvals?run_id=${runId}`);

/** Answer an approval; a `run`-scope yes covers later calls to that tool. */
export const resolveApproval = (
  id: string,
  approved: boolean,
  scope: "call" | "run" = "call",
): Promise<ApprovalResponse> =>
  request<ApprovalResponse>(`/approvals/${id}`, { method: "POST", ...asJson({ approved, scope }) });

// --- settings and budget ----------------------------------------------------

/** The month's spend against the one cap; with a space, that space's share too. */
export const getBudget = (spaceId?: string): Promise<BudgetResponse> =>
  request<BudgetResponse>(`/budget${query({ space_id: spaceId })}`);

export const getSettings = (): Promise<SettingsResponse> => request<SettingsResponse>("/settings");

/**
 * PATCH settings, preserving omitted fields. A rejected 400 includes
 * `{message, field}` for the named input.
 */
export const updateSettings = (patch: UpdateSettingsRequest): Promise<SettingsResponse> =>
  request<SettingsResponse>("/settings", { method: "PATCH", ...asJson(patch) });

/** A month of model calls from the ledger, sliced; `period` is `YYYY-MM`, this month if omitted. */
export const getUsage = (period: string | null, spaceId: string | null): Promise<UsageReport> =>
  request<UsageReport>(`/usage${query({ period, space_id: spaceId })}`);

/** Whether each chat adapter is actually connected, and why not if not. */
export const getChannels = (): Promise<ChannelStatusResponse[]> =>
  request<ChannelStatusResponse[]>("/channels");

export const listProviders = (): Promise<ProviderCatalogueResponse> =>
  request<ProviderCatalogueResponse>("/settings/providers");

/**
 * Check whether settings can build a provider without a model call; dashboard
 * preflight yields the same refusal as starting a run.
 */
export const verifySettings = (spaceId?: string): Promise<VerifyResponse> =>
  request<VerifyResponse>(`/settings/verify${query({ space_id: spaceId })}`, { method: "POST" });

/** Fetch OAuth state only; tokens remain in the pinned runtime and OS keychain. */
export const getChatGPTAuth = (): Promise<ChatGPTAuthResponse> =>
  request<ChatGPTAuthResponse>("/auth/chatgpt");

/** Fetch the pinned App Server runtime into the data directory; idempotent while it runs. */
export const installChatGPTRuntime = (): Promise<ChatGPTAuthResponse> =>
  request<ChatGPTAuthResponse>("/auth/chatgpt/runtime", { method: "POST" });

export const startChatGPTLogin = (): Promise<ChatGPTLoginResponse> =>
  request<ChatGPTLoginResponse>("/auth/chatgpt/login", { method: "POST" });

export const cancelChatGPTLogin = (): Promise<void> =>
  requestNoContent("/auth/chatgpt/login/cancel", { method: "POST" });

export const logoutChatGPT = (): Promise<void> =>
  requestNoContent("/auth/chatgpt/logout", { method: "POST" });

/** Market alerts (Phase 18), newest first, in one space or all, and how many are unseen. */
export const listAlerts = (spaceId?: string, limit = 50): Promise<AlertsResponse> =>
  request<AlertsResponse>(`/alerts${query({ space_id: spaceId, limit })}`);

/** Mark a space's alerts, or every space's, as seen. */
export const markAlertsSeen = (spaceId?: string): Promise<SeenResponse> =>
  request<SeenResponse>("/alerts/seen", { method: "POST", ...asJson({ space_id: spaceId ?? null }) });

/** A space's market watch: on or off, what it follows, when it last looked. */
export const getMonitor = (spaceId: string): Promise<MonitorStatus> =>
  request<MonitorStatus>(`/spaces/${spaceId}/monitor`);

/** Switch the watch by its file, writing the starter file the first time. */
export const setMonitor = (spaceId: string, enabled: boolean): Promise<MonitorStatus> =>
  request<MonitorStatus>(`/spaces/${spaceId}/monitor`, { method: "PUT", ...asJson({ enabled }) });
