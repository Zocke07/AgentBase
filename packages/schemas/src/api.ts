/**
 * Generated from the sidecar's OpenAPI schema. Do not edit.
 *
 * Regenerate with `just schemas`. BUILD_SPEC §5 Phase 7 requires the API types
 * to be generated rather than hand-written, and
 * `test_openapi_snapshot.py` fails if this file drifts from the FastAPI app.
 *
 * A field is optional here exactly when the schema does not list it as
 * required, which for a response model means it has a default. That is the
 * schema's reading rather than a judgement about what the server sends, because
 * a generator that second-guessed its input would be a second source of truth.
 */


/**
 * One row of `agent_defs` (§4).
 *
 * Frozen: a definition handed to a run is a snapshot of what that run started
 * with, and a snapshot that can be mutated in place is not one. See
 * :mod:`agentspace.orchestrator.registry`.
 */
export interface AgentDef {
  id: string;
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
}

/**
 * A new definition.
 *
 * Deliberately not the same model as :class:`~agentspace.store.agents.AgentDef`:
 * `id`, `created_at`, `updated_at` and `is_builtin` are ours to assign, and a
 * request model that accepted them would let a caller mint a built-in — which
 * is a definition the delete path refuses to remove.
 */
export interface CreateAgentRequest {
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
  origin?: "ui" | "discord" | "telegram";
  origin_ref?: string | null;
}

/**
 * One append-only row of the log.
 *
 * ``seq`` is per-run and 1-based; it is the id the SSE stream publishes and
 * the cursor ``Last-Event-ID`` carries. ``id`` is the global rowid and exists
 * for ordering across runs — never use it as a resume cursor, since a client
 * resuming one run would then skip every event another run interleaved.
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

/**
 * A decision on one approval.
 *
 * ``extra="forbid"`` for the reason every request model in this project has
 * it: Pydantic's default is to drop an unknown field, which turned a
 * misspelled setting into a `200 OK` that changed nothing once already
 * (CLAUDE.md, Phase 4). Here the stakes are higher — a client that sent
 * ``{"approve": true}`` would have the typo silently read as a denial.
 */
export interface ResolveApprovalRequest {
  approved: boolean;
}

/**
 * How much damage a tool call can do. §5 Phase 6's three levels.
 *
 * The ordering is meaningful to a reader and deliberately not encoded as
 * comparison: "at most medium" is not a policy this project expresses, because
 * `http_get` and `write_file` are both medium and permitting one is not a
 * reason to permit the other. Policy is a *set* of levels, never a threshold.
 */
export type RiskLevel = "low" | "medium" | "high";

/** A row of the `runs` table (§4). */
export interface Run {
  id: string;
  goal: string;
  status: "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";
  origin: "ui" | "discord" | "telegram";
  origin_ref?: string | null;
  created_at: string;
  finished_at?: string | null;
}

/** Workspace settings plus the read-only facts the UI needs beside them. */
export interface SettingsResponse {
  settings: WorkspaceSettings;
  configured_secrets: string[];
  supported_providers: string[];
  model_is_priced: boolean;
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
 * ``None`` is meaningful for `provider` and `model` — it is how a definition
 * goes back to inheriting the workspace default — so this cannot use
 * `exclude_none` the way `PATCH /settings` does. `model_fields_set` is what
 * separates "sent as null" from "not sent".
 */
export interface UpdateAgentRequest {
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
 * **Unknown fields are rejected rather than ignored.** Pydantic's default is
 * to drop them, which turns a misspelled or not-yet-supported setting into a
 * `200 OK` that changed nothing — the caller is told it worked and it did
 * not. That is exactly how the Phase 4 run limits appeared configurable
 * through this endpoint for a while without being so.
 *
 * **This model must list every field of
 * :class:`~agentspace.store.settings.WorkspaceSettings`.** It duplicates that
 * list because the two differ in bounds and optionality, and a duplicated
 * list is a list that drifts: Phase 6 added `auto_approve` to the settings
 * model and not to this one, so `GET /settings` reported a policy that
 * `PATCH /settings` refused to set — the workspace's entire approval policy
 * was unsettable through the API. `extra="forbid"` made that loud rather than
 * silent, which is the Phase 4 fix working, and
 * `test_every_workspace_setting_can_be_patched` is what stops the next field
 * repeating it.
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
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
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
}
