import type { Event, EventType } from "@agentbase/schemas";

import { flag, int, record, records, strings, text, type Payload } from "../lib/payload";

/**
 * Run reducer: the UI half of BUILD_SPEC §2 and sole source of run rendering.
 *
 * It is pure, clock-free, and shared by live/replay. Keep claimed work (`claim`)
 * separate from actual calls (`toolCalls`): completed agents have claimed work
 * absent from the log.
 */

/**
 * Current agent activity according to the log. Each emitted event leaves an
 * agent in exactly one state.
 */
export type Activity = "spawned" | "thinking" | "calling" | "waiting" | "executing" | "completed";

export interface AgentNode {
  readonly name: string;
  readonly role: string | null;
  readonly definitionId: string | null;
  readonly definitionName: string | null;
  readonly systemPrompt: string | null;
  readonly provider: string | null;
  readonly model: string | null;
  readonly allowedTools: readonly string[];
  readonly autoApprove: readonly string[];
  readonly maxSteps: number | null;
  readonly activity: Activity;
  /** Tool executing under `"executing"`; null otherwise. */
  readonly currentTool: string | null;
  /** Unmoved-past `llm.error` or `tool.error` message. */
  readonly lastError: string | null;
  readonly steps: number;
  readonly finishedReason: string | null;
  /** Current model-call streamed output; reset by `llm.request`. */
  readonly streamedText: string;
  readonly lastMessage: string | null;
  /** First appearance; graph node sort order. */
  readonly seq: number;
  /** Agent model calls, summed from `llm.response`. */
  readonly calls: number;
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly costMicros: number;
  /**
   * Latest and maximum input tokens: current and peak carried context.
   */
  readonly lastContext: number | null;
  readonly peakContext: number;
}

export interface Handoff {
  readonly from: string;
  readonly to: string;
  readonly task: string;
  readonly seq: number;
}

export type ApprovalStatus = "pending" | "approved" | "denied" | "expired";

export interface ApprovalRecord {
  readonly id: string;
  readonly agent: string;
  readonly tool: string;
  readonly risk: string;
  /** Backend-rendered sentence; never compose it here (§2). */
  readonly prompt: string;
  readonly status: ApprovalStatus;
  readonly automatic: boolean;
  /** Automatic answer based on this person's earlier in-run answer. */
  readonly precedent: boolean;
  /** Automatic answer from app-wide or space policy for this named tool. */
  readonly policy: boolean;
  /**
   * Which rule answered an automatic yes: `"level"` (the risk level is
   * pre-approved) or `"tool"` (the tool is always allowed); null otherwise.
   */
  readonly rule: "level" | "tool" | null;
  /** The listed host a network call reached on the policy's word. */
  readonly host: string | null;
  /** Person's yes scope: this call or remaining run tool calls. */
  readonly scope: "call" | "run";
  readonly seq: number;
}

export interface ToolCall {
  readonly agent: string;
  readonly tool: string;
  readonly args: Payload;
  readonly callId: string | null;
  readonly result: string | null;
  readonly seq: number;
}

export interface Denial {
  readonly agent: string;
  readonly tool: string;
  readonly reason: string;
  /**
   * Refusal boundary: `"sandbox"` for out-of-bounds calls without a prompt;
   * `null` for allowlist or person refusals.
   */
  readonly blockedBy: string | null;
  readonly seq: number;
}

export interface RunError {
  readonly agent: string | null;
  readonly kind: "llm" | "tool";
  readonly message: string;
  readonly seq: number;
}

/**
 * The approval policy a run acted under, as `run.started` recorded it. With
 * nobody answering calls one by one, this is why a call ran without asking.
 * Older runs recorded none, so it is null for them.
 */
export interface RunApprovalPolicy {
  /** Risk levels answered yes by policy. */
  readonly levels: readonly string[];
  /** Tools always allowed, and tools never allowed. */
  readonly allowTools: readonly string[];
  readonly denyTools: readonly string[];
  /** Hosts a network call may reach without asking; `*` is any. */
  readonly hosts: readonly string[];
  /** How long a question waited before expiring; null waits out the run. */
  readonly questionSeconds: number | null;
  /** Stepped through: every call asked. */
  readonly supervised: boolean;
  readonly origin: string | null;
}

/** One vault excerpt the supervisor received, as `run.started` recorded it. */
export interface RetrievedExcerpt {
  readonly citation: string;
  readonly path: string | null;
  readonly heading: string | null;
  readonly score: number | null;
  readonly matchedTerms: readonly string[];
  readonly reasons: readonly string[];
  readonly estimatedTokens: number | null;
}

export interface Budget {
  readonly spentMicros: number;
  readonly capMicros: number;
  readonly percent: number;
}

/** Terminal event's asserted run account, not a fact. */
export interface RunClaim {
  readonly kind: "summary" | "reason";
  readonly text: string;
}

/**
 * Non-window run origin. `identity` is the resolved internal name; show the
 * sender-controlled `displayName` beside, never instead of, it.
 */
export interface RunOrigin {
  readonly channel: string;
  readonly identity: string | null;
  readonly displayName: string | null;
  readonly threadRef: string | null;
  readonly trigger: string | null;
}

export type RunStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface RunView {
  readonly runId: string | null;
  readonly goal: string | null;
  /** Present only for chat-channel runs. */
  readonly origin: RunOrigin | null;
  readonly limits: Payload | null;
  readonly approvalPolicy: RunApprovalPolicy | null;
  /** Goal excerpts and user-removed citations. */
  readonly knowledge: readonly RetrievedExcerpt[];
  readonly knowledgeExclusions: readonly string[];
  /** Proposed-memory note containing the outcome, if written. */
  readonly memoryPath: string | null;
  readonly status: RunStatus;
  readonly claim: RunClaim | null;
  readonly agents: Readonly<Record<string, AgentNode>>;
  readonly agentOrder: readonly string[];
  readonly handoffs: readonly Handoff[];
  readonly approvals: readonly ApprovalRecord[];
  readonly requested: readonly ToolCall[];
  readonly toolCalls: readonly ToolCall[];
  readonly denials: readonly Denial[];
  readonly errors: readonly RunError[];
  readonly inputTokens: number;
  readonly outputTokens: number;
  /** Ledger total for model calls, summed from `llm.response`. */
  readonly costMicros: number;
  readonly budget: Budget | null;
  readonly budgetExceeded: boolean;
  readonly lastSeq: number;
  readonly eventCount: number;
  /** `run.started` timestamp and latest event timestamp; never a clock. */
  readonly startedTs: string | null;
  readonly latestTs: string | null;
  /** Unknown build event types, rendered rather than swallowed. */
  readonly unrecognised: readonly string[];
}

export const EMPTY_RUN: RunView = {
  runId: null,
  goal: null,
  origin: null,
  limits: null,
  approvalPolicy: null,
  knowledge: [],
  knowledgeExclusions: [],
  memoryPath: null,
  status: "pending",
  claim: null,
  agents: {},
  agentOrder: [],
  handoffs: [],
  approvals: [],
  requested: [],
  toolCalls: [],
  denials: [],
  errors: [],
  inputTokens: 0,
  outputTokens: 0,
  costMicros: 0,
  budget: null,
  budgetExceeded: false,
  lastSeq: 0,
  eventCount: 0,
  startedTs: null,
  latestTs: null,
  unrecognised: [],
};

// --- agent helpers ----------------------------------------------------------

const newAgent = (name: string, seq: number): AgentNode => ({
  name,
  role: null,
  definitionId: null,
  definitionName: null,
  systemPrompt: null,
  provider: null,
  model: null,
  allowedTools: [],
  autoApprove: [],
  maxSteps: null,
  activity: "spawned",
  currentTool: null,
  lastError: null,
  steps: 0,
  finishedReason: null,
  streamedText: "",
  lastMessage: null,
  seq,
  calls: 0,
  inputTokens: 0,
  outputTokens: 0,
  costMicros: 0,
  lastContext: null,
  peakContext: 0,
});

/**
 * Create unseen `name` nodes for each `agent_id` event so resumed streams retain
 * agents spawned before resumption.
 */
function ensureAgent(state: RunView, name: string, seq: number): RunView {
  if (state.agents[name] !== undefined) return state;

  return {
    ...state,
    agents: { ...state.agents, [name]: newAgent(name, seq) },
    agentOrder: [...state.agentOrder, name],
  };
}

/** Apply `change` to one agent node without altering other state. */
function withAgent(
  state: RunView,
  name: string,
  seq: number,
  change: (agent: AgentNode) => AgentNode,
): RunView {
  const base = state.agents[name] ?? newAgent(name, seq);

  return {
    ...ensureAgent(state, name, seq),
    agents: { ...state.agents, [name]: change(base) },
  };
}

// --- the fold ---------------------------------------------------------------

/** Apply one event immutably. */
export function reduce(state: RunView, event: Event): RunView {
  const payload = event.payload ?? {};
  const agent = event.agent_id ?? null;
  const seq = event.seq;

  const counted: RunView = {
    ...state,
    runId: state.runId ?? event.run_id,
    lastSeq: Math.max(state.lastSeq, seq),
    eventCount: state.eventCount + 1,
    // First resumed event substitutes for unseen `run.started`.
    startedTs: state.startedTs ?? event.ts,
    latestTs: event.ts,
  };

  // Single agent-registration point.
  const next = agent === null ? counted : ensureAgent(counted, agent, seq);

  switch (event.type) {
    // --- the run ------------------------------------------------------------

    case "run.started":
      return {
        ...next,
        goal: text(payload, "goal"),
        limits: record(payload, "limits"),
        approvalPolicy: approvalPolicyOf(payload),
        knowledge: records(payload, "knowledge").map(excerptOf),
        knowledgeExclusions: strings(payload, "knowledge_exclusions"),
        status: "running",
      };

    case "run.completed":
      return {
        ...next,
        status: "completed",
        claim: claimOf("summary", payload),
        memoryPath: text(payload, "memory_path"),
      };

    case "run.failed":
      return { ...next, status: "failed", claim: claimOf("reason", payload) };

    case "run.paused":
      return { ...next, status: "paused" };

    case "run.cancelled":
      return { ...next, status: "cancelled", claim: claimOf("reason", payload) };

    // --- agents -------------------------------------------------------------

    case "agent.spawned":
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        role: text(payload, "role") ?? node.role,
        definitionId: text(payload, "definition_id") ?? node.definitionId,
        definitionName: text(payload, "definition_name") ?? node.definitionName,
        systemPrompt: text(payload, "system_prompt") ?? node.systemPrompt,
        provider: text(payload, "provider") ?? node.provider,
        model: text(payload, "model") ?? node.model,
        allowedTools: strings(payload, "allowed_tools"),
        autoApprove: strings(payload, "auto_approve"),
        maxSteps: int(payload, "max_steps") ?? node.maxSteps,
        activity: "spawned",
      }));

    case "agent.thinking":
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        activity: "thinking",
        steps: Math.max(node.steps, int(payload, "step") ?? 0),
      }));

    case "agent.message":
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        lastMessage: text(payload, "text") ?? node.lastMessage,
      }));

    case "agent.handoff": {
      if (agent === null) return next;
      const to = text(payload, "to");
      if (to === null) return next;
      return {
        ...next,
        handoffs: [...next.handoffs, { from: agent, to, task: text(payload, "task") ?? "", seq }],
      };
    }

    case "agent.completed":
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        activity: "completed",
        finishedReason: text(payload, "reason") ?? node.finishedReason,
        steps: Math.max(node.steps, int(payload, "steps") ?? 0),
      }));

    // --- the model ----------------------------------------------------------

    case "llm.request":
      if (agent === null) return next;
      // New call resets prior streamed text.
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        activity: "calling",
        streamedText: "",
        lastError: null,
      }));

    case "llm.token":
      // Streaming no text does not make the agent idle.
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        streamedText: node.streamedText + (text(payload, "text") ?? ""),
      }));

    case "llm.response": {
      const input = int(payload, "input_tokens") ?? 0;
      const output = int(payload, "output_tokens") ?? 0;
      const cost = int(payload, "cost_micros") ?? 0;
      const totalled: RunView = {
        ...next,
        inputTokens: next.inputTokens + input,
        outputTokens: next.outputTokens + output,
        costMicros: next.costMicros + cost,
      };
      return agent === null
        ? totalled
        : withAgent(totalled, agent, seq, (node) => ({
            ...thinkingAgain(node),
            calls: node.calls + 1,
            inputTokens: node.inputTokens + input,
            outputTokens: node.outputTokens + output,
            costMicros: node.costMicros + cost,
            lastContext: input,
            peakContext: Math.max(node.peakContext, input),
          }));
    }

    case "llm.error": {
      const message = text(payload, "error") ?? "";
      const recorded: RunView = {
        ...next,
        errors: [...next.errors, { agent, kind: "llm", message, seq }],
      };
      return agent === null
        ? recorded
        : withAgent(recorded, agent, seq, (node) => ({ ...thinkingAgain(node), lastError: message }));
    }

    // --- tools --------------------------------------------------------------

    case "tool.requested":
      return { ...next, requested: [...next.requested, toolCallOf(agent, payload, seq)] };

    case "tool.approved":
      return { ...next, approvals: settle(next.approvals, payload, "approved") };

    case "tool.denied": {
      const denial: Denial = {
        agent: agent ?? "",
        tool: text(payload, "tool") ?? "",
        reason: text(payload, "reason") ?? "",
        blockedBy: text(payload, "blocked_by"),
        seq,
      };
      const refused: RunView = { ...next, denials: [...next.denials, denial] };
      return agent === null ? refused : withAgent(refused, agent, seq, thinkingAgain);
    }

    case "tool.called": {
      // `tool.requested` is attempted work; this is executed work.
      const call = toolCallOf(agent, payload, seq);
      const executing: RunView = { ...next, toolCalls: [...next.toolCalls, call] };
      return agent === null
        ? executing
        : withAgent(executing, agent, seq, (node) => ({
          ...node,
          activity: "executing",
          currentTool: call.tool,
          lastError: null,
        }));
    }

    case "tool.result": {
      const answered: RunView = { ...next, toolCalls: attachResult(next.toolCalls, payload) };
      return agent === null ? answered : withAgent(answered, agent, seq, thinkingAgain);
    }

    case "tool.error": {
      const message = text(payload, "error") ?? "";
      const failed: RunView = {
        ...next,
        errors: [...next.errors, { agent, kind: "tool", message, seq }],
      };
      return agent === null
        ? failed
        : withAgent(failed, agent, seq, (node) => ({ ...thinkingAgain(node), lastError: message }));
    }

    // --- approvals ----------------------------------------------------------

    case "approval.requested": {
      const requestedApproval: ApprovalRecord = {
        id: text(payload, "approval_id") ?? `seq-${String(seq)}`,
        agent: agent ?? "",
        tool: text(payload, "tool") ?? "",
        risk: text(payload, "risk") ?? "",
        prompt: text(payload, "prompt") ?? "",
        status: "pending",
        automatic: flag(payload, "automatic"),
        precedent: text(payload, "precedent") !== null,
        policy: text(payload, "policy") !== null,
        rule: ruleOf(text(payload, "rule")),
        host: text(payload, "host"),
        scope: "call",
        seq,
      };
      // Policy approval needs no waiting, but remains recorded for auditability.
      const waiting =
        agent === null || requestedApproval.automatic
          ? next
          : withAgent(next, agent, seq, (node) => ({ ...node, activity: "waiting" }));
      return { ...waiting, approvals: [...waiting.approvals, requestedApproval] };
    }

    case "approval.resolved": {
      const status = text(payload, "status");
      const settled = isApprovalStatus(status) ? status : "expired";
      const resolved: RunView = { ...next, approvals: settle(next.approvals, payload, settled) };
      return agent === null ? resolved : withAgent(resolved, agent, seq, thinkingAgain);
    }

    // --- budget -------------------------------------------------------------

    case "budget.warning":
      return { ...next, budget: budgetOf(payload, next.budget) };

    case "budget.exceeded":
      return { ...next, budget: budgetOf(payload, next.budget), budgetExceeded: true };

    // --- channels ------------------------------------------------------------

    case "channel.inbound":
      // First channel-originated run event by construction.
      return {
        ...next,
        origin: {
          channel: text(payload, "channel") ?? "chat",
          identity: text(payload, "identity"),
          displayName: text(payload, "display_name"),
          threadRef: text(payload, "thread_ref"),
          trigger: text(payload, "trigger"),
        },
      };

    case "channel.outbound":
      // Delivery fact, not agent action; log panel renders it.
      return next;

    default:
      // Server may emit event types unknown to this build.
      return { ...next, unrecognised: [...next.unrecognised, event.type] };
  }
}

/** Fold events, optionally continuing existing state. */
export function reduceAll(events: readonly Event[], from: RunView = EMPTY_RUN): RunView {
  return events.reduce(reduce, from);
}

// --- small helpers ----------------------------------------------------------

/** Return to deciding activity; completed agents remain completed. */
function thinkingAgain(node: AgentNode): AgentNode {
  if (node.activity === "completed") return node;
  return { ...node, activity: "thinking", currentTool: null };
}

function approvalPolicyOf(payload: Payload): RunApprovalPolicy | null {
  if (!("approval" in payload)) return null;
  const approval = record(payload, "approval");
  const policies = record(approval, "tool_policies");
  const answered = (answer: string): string[] =>
    Object.keys(policies).filter((tool) => policies[tool] === answer);
  return {
    levels: strings(approval, "levels"),
    allowTools: answered("allow"),
    denyTools: answered("deny"),
    hosts: strings(approval, "hosts"),
    questionSeconds: int(approval, "question_seconds"),
    supervised: flag(approval, "supervised"),
    origin: text(approval, "origin"),
  };
}

function ruleOf(value: string | null): "level" | "tool" | null {
  return value === "level" || value === "tool" ? value : null;
}

function excerptOf(hit: Payload): RetrievedExcerpt {
  return {
    citation: text(hit, "citation") ?? "?",
    path: text(hit, "path"),
    heading: text(hit, "heading"),
    score: int(hit, "score"),
    matchedTerms: strings(hit, "matched_terms"),
    reasons: strings(hit, "reasons"),
    estimatedTokens: int(hit, "estimated_tokens"),
  };
}

function claimOf(kind: RunClaim["kind"], payload: Payload): RunClaim | null {
  const body = text(payload, kind === "summary" ? "summary" : "reason");
  return body === null ? null : { kind, text: body };
}

function toolCallOf(agent: string | null, payload: Payload, seq: number): ToolCall {
  return {
    agent: agent ?? "",
    tool: text(payload, "tool") ?? "",
    args: record(payload, "args"),
    callId: text(payload, "call_id"),
    result: null,
    seq,
  };
}

/** Attach `tool.result` to its call. */
function attachResult(calls: readonly ToolCall[], payload: Payload): ToolCall[] {
  const callId = text(payload, "call_id");
  const tool = text(payload, "tool");
  const result = text(payload, "result") ?? "";
  const updated = [...calls];

  // Match newest unanswered call, using `call_id` when present; one step may
  // call the same tool repeatedly.
  for (let index = updated.length - 1; index >= 0; index -= 1) {
    const call = updated[index];
    if (call?.result !== null) continue;
    if (callId === null ? call.tool !== tool : call.callId !== callId) continue;

    updated[index] = { ...call, result };
    return updated;
  }

  return updated;
}

function settle(
  approvals: readonly ApprovalRecord[],
  payload: Payload,
  status: ApprovalStatus,
): ApprovalRecord[] {
  const id = text(payload, "approval_id");
  const updated = [...approvals];

  for (let index = updated.length - 1; index >= 0; index -= 1) {
    const approval = updated[index];
    if (approval === undefined) continue;
    if (id === null ? approval.status !== "pending" : approval.id !== id) continue;

    updated[index] = {
      ...approval,
      status,
      automatic: approval.automatic || flag(payload, "automatic"),
      precedent: approval.precedent || text(payload, "precedent") !== null,
      policy: approval.policy || text(payload, "policy") !== null,
      scope: text(payload, "scope") === "run" ? "run" : approval.scope,
    };
    return updated;
  }

  return updated;
}

function budgetOf(payload: Payload, previous: Budget | null): Budget {
  const spentMicros = int(payload, "spent_micros") ?? previous?.spentMicros ?? 0;
  const capMicros = int(payload, "cap_micros") ?? previous?.capMicros ?? 0;
  const percent = int(payload, "percent") ?? (capMicros > 0 ? Math.floor((spentMicros * 100) / capMicros) : 100);
  return { spentMicros, capMicros, percent };
}

function isApprovalStatus(value: string | null): value is ApprovalStatus {
  return value === "pending" || value === "approved" || value === "denied" || value === "expired";
}

// --- derived views the components need --------------------------------------

/**
 * Return whether an approval still needs a person. Automatic approvals never
 * do, even before `approval.resolved`; fold and panel share this pending rule.
 */
export function awaitingPerson(approval: ApprovalRecord): boolean {
  return approval.status === "pending" && !approval.automatic;
}

/** Approvals a person still has to answer, oldest first. */
export function pendingApprovals(state: RunView): ApprovalRecord[] {
  return state.approvals.filter(awaitingPerson);
}

/** Every event type the reducer knows. Exported so a test can assert coverage. */
export const KNOWN_EVENT_TYPES: readonly EventType[] = [
  "run.started",
  "run.completed",
  "run.failed",
  "run.paused",
  "run.cancelled",
  "agent.spawned",
  "agent.thinking",
  "agent.message",
  "agent.handoff",
  "agent.completed",
  "llm.request",
  "llm.token",
  "llm.response",
  "llm.error",
  "tool.requested",
  "tool.approved",
  "tool.denied",
  "tool.called",
  "tool.result",
  "tool.error",
  "approval.requested",
  "approval.resolved",
  "budget.warning",
  "budget.exceeded",
  "channel.inbound",
  "channel.outbound",
];
