import type {
  AgentDef,
  ApprovalResponse,
  BudgetResponse,
  ChannelStatusResponse,
  ChatGPTAuthResponse,
  ChatGPTLoginResponse,
  CreateAgentRequest,
  CreateSpaceRequest,
  Event,
  ProviderCatalogueResponse,
  Run,
  SettingsResponse,
  SpaceResponse,
  ToolResponse,
  UpdateAgentRequest,
  UpdateSettingsRequest,
  UpdateSpaceRequest,
  VerifyResponse,
} from "@agentspace/schemas";

import { resolveSidecarBaseUrl } from "./sidecar";

/**
 * Typed calls to the sidecar. Every type comes from `@agentspace/schemas`,
 * generated from the OpenAPI document, so a backend model change breaks the
 * typecheck rather than the runtime. Nothing here touches the run store:
 * events reach the UI through the stream and the reducer, and history fetched
 * here goes through the same reducer.
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

let cachedBaseUrl: Promise<string> | null = null;

/** The sidecar's origin, resolved once per page load. */
export function baseUrl(): Promise<string> {
  cachedBaseUrl ??= resolveSidecarBaseUrl();
  return cachedBaseUrl;
}

/** Forget the cached origin. Exists so tests do not leak one into the next. */
export function resetBaseUrl(): void {
  cachedBaseUrl = null;
}

/**
 * Turn a FastAPI error body into an {@link ApiError}. Three shapes reach here:
 * `{message, field}`, a plain string `detail`, and Pydantic's `[{loc, msg}]`.
 */
function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string") {
    return new ApiError(status, detail);
  }

  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown; msg?: unknown } | undefined;
    const loc = Array.isArray(first?.loc) ? first.loc : [];
    // `loc` is ["body", "field_name"]; the last segment is the field.
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
 * Be told when a request could not reach the sidecar at all (a failed
 * connection, not a 4xx or 5xx). The shell uses it to re-enter its reconnect loop.
 */
export function onTransportFailure(listener: TransportListener): () => void {
  transportListeners.add(listener);
  return () => {
    transportListeners.delete(listener);
  };
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  // Built as a plain record rather than spread from `init.headers`, which is a
  // union including a string-pair array, spreading that yields numeric indices.
  const headers: Record<string, string> =
    init?.body === undefined ? {} : { "Content-Type": "application/json" };

  let response: Response;
  try {
    response = await fetch(`${await baseUrl()}${path}`, { ...init, headers });
  } catch (failure) {
    // `fetch` rejects only when no response came back at all.
    for (const listener of transportListeners) listener();
    throw failure;
  }

  if (!response.ok) {
    // A body that is not JSON is not a reason to lose the status code.
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
 * Change a space. A PATCH: fields left out are untouched, and a rule sent as
 * `null` goes back to inheriting the app-wide default, which is why this
 * cannot drop nulls the way `updateSettings` does.
 */
export const updateSpace = (id: string, body: UpdateSpaceRequest): Promise<SpaceResponse> =>
  request<SpaceResponse>(`/spaces/${id}`, { method: "PATCH", ...asJson(body) });

/** Delete an empty space and its agents. A 409 names why not: the default, or runs. */
export const deleteSpace = (id: string): Promise<void> =>
  requestNoContent(`/spaces/${id}`, { method: "DELETE" });

/** Add fresh copies of the three built-in roles to a space's roster. */
export const seedSpace = (id: string): Promise<AgentDef[]> =>
  request<AgentDef[]>(`/spaces/${id}/seed`, { method: "POST" });

// --- runs -------------------------------------------------------------------

export const listRuns = (limit = 50, spaceId?: string): Promise<Run[]> =>
  request<Run[]>(`/runs${query({ limit, space_id: spaceId })}`);

export const getRun = (runId: string): Promise<Run> => request<Run>(`/runs/${runId}`);

/** Start a run in a space. Omitting the space means the default one. */
export const createRun = (goal: string, spaceId?: string): Promise<Run> =>
  request<Run>("/runs", { method: "POST", ...asJson({ goal, space_id: spaceId ?? null }) });

/**
 * Ask a run to stop. Answers 202 with the row as it stands: the run stops at
 * its next check and writes `run.cancelled` itself, which arrives over the
 * stream like everything else. A 409 names the status of a run that cannot
 * be cancelled.
 */
export const cancelRun = (runId: string): Promise<Run> =>
  request<Run>(`/runs/${runId}/cancel`, { method: "POST" });

/**
 * Remove a finished run, its log and its approvals. Its spend stays in the
 * month's figure. A 409 names why not: the run has not ended (cancel it
 * first), or the sidecar is still letting go of it.
 */
export const deleteRun = (runId: string): Promise<void> =>
  requestNoContent(`/runs/${runId}`, { method: "DELETE" });

/** A run's event log as an array, for opening one and then resuming its stream from the end. */
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

/** A copy of a definition on another space's roster: a new row with a new id. */
export const copyAgent = (id: string, spaceId: string): Promise<AgentDef> =>
  request<AgentDef>(`/agents/${id}/copy`, { method: "POST", ...asJson({ space_id: spaceId }) });

export const deleteAgent = (id: string): Promise<void> =>
  requestNoContent(`/agents/${id}`, { method: "DELETE" });

export const listTools = (): Promise<ToolResponse[]> => request<ToolResponse[]>("/tools");

// --- approvals --------------------------------------------------------------

/** Approvals still awaiting an answer, including ones raised before this window connected. */
export const listApprovals = (runId?: string): Promise<ApprovalResponse[]> =>
  request<ApprovalResponse[]>(runId === undefined ? "/approvals" : `/approvals?run_id=${runId}`);

export const resolveApproval = (id: string, approved: boolean): Promise<ApprovalResponse> =>
  request<ApprovalResponse>(`/approvals/${id}`, { method: "POST", ...asJson({ approved }) });

// --- settings and budget ----------------------------------------------------

/** The month's spend against the one cap; with a space, that space's share too. */
export const getBudget = (spaceId?: string): Promise<BudgetResponse> =>
  request<BudgetResponse>(`/budget${query({ space_id: spaceId })}`);

export const getSettings = (): Promise<SettingsResponse> => request<SettingsResponse>("/settings");

/**
 * Change some settings. A PATCH: fields left out are untouched. A refusal is a
 * 400 carrying `{message, field}`, which the settings screen puts on the input
 * the server named.
 */
export const updateSettings = (patch: UpdateSettingsRequest): Promise<SettingsResponse> =>
  request<SettingsResponse>("/settings", { method: "PATCH", ...asJson(patch) });

/** Whether each chat adapter is actually connected, and why not if not. */
export const getChannels = (): Promise<ChannelStatusResponse[]> =>
  request<ChannelStatusResponse[]>("/channels");

export const listProviders = (): Promise<ProviderCatalogueResponse> =>
  request<ProviderCatalogueResponse>("/settings/providers");

/**
 * Whether the current settings can build a provider: the same refusal a run
 * would get, without a model call. The dashboard's pre-flight before Start.
 */
export const verifySettings = (spaceId?: string): Promise<VerifyResponse> =>
  request<VerifyResponse>(`/settings/verify${query({ space_id: spaceId })}`, { method: "POST" });

/** OAuth state only. Tokens stay inside the pinned Codex runtime and OS keychain. */
export const getChatGPTAuth = (): Promise<ChatGPTAuthResponse> =>
  request<ChatGPTAuthResponse>("/auth/chatgpt");

export const startChatGPTLogin = (): Promise<ChatGPTLoginResponse> =>
  request<ChatGPTLoginResponse>("/auth/chatgpt/login", { method: "POST" });

export const cancelChatGPTLogin = (): Promise<void> =>
  requestNoContent("/auth/chatgpt/login/cancel", { method: "POST" });

export const logoutChatGPT = (): Promise<void> =>
  requestNoContent("/auth/chatgpt/logout", { method: "POST" });
