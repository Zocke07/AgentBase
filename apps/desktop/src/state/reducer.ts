import type { Event, EventType } from "@agentspace/schemas";

import { flag, int, record, strings, text, type Payload } from "../lib/payload";

/**
 * The run reducer — the UI's half of BUILD_SPEC §2.
 *
 * "Every agent action is an append-only event row, and the UI is a pure
 * projection of the event log." This is that projection. Everything the
 * dashboard renders comes from here, and nothing the dashboard renders about a
 * run comes from anywhere else — no side fetch, no local bookkeeping, no
 * remembered value from a previous render.
 *
 * Three properties are load-bearing, and each has tests that fail without it:
 *
 * **It is a pure fold.** `reduce(state, event)` returns a new state and touches
 * nothing. That is what makes replay and live the *same* rendering path rather
 * than two paths that happen to agree — §5 Phase 7's acceptance criterion asks
 * for replay to be pixel-identical to live, and the only way to be sure is for
 * there to be one function and one input.
 *
 * **It has no clock.** Nothing here reads `Date.now()`. A single relative
 * timestamp ("3 seconds ago") would make the same log render differently on
 * every fold and quietly break the criterion above. Times come from the
 * events' own `ts`.
 *
 * **It separates what an agent claimed from what it did.** `claim` holds the
 * terminal `summary` or `reason`; `toolCalls` holds the calls that actually
 * executed. CLAUDE.md records three live runs where a run completed claiming
 * work that the log shows never happened — a file "saved" by a run containing
 * no file tool call at all. Keeping them in one field would make the dashboard
 * repeat the confabulation instead of exposing it.
 */

/**
 * What an agent is doing right now, as far as the log says.
 *
 * Every event an agent emits leaves it in exactly one of these, and the
 * transition table is pinned by a test that walks a whole tool call. The
 * original machine had four transitions and left every other event's label
 * where it was, so an agent running a thirty-second shell command read
 * "calling the model" and one whose approval had just been granted read
 * "waiting for approval" until its next thinking event. §5 Phase 7's "live
 * status colour" is only live if the colour follows the log.
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
  readonly steps: number;
  readonly finishedReason: string | null;
  /** Streamed output of the *current* model call — reset on each `llm.request`. */
  readonly streamedText: string;
  readonly lastMessage: string | null;
  /** Where this agent first appears — the graph orders nodes by it. */
  readonly seq: number;
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
  /** The sentence the backend rendered. Never composed here — see §2. */
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
 * Where a run came from, when it did not come from this window.
 *
 * §5 Phase 8 requires a Discord-originated run to "appear live in the
 * dashboard, and vice versa. Same event log, no special-casing." The
 * no-special-casing half is already true — the SSE endpoint has no idea a
 * channel exists — but a user watching a run they did not start still needs to
 * know who did, and the log is the only place that says so.
 *
 * `identity` is the *internal* name the sender's external id resolved to, not
 * anything the sender typed. `displayName` is theirs and is shown beside it,
 * never instead of it: a chat user controls their own display name, so a UI
 * that showed only that could be made to read like anyone.
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
  /** Event types this build does not know about. Rendered, never swallowed. */
  readonly unrecognised: readonly string[];
}

export const EMPTY_RUN: RunView = {
  runId: null,
  goal: null,
  origin: null,
  limits: null,
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
  steps: 0,
  finishedReason: null,
  streamedText: "",
  lastMessage: null,
  seq,
});

/**
 * Create a node for `name` if the run has not seen it before.
 *
 * Applied to *every* event carrying an `agent_id`, not only `agent.spawned`. A
 * stream resumed mid-run legitimately starts after the spawn event, and an
 * agent whose spawn was missed would otherwise vanish from the graph while the
 * rest of its events rendered — a graph that looks complete and is not.
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
  };

  // One place where an agent becomes known to the run, so no case below has to
  // remember to do it.
  const next = agent === null ? counted : ensureAgent(counted, agent, seq);

  switch (event.type) {
    // --- the run ------------------------------------------------------------

    case "run.started":
      return {
        ...next,
        goal: text(payload, "goal"),
        limits: record(payload, "limits"),
        status: "running",
      };

    case "run.completed":
      return { ...next, status: "completed", claim: claimOf("summary", payload) };

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
      // A new call starts a new stream. Keeping the previous call's text would
      // render step 4's answer glued to the end of step 1's.
      return withAgent(next, agent, seq, (node) => ({ ...node, activity: "calling", streamedText: "" }));

    case "llm.token":
      // Deliberately does *not* change `activity`. CLAUDE.md: deltas arrive
      // 1-10 at a time from Anthropic and a whole live Ollama run emitted zero
      // of them, so an agent that streams nothing is not an idle agent.
      if (agent === null) return next;
      return withAgent(next, agent, seq, (node) => ({
        ...node,
        streamedText: node.streamedText + (text(payload, "text") ?? ""),
      }));

    case "llm.response": {
      const totalled: RunView = {
        ...next,
        inputTokens: next.inputTokens + (int(payload, "input_tokens") ?? 0),
        outputTokens: next.outputTokens + (int(payload, "output_tokens") ?? 0),
        costMicros: next.costMicros + (int(payload, "cost_micros") ?? 0),
      };
      return agent === null ? totalled : withAgent(totalled, agent, seq, thinkingAgain);
    }

    case "llm.error": {
      const recorded: RunView = {
        ...next,
        errors: [...next.errors, { agent, kind: "llm", message: text(payload, "error") ?? "", seq }],
      };
      return agent === null ? recorded : withAgent(recorded, agent, seq, thinkingAgain);
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
      // The event that means something *happened*. `tool.requested` is what an
      // agent tried; this is what executed.
      const call = toolCallOf(agent, payload, seq);
      const executing: RunView = { ...next, toolCalls: [...next.toolCalls, call] };
      return agent === null
        ? executing
        : withAgent(executing, agent, seq, (node) => ({ ...node, activity: "executing", currentTool: call.tool }));
    }

    case "tool.result": {
      const answered: RunView = { ...next, toolCalls: attachResult(next.toolCalls, payload) };
      return agent === null ? answered : withAgent(answered, agent, seq, thinkingAgain);
    }

    case "tool.error": {
      const failed: RunView = {
        ...next,
        errors: [...next.errors, { agent, kind: "tool", message: text(payload, "error") ?? "", seq }],
      };
      return agent === null ? failed : withAgent(failed, agent, seq, thinkingAgain);
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
      // A policy's yes is not a question. The gate emits the request and its
      // resolution as two events, and between them nobody is waiting on
      // anything — so the agent is not "waiting", and `pendingApprovals` below
      // does not count it. The record still goes in, because "what did this
      // run do without asking me" is answered from exactly these rows.
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
      // The first event of a channel-originated run, by construction: the
      // launcher appends it before the orchestrator task exists, so it cannot
      // race `run.started`.
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
      // Deliberately changes nothing. It records that the run was *reported*
      // to a conversation, which is a fact about delivery rather than about
      // what the agents did — and the graph is a projection of the latter. It
      // is rendered in the log panel, where a reader asking "did this reach
      // Discord?" is asking the question it answers.
      return next;

    default:
      // Not a `never` check by accident: the server can emit a type this build
      // has never heard of, and Phase 2's bug was exactly that being silent.
      return { ...next, unrecognised: [...next.unrecognised, event.type] };
  }
}

/** Fold a batch of events, optionally continuing from an existing state. */
export function reduceAll(events: readonly Event[], from: RunView = EMPTY_RUN): RunView {
  return events.reduce(reduce, from);
}

// --- small helpers ----------------------------------------------------------

/**
 * Back to deciding what to do next: the state between one thing finishing —
 * a model call, a tool, an approval — and the next event saying what follows.
 * A completed agent stays completed; a late event for it does not revive it.
 */
function thinkingAgain(node: AgentNode): AgentNode {
  if (node.activity === "completed") return node;
  return { ...node, activity: "thinking", currentTool: null };
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

/**
 * Attach a `tool.result` to the call it belongs to.
 *
 * Matched on `call_id` when there is one, because a single agent step can carry
 * several calls to the same tool and pairing them by name would attach a result
 * to the wrong one.
 */
function attachResult(calls: readonly ToolCall[], payload: Payload): ToolCall[] {
  const callId = text(payload, "call_id");
  const tool = text(payload, "tool");
  const result = text(payload, "result") ?? "";
  const updated = [...calls];

  // Walked backwards so the newest unanswered call wins, and matched on
  // `call_id` when there is one: a single agent step can carry several calls to
  // the same tool, and pairing them by name would attach a result to the wrong
  // one.
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
 * Whether an approval is a question a *person* still has to answer.
 *
 * An automatic one never is, even while its `approval.resolved` has not yet
 * arrived: the policy answered it before the question was written. One rule,
 * used by the fold's derived views and by the panel that renders them, so the
 * two cannot disagree about what "pending" means.
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
