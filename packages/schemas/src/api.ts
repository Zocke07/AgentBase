/**
 * Generated from the sidecar's OpenAPI schema. Do not edit.
 *
 * Regenerate with `just schemas`; `test_openapi_snapshot.py` fails if this
 * file drifts from the FastAPI app. A field is optional here exactly when the
 * schema does not list it as required.
 */


/**
 * When the run of another schedule in the same space completes.
 *
 * A stage in a chain: the collection runs at its time, the analysis after it.
 * A failed or cancelled run stops the chain there.
 */
export interface AfterCadence {
  kind: "after";
  schedule_id: string;
}

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

/** One agent a provider switch would leave on the old provider's model. */
export interface AgentMove {
  id: string;
  name: string;
  provider: string | null;
  model: string | null;
  to_model: string | null;
}

export interface AlertsResponse {
  alerts: MarketAlert[];
  unseen: number;
}

/** Approval data rendered by the dialog. */
export interface ApprovalResponse {
  id: string;
  run_id: string;
  tool: string;
  args: Record<string, unknown>;
  risk: string;
  status: string;
  created_at: string;
  resolved_at?: string | null;
  scope?: "call" | "run";
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

/** Allowlist entry mapping one channel user to one identity. */
export interface ChannelIdentity {
  channel: "discord";
  external_user_id: string;
  identity: string;
}

/** Adapter status rendered by the settings screen. */
export interface ChannelStatusResponse {
  channel: string;
  enabled: boolean;
  configured: boolean;
  running: boolean;
  failures: number;
  last_error?: string | null;
  refused?: string[];
}

export interface ChatGPTAuthResponse {
  state: "connected" | "connecting" | "preparing" | "disconnected" | "error";
  email?: string | null;
  plan?: string | null;
  error?: string | null;
  runtime?: ChatGPTRuntimeResponse | null;
}

export interface ChatGPTLoginResponse {
  login_id: string;
  auth_url: string;
}

/** App Server runtime state: missing, downloading, ready, or failed. */
export interface ChatGPTRuntimeResponse {
  state: "ready" | "missing" | "downloading" | "error";
  version: string;
  downloaded_bytes?: number;
  total_bytes?: number;
  error?: string | null;
}

/** Copy destination. Copies get a new ID and are never built-ins. */
export interface CopyAgentRequest {
  space_id: string;
}

/** Seed a new space with another space's roster copies. */
export interface CopyFrom {
  copy_from: string;
}

/** New definition; callers cannot mint a built-in :class:`AgentDef`. */
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
  origin?: "ui" | "discord" | "schedule" | "automation" | "monitor";
  origin_ref?: string | null;
  excluded_citations?: string[];
  supervised?: boolean;
}

export interface CreateScheduleRequest {
  space_id: string;
  name: string;
  goal: string;
  cadence: DailyCadence | WeeklyCadence | IntervalCadence | AfterCadence;
  missed?: "run_on_launch" | "skip";
  enabled?: boolean;
  max_run_seconds?: number | null;
}

export interface CreateSpaceRequest {
  name: string;
  description?: string;
  provider?: string | null;
  model?: string | null;
  seed?: "empty" | "builtins" | CopyFrom;
}

/** Every day at a local time of day. */
export interface DailyCadence {
  kind: "daily";
  at: string;
}

export interface EvaluateKnowledgeRequest {
  cases: KnowledgeEvaluationCase[];
  limit?: number;
}

/**
 * Append-only log row.
 *
 * ``seq`` is a 1-based per-run SSE/``Last-Event-ID`` cursor; global rowid
 * ``id`` is never a resume cursor.
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

/** Every event this application emits; list matches §4 verbatim. */
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

/** `/health` response; the shell polls it for sidecar readiness. */
export interface HealthResponse {
  ok: boolean;
  instance: string | null;
}

export interface ImportKnowledgeRequest {
  files: ImportNote[];
  overwrite?: boolean;
}

export interface ImportNote {
  path: string;
  content: string;
}

/** Every so many hours, counted from the last time it was due. */
export interface IntervalCadence {
  kind: "interval";
  every_hours: number;
}

export interface KnowledgeEdge {
  source: string;
  target: string;
}

export interface KnowledgeEvaluation {
  results: KnowledgeEvaluationResult[];
  mean_reciprocal_rank: number;
  mean_recall_at_k: number;
  limit: number;
}

export interface KnowledgeEvaluationCase {
  question: string;
  expected_paths: string[];
}

export interface KnowledgeEvaluationResult {
  question: string;
  expected_paths: string[];
  retrieved_paths: string[];
  reciprocal_rank: number;
  recall_at_k: number;
}

/** What deleting a folder removed, and where a copy went first. */
export interface KnowledgeFolderDeleteResult {
  path: string;
  deleted_files: number;
  backup_path: string;
}

export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

export interface KnowledgeImportResult {
  created: number;
  updated: number;
  skipped: number;
  backup_path: string | null;
}

export interface KnowledgeIndex {
  notes: NoteSummary[];
  stats: KnowledgeStats;
  index_status: KnowledgeIndexStatus;
}

/** What the incremental vault refresh did for this response. */
export interface KnowledgeIndexStatus {
  indexed_at: string;
  scanned_files: number;
  changed_files: number;
  reused_files: number;
  truncated: boolean;
  duration_ms: number;
}

export interface KnowledgeMoveResult {
  note: KnowledgeNote;
  updated_links: number;
  backup_path: string;
}

export interface KnowledgeNode {
  path: string;
  title: string;
  tags?: string[];
}

/** A note plus its editable Markdown source. */
export interface KnowledgeNote {
  path: string;
  title: string;
  excerpt: string;
  tags?: string[];
  properties?: Record<string, string>;
  links?: string[];
  backlinks?: string[];
  unresolved_links?: string[];
  pinned?: boolean;
  updated_at: string;
  content: string;
}

export interface KnowledgeSearch {
  query: string;
  hits: SearchHit[];
  duration_ms?: number;
  total_chunks?: number;
  retrieval_mode?: string;
}

export interface KnowledgeStats {
  note_count: number;
  link_count: number;
  tag_count: number;
  chunk_count: number;
  orphan_count?: number;
  unresolved_link_count?: number;
}

export interface MarketAlert {
  id: string;
  space_id: string;
  batch_id: string;
  symbol: string;
  name: string | null;
  instrument: "stock" | "index";
  kind: "move" | "jump";
  direction: "up" | "down";
  change_pct: number;
  level_pct: number;
  price: number;
  reference_price: number;
  reference: "previous_close" | "regular_close" | "window";
  window_minutes: number | null;
  session: "pre" | "regular" | "post";
  market_date: string;
  quoted_at: string;
  created_at: string;
  explanation_status: "queued" | "running" | "done" | "failed" | "skipped" | "off";
  explanation_run_id: string | null;
  explanation_path: string | null;
  explanation: string | null;
  seen_at: string | null;
}

export interface MemoryIndex {
  items: MemoryItem[];
  proposed: number;
  approved: number;
  archived: number;
}

/** A run outcome waiting for, or carrying, a user's trust decision. */
export interface MemoryItem {
  path: string;
  run_id: string | null;
  source: string;
  title: string;
  goal: string;
  outcome: string;
  status: MemoryStatus;
  pinned: boolean;
  confidence: string;
  tags?: string[];
  citations?: string[];
  merged_from?: string[];
  merged_into?: string | null;
  managed_at?: string | null;
  management_model?: string | null;
  management_action?: string | null;
  management_reason?: string | null;
  management_backup?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryMergeResult {
  memory: MemoryItem;
  archived_paths: string[];
  backup_path: string;
}

/** Trust state for an agent-generated memory. */
export type MemoryStatus = "proposed" | "approved" | "archived";

export interface MergeMemoriesRequest {
  paths: string[];
  title?: string | null;
}

/** One selectable model: where it sits in the lineup and what it costs. */
export interface ModelEntry {
  id: string;
  tier: "frontier" | "strong" | "balanced" | "fast";
  current: boolean;
  input_micros_per_million: number;
  output_micros_per_million: number;
  available?: boolean | null;
}

/** What the window shows about one space's watch. */
export interface MonitorStatus {
  enabled: boolean;
  error?: string | null;
  symbols?: string[];
  check_every_minutes?: number;
  market_open?: boolean;
  last_checked_at?: string | null;
  next_check_at?: string | null;
  problems?: string[];
  explain?: boolean;
  explanations_today?: number;
  max_explanations_per_day?: number;
  stock_move_pct?: number;
  stock_jump_pct?: number;
  index_move_pct?: number;
  index_jump_pct?: number;
  jump_window_minutes?: number;
}

export interface MonitorSwitchRequest {
  enabled: boolean;
}

export interface MoveNoteRequest {
  source: string;
  target: string;
  update_links?: boolean;
}

/** What the note browser needs without opening the full document. */
export interface NoteSummary {
  path: string;
  title: string;
  excerpt: string;
  tags?: string[];
  properties?: Record<string, string>;
  links?: string[];
  backlinks?: string[];
  unresolved_links?: string[];
  pinned?: boolean;
  updated_at: string;
}

export interface PersonalPortfolio {
  currency: string;
  cash: string;
  holdings: PortfolioHolding[];
  watchlist: PortfolioStock[];
  limits: PortfolioLimits;
}

export interface PinNoteRequest {
  path: string;
  pinned: boolean;
}

export interface PortfolioHolding {
  ticker: string;
  sector: string;
  company_name?: string;
  industry?: string;
  exchange?: string;
  shares: string;
  cost_per_share?: string | null;
  opened?: string | null;
}

export interface PortfolioLimits {
  max_position_pct: string;
  max_sector_pct: string;
  max_daily_loss_pct: string;
}

export interface PortfolioResponse {
  portfolio: PersonalPortfolio;
  revision: string;
}

export interface PortfolioStock {
  ticker: string;
  sector: string;
  company_name?: string;
  industry?: string;
  exchange?: string;
}

/** The newest valuation, for Home's portfolio card. Read-only. */
export interface PortfolioValuation {
  as_of: string;
  currency: string;
  total_value: number;
  day_change: number;
  day_change_pct: number | null;
  positions_date?: string | null;
  since_previous?: SinceReport | null;
}

export interface PreviewRequest {
  cadence: DailyCadence | WeeklyCadence | IntervalCadence | AfterCadence;
}

/** Selectable and priced models by provider. */
export interface ProviderCatalogueResponse {
  providers: ProviderEntry[];
  models: Record<string, string[]>;
  catalog: Record<string, ModelEntry[]>;
}

/** Selectable provider. */
export interface ProviderEntry {
  name: string;
  requires_key: boolean;
  free_text_model: boolean;
  default_model?: string | null;
}

/** What moving a space to ``provider`` would change, before it is saved. */
export interface ProviderSwitchPlan {
  provider: string;
  model: string | null;
  agents: AgentMove[];
}

/** Decision on one approval; reject misspelled fields rather than deny. */
export interface ResolveApprovalRequest {
  approved: boolean;
  scope?: "call" | "run";
}

/** Potential damage from a tool call; policy uses a set, not a threshold. */
export type RiskLevel = "low" | "medium" | "high";

/** ``runs`` table row (§4). */
export interface Run {
  id: string;
  space_id: string;
  goal: string;
  status: "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";
  origin: "ui" | "discord" | "schedule" | "automation" | "monitor";
  origin_ref?: string | null;
  title?: string | null;
  created_at: string;
  finished_at?: string | null;
}

export interface SavePortfolioRequest {
  portfolio: PersonalPortfolio;
  revision: string;
}

/** Cadence preview before saving. */
export interface SchedulePreview {
  summary: string;
  next: string[];
}

/** Schedule plus a shared human-readable cadence. */
export interface ScheduleResponse {
  id: string;
  space_id: string;
  name: string;
  goal: string;
  cadence: DailyCadence | WeeklyCadence | IntervalCadence | AfterCadence;
  missed?: "run_on_launch" | "skip";
  enabled?: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_run_id?: string | null;
  last_outcome?: string | null;
  max_run_seconds?: number | null;
  created_at: string;
  updated_at: string;
  summary: string;
}

/** Optional narrowing shared by the UI, evaluations and agent tool. */
export interface SearchFilters {
  folders?: string[];
  tags?: string[];
  note_types?: string[];
  memory_statuses?: MemoryStatus[];
  pinned_only?: boolean;
  updated_after?: string | null;
  updated_before?: string | null;
}

export interface SearchHit {
  path: string;
  title: string;
  heading: string | null;
  excerpt: string;
  citation: string;
  score: number;
  tags?: string[];
  matched_terms?: string[];
  reasons?: string[];
  estimated_tokens?: number;
}

export interface SearchKnowledgeRequest {
  query: string;
  limit?: number;
  filters?: SearchFilters;
}

export interface SeenRequest {
  space_id?: string | null;
}

export interface SeenResponse {
  marked: number;
}

/** Workspace settings plus UI read-only facts. */
export interface SettingsResponse {
  settings: WorkspaceSettings;
  configured_secrets: string[];
  known_secrets: string[];
  supported_providers: string[];
  model_is_priced: boolean;
  version: string;
  data_dir: string;
}

/** What changed since the report before, as compute_portfolio recorded it. */
export interface SinceReport {
  session: string;
  skipped_sessions: string[];
  total_value: number;
  value_change: number;
  value_change_pct: number | null;
  price_change_pct: Record<string, number | null>;
}

/** Space and its run read/write location. */
export interface SpaceResponse {
  id: string;
  name: string;
  description?: string;
  provider?: string | null;
  model?: string | null;
  auto_approve?: RiskLevel[] | null;
  tool_policies?: Record<string, ToolPolicy> | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  max_run_cost_micros?: number | null;
  archived?: boolean;
  created_at: string;
  updated_at: string;
  folder: string;
  is_default: boolean;
}

export interface TextFile {
  path: string;
  size: number;
  updated_at: string;
  content: string;
}

export interface TextFileIndex {
  files: TextFileSummary[];
}

/** A plain-text file in the space folder, as the tree lists it. */
export interface TextFileSummary {
  path: string;
  size: number;
  updated_at: string;
}

/**
 * Per-tool gate decision before risk-level policy.
 *
 * Absent tools default to ``ASK``; ``ALLOW`` bypasses the prompt and ``DENY``
 * refuses the call.
 */
export type ToolPolicy = "ask" | "allow" | "deny";

/** Catalogue entry rendered by the agent editor. */
export interface ToolResponse {
  name: string;
  description: string;
  risk: string;
  available: boolean;
}

/**
 * Partial update; omitted fields stay unchanged.
 *
 * ``None`` restores provider/model inheritance, so ``model_fields_set``
 * distinguishes it from an omitted field.
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

export interface UpdateMemoryRequest {
  path: string;
  status?: MemoryStatus | null;
  pinned?: boolean | null;
}

/** Partial update; omitted fields remain unchanged. */
export interface UpdateScheduleRequest {
  name?: string | null;
  goal?: string | null;
  cadence?: DailyCadence | WeeklyCadence | IntervalCadence | AfterCadence | null;
  missed?: "run_on_launch" | "skip" | null;
  enabled?: boolean | null;
  max_run_seconds?: number | null;
}

/**
 * Partial update; omitted fields stay unchanged.
 *
 * Reject unknown fields: Pydantic would otherwise return ``200 OK`` for a
 * misspelling. Mirror every :class:`~agentbase.store.settings.WorkspaceSettings`
 * field here; bounds and optionality differ, and the paired test detects drift.
 */
export interface UpdateSettingsRequest {
  provider?: string | null;
  model?: string | null;
  openai_access?: "api_key" | "chatgpt" | null;
  monthly_cap_micros?: number | null;
  ollama_base_url?: string | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  max_run_cost_micros?: number | null;
  unattended_question_seconds?: number | null;
  memory_management?: "automatic" | "review" | "off" | null;
  auto_approve?: RiskLevel[] | null;
  tool_policies?: Record<string, ToolPolicy> | null;
  auto_approve_hosts?: string[] | null;
  discord_enabled?: boolean | null;
  channel_identities?: ChannelIdentity[] | null;
  channel_approvals?: "dashboard_only" | "originator" | null;
  channel_space_id?: string | null;
  discord_alert_channel_id?: string | null;
  alert_desktop_notifications?: boolean | null;
  onboarding_completed?: boolean | null;
}

/**
 * Partial update; ``None`` inherits, so ``model_fields_set`` detects sent null.
 *
 * The provider cannot be cleared: a space names its own.
 */
export interface UpdateSpaceRequest {
  name?: string | null;
  description?: string | null;
  provider?: string | null;
  model?: string | null;
  auto_approve?: RiskLevel[] | null;
  tool_policies?: Record<string, ToolPolicy> | null;
  max_steps_per_agent?: number | null;
  max_agents_per_run?: number | null;
  max_run_seconds?: number | null;
  max_run_cost_micros?: number | null;
  archived?: boolean | null;
}

/** Period slice by model, space, or day. */
export interface UsageBucket {
  key: string;
  label: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_micros: number;
  cost_display: string;
}

export interface UsageReport {
  period: string;
  periods: string[];
  space_id: string | null;
  cap_micros: number;
  totals: UsageTotals;
  by_model: UsageBucket[];
  by_space: UsageBucket[];
  by_day: UsageBucket[];
  runs: UsageRun[];
}

export interface UsageRun {
  run_id: string | null;
  space_id: string | null;
  goal: string | null;
  status: string | null;
  origin: string | null;
  created_at: string | null;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  peak_context: number;
  mean_context: number;
  cost_micros: number;
  cost_display: string;
}

export interface UsageTotals {
  calls: number;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cost_micros: number;
  cost_display: string;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/** Whether current settings can build a provider, with a failure reason. */
export interface VerifyResponse {
  ok: boolean;
  reason?: string | null;
  provider?: string | null;
  model?: string | null;
  suggested_model?: string | null;
}

/** On chosen weekdays at a local time of day. */
export interface WeeklyCadence {
  kind: "weekly";
  at: string;
  weekdays: number[];
}

/** Everything the user can configure that is not a secret. */
export interface WorkspaceSettings {
  provider?: string;
  model?: string;
  openai_access?: "api_key" | "chatgpt";
  monthly_cap_micros?: number;
  ollama_base_url?: string;
  auto_approve?: RiskLevel[];
  tool_policies?: Record<string, ToolPolicy>;
  auto_approve_hosts?: string[];
  max_steps_per_agent?: number;
  max_agents_per_run?: number;
  max_run_seconds?: number;
  max_run_cost_micros?: number;
  unattended_question_seconds?: number;
  memory_management?: "automatic" | "review" | "off";
  discord_enabled?: boolean;
  channel_identities?: ChannelIdentity[];
  channel_approvals?: "dashboard_only" | "originator";
  channel_space_id?: string | null;
  discord_alert_channel_id?: string | null;
  alert_desktop_notifications?: boolean;
  onboarding_completed?: boolean;
}

export interface WriteFileRequest {
  path: string;
  content: string;
  create?: boolean;
}

export interface WriteNoteRequest {
  path: string;
  content: string;
  create?: boolean;
}
