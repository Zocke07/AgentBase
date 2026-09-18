import type { Event, EventType } from "@agentspace/schemas";

import { flag, int, record, records, strings, text, type Payload } from "../lib/payload";

/**
 * The run reducer: the UI's half of BUILD_SPEC §2. Everything the dashboard
 * renders about a run comes from this fold and nowhere else.
 *
 * It is pure (one function, one input, so live and replay are the same
 * rendering path), it has no clock (a relative timestamp would make the same
 * log render differently on every fold), and it keeps what an agent claimed
 * (`claim`) apart from what it did (`toolCalls`), because live runs have
 * completed claiming work the log shows never happened.
 */

/**
 * What an agent is doing right now, as far as the log says. Every event an
 * agent emits leaves it in exactly one of these; a test walks a whole tool call.
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
  /** The tool being executed while `activity` is `"executing"`; null otherwise. */
  readonly currentTool: string | null;
  /** The message of an `llm.error`/`tool.error` this agent has not yet acted past. */
  readonly lastError: string | null;
  readonly steps: number;
  readonly finishedReason: string | null;
  /** Streamed output of the *current* model call, reset on each `llm.request`. */
  readonly streamedText: string;
  readonly lastMessage: string | null;
  /** Where this agent first appears, the graph orders nodes by it. */
  readonly seq: number;
  /** This agent's own model calls, summed from its `llm.response` events. */
  readonly calls: number;
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly costMicros: number;
  /**
   * The input tokens of the latest call and the largest so far: the size of
   * the context this agent is carrying, and the most it has carried.
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
  /** The sentence the backend rendered. Never composed here; see §2. */
  readonly prompt: string;
  readonly status: ApprovalStatus;
  readonly automatic: boolean;
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
   * Which boundary refused: `"sandbox"` when the call was out of bounds and
   * nobody was asked, `null` when the allowlist refused it or a person did.
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

/** A terminal event's own account of the run. An assertion, not a fact. */
export interface RunClaim {
  readonly kind: "summary" | "reason";
  readonly text: string;
}

/**
 * Where a run came from, when it did not come from this window. `identity`
 * is the internal name the sender resolved to; `displayName` is theirs and is
 * shown beside it, never instead of it, since a chat user controls their own.
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
  /** Set only for a run that arrived from a chat channel. */
  readonly origin: RunOrigin | null;
  readonly limits: Payload | null;
  /** The cited excerpts retrieved for the goal, and the citations the user removed. */
  readonly knowledge: readonly RetrievedExcerpt[];
  readonly knowledgeExclusions: readonly string[];
  /** Where the run's outcome was written as a proposed memory note, if it was. */
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
  /** The ledger's figure for every model call so far, summed from `llm.response`. */
  readonly costMicros: number;
  readonly budget: Budget | null;
  readonly budgetExceeded: boolean;
  readonly lastSeq: number;
  readonly eventCount: number;
  /** `run.started`'s own timestamp, and the latest event's. Never a clock. */
  readonly startedTs: string | null;
  readonly latestTs: string | null;
  /** Event types this build does not know about. Rendered, never swallowed. */
  readonly unrecognised: readonly string[];
}

export const EMPTY_RUN: RunView = {
  runId: null,
  goal: null,
  origin: null,
  limits: null,
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
 * Create a node for `name` if the run has not seen it before. Applied to every
 * event carrying an `agent_id`, so a stream resumed after the spawn still
 * shows the agent.
 */
function ensureAgent(state: RunView, name: string, seq: number): RunView {
  if (state.agents[name] !== undefined) return state;

  return {
    ...state,
    agents: { ...state.agents, [name]: newAgent(name, seq) },
    agentOrder: [...state.agentOrder, name],
  };
}

/** Apply `change` to one agent's node, leaving the rest of the state alone. */
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

/** Apply one event. Returns a new state; never mutates the one passed in. */
export function reduce(state: RunView, event: Event): RunView {
  const payload = event.payload ?? {};
  const agent = event.agent_id ?? null;
  const seq = event.seq;

  const counted: RunView = {
    ...state,
    runId: state.runId ?? event.run_id,
    lastSeq: Math.max(state.lastSeq, seq),
    eventCount: state.eventCount + 1,
    // The first event seen stands in for `run.started` on a resumed stream.
    startedTs: state.startedTs ?? event.ts,
    latestTs: event.ts,
  };

  // One place where an agent becomes known to the run.
  const next = agent === null ? counted : ensureAgent(counted, agent, seq);

  switch (event.type) {
    // --- the run ------------------------------------------------------------

    case "run.started":
      return {
        ...next,
        goal: text(payload, "goal"),
        limits: record(payload, "limits"),
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
      // A new call starts a new stream; the previous call's text does not carry over.
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        activity: "calling",
        streamedText: "",
        lastError: null,
      }));

    case "llm.token":
      // Deliberately does not change `activity`: an agent that streams nothing is not idle.
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
      // `tool.requested` is what an agent tried; this is what executed.
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
        seq,
      };
      // A policy's yes is not a question: nobody waits on an automatic one,
      // but the record stays so "what ran without asking me" is answerable.
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
      // The first event of a channel-originated run, by construction.
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
      // A fact about delivery, not about what the agents did; the log panel renders it.
      return next;

    default:
      // Not a `never` check: the server can emit a type this build has never heard of.
      return { ...next, unrecognised: [...next.unrecognised, event.type] };
  }
}

/** Fold a batch of events, optionally continuing from an existing state. */
export function reduceAll(events: readonly Event[], from: RunView = EMPTY_RUN): RunView {
  return events.reduce(reduce, from);
}

// --- small helpers ----------------------------------------------------------

/** Back to deciding what to do next. A completed agent stays completed. */
function thinkingAgain(node: AgentNode): AgentNode {
  if (node.activity === "completed") return node;
  return { ...node, activity: "thinking", currentTool: null };
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

/** Attach a `tool.result` to the call it belongs to. */
function attachResult(calls: readonly ToolCall[], payload: Payload): ToolCall[] {
  const callId = text(payload, "call_id");
  const tool = text(payload, "tool");
  const result = text(payload, "result") ?? "";
  const updated = [...calls];

  // Newest unanswered call first, matched on `call_id` when there is one: a
  // step can carry several calls to the same tool.
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
 * Whether an approval is a question a person still has to answer. An automatic
 * one never is, even before its `approval.resolved` arrives. The one rule for
 * "pending", shared by the fold and the panel.
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
