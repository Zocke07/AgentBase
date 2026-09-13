/**
 * Generated from the sidecar's OpenAPI schema. Do not edit.
 *
 * Regenerate with `just schemas`; `test_openapi_snapshot.py` fails if this
 * file drifts from the FastAPI app. A field is optional here exactly when the
 * schema does not list it as required.
 */


/** One row of `agent_defs` (§4). Frozen: a run holds a snapshot of it. */
export interface AgentDef {
  id: string;
  space_id: string;
  name: string;
  role: string;
  system_prompt: string;
  provider?: string | null;
  model?: string | null;
  allowed_tools?: string[];
  max_steps?: number;
  auto_approve?: RiskLevel[];
  is_builtin?: boolean;
  enabled?: boolean;
  created_at: string;
  updated_at: string;
}

/** One approval, as the dialog renders it. */
export interface ApprovalResponse {
  id: string;
  run_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk: string;
  status: string;
  created_at: string;
  resolved_at?: string | null;
}

export interface BudgetResponse {
  period: string;
  spent_micros: number;
  cap_micros: number;
  percent_used: number;
  spent_display: string;
  cap_display: string;
  space_spent_micros?: number | null;
  space_spent_display?: string | null;
}

/** One allowlist entry: this person, on this channel, is that identity. */
export interface ChannelIdentity {
  channel: "discord";
  external_user_id: string;
  identity: string;
}

/** One adapter, as the settings screen renders it. */
export interface ChannelStatusResponse {
  channel: string;
  enabled: boolean;
  configured: boolean;
  running: boolean;
  failures: number;
  last_error?: string | null;
  refused?: string[];
}

/** Where the copy goes. A copy is a new row with a new id, never a built-in. */
export interface CopyAgentRequest {
  space_id: string;
}

/** Seed a new space with copies of another space's roster. */
export interface CopyFrom {
  copy_from: string;
}

/**
 * A new definition.
 *
 * Not :class:`~agentspace.store.agents.AgentDef`: a caller must not mint a built-in.
 */
export interface CreateAgentRequest {
  space_id?: string | null;
  name: string;
  role: string;
  system_prompt: string;
  provider?: string | null;
  model?: string | null;
  allowed_tools?: string[];
  max_steps?: number | null;
  auto_approve?: string[];
  enabled?: boolean;
}

export interface CreateRunRequest {
  goal: string;
  space_id?: string | null;
  origin?: "ui" | "discord";
  origin_ref?: string | null;
}

export interface CreateSpaceRequest {
  name: string;
  description?: string;
  seed?: "empty" | "builtins" | CopyFrom;
}

/**
 * One append-only row of the log.
 *
 * ``seq`` is per-run and 1-based: the SSE id and the ``Last-Event-ID``
 * cursor. ``id`` is the global rowid and is never a resume cursor.
 */
export interface Event {
  id: number;
  run_id: string;
  seq: number;
  agent_id?: string | null;
  type: EventType;
  payload?: Record<string, unknown>;
  ts: string;
}

/** Every event this application can emit. The list is from §4, verbatim. */
export type EventType =
  | "run.started"
  | "run.completed"
  | "run.failed"
  | "run.paused"
  | "run.cancelled"
  | "agent.spawned"
  | "agent.thinking"
  | "agent.message"
  | "agent.handoff"
  | "agent.completed"
  | "llm.request"
  | "llm.token"
  | "llm.response"
  | "llm.error"
  | "tool.requested"
  | "tool.approved"
  | "tool.denied"
  | "tool.called"
  | "tool.result"
  | "tool.error"
  | "approval.requested"
  | "approval.resolved"
  | "budget.warning"
  | "budget.exceeded"
  | "channel.inbound"
  | "channel.outbound";

export interface HTTPValidationError {
  detail?: ValidationError[];
}

/** What `/health` says. The shell polls it to decide the sidecar is up. */
export interface HealthResponse {
  ok: boolean;
  instance: string | null;
}

/** What can be selected, and which models are priced, per provider. */
export interface ProviderCatalogueResponse {
  providers: ProviderEntry[];
  models: Record<string, string[]>;
}

/** One selectable provider. */
export interface ProviderEntry {
  name: string;
  requires_key: boolean;
  free_text_model: boolean;
}

/** A decision on one approval. A misspelled field must not be read as a denial. */
export interface ResolveApprovalRequest {
  approved: boolean;
}

/** How much damage a tool call can do. Policy is a *set* of levels, never a threshold. */
export type RiskLevel = "low" | "medium" | "high";

/** A row of the `runs` table (§4). */
export interface Run {
  id: string;
  space_id: string;
  goal: string;
  status: "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";
  origin: "ui" | "discord";
  origin_ref?: string | null;
  created_at: string;
  finished_at?: string | null;
}

/** Workspace settings plus the read-only facts the UI needs beside them. */
export interface SettingsResponse {
  settings: WorkspaceSettings;
  configured_secrets: string[];
  known_secrets: string[];
  supported_providers: string[];
  model_is_priced: boolean;
}

/** A space, plus where its runs read and write. */
export interface SpaceResponse {
  id: string;
  name: string;
  description?: string;
  provider?: string | null;
  model?: string | null;
  auto_approve?: RiskLevel[] | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  archived?: boolean;
  created_at: string;
  updated_at: string;
  folder: string;
  is_default: boolean;
}

/** One catalogue entry, as the agent editor renders it. */
export interface ToolResponse {
  name: string;
  description: string;
  risk: string;
  available: boolean;
}

/**
 * A partial update. Every field optional; omitted fields are untouched.
 *
 * ``None`` is meaningful for `provider` and `model` (back to inheriting), so
 * `model_fields_set` separates "sent as null" from "not sent".
 */
export interface UpdateAgentRequest {
  space_id?: string | null;
  name?: string | null;
  role?: string | null;
  system_prompt?: string | null;
  provider?: string | null;
  model?: string | null;
  allowed_tools?: string[] | null;
  max_steps?: number | null;
  auto_approve?: string[] | null;
  enabled?: boolean | null;
}

/**
 * A partial update. Every field optional; omitted fields are untouched.
 *
 * Unknown fields are rejected, not dropped: Pydantic's default turns a
 * misspelled setting into a `200 OK` that changed nothing. This model must
 * list every field of :class:`~agentspace.store.settings.WorkspaceSettings`
 * (they differ in bounds and optionality, so it cannot be the same class),
 * and `test_every_workspace_setting_can_be_patched` keeps the two in step.
 */
export interface UpdateSettingsRequest {
  provider?: string | null;
  model?: string | null;
  monthly_cap_micros?: number | null;
  ollama_base_url?: string | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  auto_approve?: RiskLevel[] | null;
  discord_enabled?: boolean | null;
  channel_identities?: ChannelIdentity[] | null;
  channel_approvals?: "dashboard_only" | "originator" | null;
  channel_space_id?: string | null;
}

/** A partial update. ``None`` means "inherit", so `model_fields_set` tells it from "not sent". */
export interface UpdateSpaceRequest {
  name?: string | null;
  description?: string | null;
  provider?: string | null;
  model?: string | null;
  auto_approve?: RiskLevel[] | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  archived?: boolean | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/** Whether the current settings can build a provider, and why not if not. */
export interface VerifyResponse {
  ok: boolean;
  reason?: string | null;
  provider?: string | null;
  model?: string | null;
}

/** Everything the user can configure that is not a secret. */
export interface WorkspaceSettings {
  provider?: string;
  model?: string;
  monthly_cap_micros?: number;
  ollama_base_url?: string;
  auto_approve?: RiskLevel[];
  max_steps_per_agent?: number;
  max_agents_per_run?: number;
  max_run_seconds?: number;
  discord_enabled?: boolean;
  channel_identities?: ChannelIdentity[];
  channel_approvals?: "dashboard_only" | "originator";
  channel_space_id?: string | null;
}
