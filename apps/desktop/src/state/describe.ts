import type { Event } from "@agentspace/schemas";

import { ellipsise, summariseArgs } from "../lib/format";
import { display, flag, int, record, text, type Payload } from "../lib/payload";

import { pendingApprovals, type AgentNode, type RunStatus, type RunView } from "./reducer";

/**
 * The plain-language layer — BUILD_SPEC §5 Phase 11, "plain language first,
 * raw types second".
 *
 * Every event gets a sentence a person can read without knowing the event
 * vocabulary — *researcher wants to write notes.txt (waiting for you)* — and
 * the raw `tool.requested` stays beside it as a chip, because the raw type is
 * what a bug report needs and the sentence is what a person reads. The agent
 * cards and the run's status get the same treatment, and the "Now" line above
 * the graph is one sentence about the whole run at this cursor.
 *
 * All of it is a pure function of the event or the fold. That is not a style
 * preference: these sentences render inside `run-projection`, so
 * `replayIdentity.test.tsx` compares them live against replay at every
 * position, and a sentence that read a clock or remembered a previous event
 * would fail it. It also means the sentences live here, beside the reducer,
 * rather than in the components that show them — the reducer decides what an
 * event *means*, and the wording of that meaning belongs with it.
 *
 * **What the sentences must not do is improve on the log.** A terminal
 * `summary` is a model's claim (CLAUDE.md records four live runs whose summary
 * described work that never happened), so its sentence says "the supervisor
 * says", never "the run did". An approval's `prompt` is the sidecar's wording
 * of the *resolved* call and is quoted, never paraphrased from the raw
 * arguments — §2 makes the log the authority, and a client that built its own
 * wording could describe a different call from the one that ran.
 */

/** A tool call in three tenses, for the three events a call passes through. */
interface CallPhrase {
  /** "write notes.txt" — after "wants to". */
  readonly infinitive: string;
  /** "writing notes.txt" — after "is". */
  readonly progressive: string;
  /** "wrote notes.txt" — what happened. */
  readonly past: string;
}

/**
 * How a call reads, from the tool's name and its arguments.
 *
 * Only the five built-ins and the three control calls get a verb of their own;
 * anything else — a tool this build has never heard of — is rendered as the
 * raw call, which is honest about what is known. The sandbox resolves paths
 * before it compares them, and this does not: the path shown is what the
 * model *asked for*, which for a `tool.denied` with `blocked_by: "sandbox"` is
 * exactly the thing worth seeing.
 */
export function callPhrase(tool: string, args: Payload): CallPhrase {
  const arg = (key: string): string => ellipsise(display(args, key, "?"), 60);
  switch (tool) {
    case "write_file":
      return { infinitive: `write ${arg("path")}`, progressive: `writing ${arg("path")}`, past: `wrote ${arg("path")}` };
    case "read_file":
      return { infinitive: `read ${arg("path")}`, progressive: `reading ${arg("path")}`, past: `read ${arg("path")}` };
    case "list_dir":
      return { infinitive: `list ${arg("path")}`, progressive: `listing ${arg("path")}`, past: `listed ${arg("path")}` };
    case "run_shell":
      return {
        infinitive: `run a shell command: ${arg("command")}`,
        progressive: `running a shell command: ${arg("command")}`,
        past: `ran a shell command: ${arg("command")}`,
      };
    case "http_get":
      return { infinitive: `fetch ${arg("url")}`, progressive: `fetching ${arg("url")}`, past: `fetched ${arg("url")}` };
    case "spawn_agent":
      return { infinitive: `spawn ${arg("agent")}`, progressive: `spawning ${arg("agent")}`, past: `spawned ${arg("agent")}` };
    case "handoff":
      return { infinitive: `hand off to ${arg("to")}`, progressive: `handing off to ${arg("to")}`, past: `handed off to ${arg("to")}` };
    case "finish":
      return { infinitive: "finish", progressive: "finishing", past: "finished" };
    default: {
      const raw = `${tool}(${summariseArgs(args)})`;
      return { infinitive: `call ${raw}`, progressive: `calling ${raw}`, past: `called ${raw}` };
    }
  }
}

/** How an agent's `agent.completed` reason reads. */
function completionPhrase(reason: string | null): string {
  switch (reason) {
    case null:
    case "finished":
      return "finished";
    case "max_steps":
      return "ran out of steps";
    default:
      return `stopped (${reason})`;
  }
}

/**
 * One sentence for one event.
 *
 * The subject is the agent the event belongs to, or "the run" when it has
 * none. Text a model or a person wrote — a message, a streamed token, a
 * summary — is quoted and truncated, so a row stays a row; the payload is one
 * click away for the whole of it.
 */
export function sentenceFor(event: Event): string {
  const payload = event.payload ?? {};
  const who = event.agent_id ?? "the run";
  const read = (key: string): string | null => text(payload, key);
  const shown = (key: string): string => display(payload, key);
  const quote = (value: string | null, limit = 120): string => `“${ellipsise(value ?? "", limit)}”`;
  const phrase = callPhrase(read("tool") ?? "?", record(payload, "args"));

  switch (event.type) {
    // --- the run ------------------------------------------------------------
    case "run.started": {
      const goal = read("goal");
      return goal === null ? "The run started." : `The run started: ${quote(goal)}`;
    }
    case "run.completed": {
      const summary = read("summary");
      // A claim, and worded as one. What the run *did* is the tool events.
      return summary === null
        ? "The run completed."
        : `The run completed — the supervisor says: ${quote(summary, 160)}`;
    }
    case "run.failed": {
      const reason = read("reason");
      return reason === null ? "The run failed." : `The run failed: ${ellipsise(reason, 160)}`;
    }
    case "run.cancelled": {
      const reason = read("reason");
      return reason === null ? "The run was cancelled." : `The run was cancelled: ${ellipsise(reason, 160)}`;
    }
    case "run.paused":
      return "The run was paused.";

    // --- agents -------------------------------------------------------------
    case "agent.spawned": {
      const role = read("role");
      return role === null ? `${who} joined the run.` : `${who} joined the run — ${ellipsise(role, 80)}`;
    }
    case "agent.thinking":
      return `${who} is deciding what to do next (step ${shown("step")}).`;
    case "agent.message": {
      const to = read("to");
      const told = to === null || to === "user" ? "reported" : `told ${to}`;
      return `${who} ${told}: ${quote(read("text"))}`;
    }
    case "agent.handoff":
      return `${who} handed off to ${read("to") ?? "?"}: ${quote(read("task"), 90)}`;
    case "agent.completed":
      return `${who} ${completionPhrase(read("reason"))} after ${shown("steps")} steps.`;

    // --- the model ----------------------------------------------------------
    case "llm.request":
      return `${who} asked the model (${read("provider") ?? "?"} · ${read("model") ?? "?"}).`;
    case "llm.token":
      return `${who} streamed ${quote(read("text"))}`;
    case "llm.response": {
      const tool = read("stop_reason") === "tool_use" ? ", with a tool call" : "";
      const tokens = `${shown("input_tokens")} tokens in, ${shown("output_tokens")} out${tool}`;
      // A response with no text and no tool call is a model that said
      // nothing — and the log can now say whether it reasoned first. Phase
      // 5 watched a local model do that five times running with the whole
      // response in a separate thinking field; before `thinking` travelled
      // in this event, the two were the same row.
      if ((read("text") ?? "") === "" && tool === "") {
        const thinking = read("thinking") ?? "";
        return thinking === ""
          ? `The model said nothing to ${who} (${tokens}).`
          : `The model reasoned, then said nothing to ${who} (${tokens}).`;
      }
      return `The model answered ${who} (${tokens}).`;
    }
    case "llm.error":
      return `${who}'s model call failed: ${ellipsise(read("error") ?? "", 140)}`;

    // --- tools --------------------------------------------------------------
    case "tool.requested":
      return `${who} wants to ${phrase.infinitive}.`;
    case "tool.approved":
      // Carries the sidecar's `summary` of the resolved call, like the
      // approval events do; the arguments are not repeated on this one.
      return `${who} may ${read("summary") ?? phrase.infinitive} — ${flag(payload, "automatic") ? "allowed by policy" : "you allowed it"}.`;
    case "tool.denied": {
      // Three refusals share this event and are very different things to
      // see in a run — CLAUDE.md is explicit that a log which collapsed them
      // would render a traversal attempt and a declined dialog identically.
      const reason = ellipsise(read("reason") ?? "", 140);
      if (read("blocked_by") === "sandbox") {
        return `The sandbox stopped ${who} from ${phrase.progressive}: ${reason}`;
      }
      if (read("approval_id") !== null) {
        return `${who} was not allowed to ${phrase.infinitive}: ${reason}`;
      }
      return `${who} is not permitted to ${phrase.infinitive}: ${reason}`;
    }
    case "tool.called":
      return `${who} is ${phrase.progressive}.`;
    case "tool.result": {
      // No arguments travel on the result, so the call is named by its tool;
      // the result text usually says what it touched.
      const tool = read("tool") ?? "tool";
      const result = read("result");
      if (tool === "spawn_agent") {
        const worker = read("agent");
        return worker === null ? `${who}'s worker reported back.` : `${worker} reported back to ${who}: ${quote(result, 100)}`;
      }
      return result === null ? `${who}'s ${tool} call finished.` : `${who}'s ${tool} call finished: ${quote(result, 100)}`;
    }
    case "tool.error":
      return `${who}'s ${read("tool") ?? "tool"} call failed: ${ellipsise(read("error") ?? "", 140)}`;

    // --- approvals ----------------------------------------------------------
    case "approval.requested": {
      // `summary` is the sidecar's rendering of the *resolved* call — the
      // same words the approval panel shows — never rebuilt from `args`.
      const summary = read("summary") ?? phrase.infinitive;
      return flag(payload, "automatic")
        ? `${who} wants to ${summary} — allowed by policy.`
        : `${who} wants to ${summary} — waiting for you.`;
    }
    case "approval.resolved": {
      const tool = read("tool") ?? "?";
      const automatic = flag(payload, "automatic");
      switch (read("status")) {
        case "approved":
          return automatic ? `Policy allowed ${who}'s ${tool} call.` : `You allowed ${who}'s ${tool} call.`;
        case "denied":
          return `You denied ${who}'s ${tool} call.`;
        case "expired":
          return `${who}'s ${tool} call went unanswered and expired.`;
        default:
          return `${who}'s ${tool} call was ${read("status") ?? "settled"}.`;
      }
    }

    // --- budget -------------------------------------------------------------
    case "budget.warning": {
      const percent = int(payload, "percent");
      return percent === null
        ? "The month's budget is nearly used up."
        : `The month's budget is ${String(percent)}% used.`;
    }
    case "budget.exceeded":
      return "The monthly cap is reached — nothing past this point called a model.";

    // --- channels -----------------------------------------------------------
    case "channel.inbound": {
      const displayName = read("display_name");
      const who2 = read("identity") ?? "someone";
      const shownAs = displayName === null ? "" : ` (${displayName})`;
      return `${who2}${shownAs} asked from ${read("channel") ?? "chat"}: ${quote(read("text"), 90)}`;
    }
    case "channel.outbound":
      return `The reply in ${read("channel") ?? "chat"} was updated ${shown("edits")} times.`;

    default:
      // A type this build does not know. The raw name is the whole sentence,
      // because inventing one would claim knowledge the reducer does not have.
      return event.type;
  }
}

/**
 * The calls that touch nothing — `orchestrator/control.py`'s vocabulary. An
 * agent "executing" one of these is delegating or finishing, not running a
 * tool, and the supervisor spends most of a run in exactly that state: its
 * `spawn_agent` call stays open for as long as the worker works.
 */
const CONTROL_CALLS: ReadonlySet<string> = new Set(["spawn_agent", "handoff", "finish"]);

/** "running write_file", "delegating", "finishing". */
function executingLabel(agent: AgentNode): string {
  switch (agent.currentTool) {
    case null:
      return "running a tool";
    case "spawn_agent":
    case "handoff":
      return "delegating";
    case "finish":
      return "finishing";
    default:
      return `running ${agent.currentTool}`;
  }
}

/** How an agent's current activity reads on its card and in the "Now" line. */
export function activityLabel(agent: AgentNode): string {
  switch (agent.activity) {
    case "spawned":
      return "ready";
    case "thinking":
      return `thinking · step ${String(agent.steps)}`;
    case "calling":
      return "calling the model";
    case "executing":
      return executingLabel(agent);
    case "waiting":
      return "waiting for approval";
    case "completed":
      return agent.finishedReason === null ? "done" : `done · ${agent.finishedReason}`;
  }
}

/** How a run's status reads as a badge. */
export const STATUS_LABEL: Record<RunStatus, string> = {
  pending: "not started",
  running: "running",
  paused: "paused",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

/** "writer", "writer and editor", "writer, editor and reviewer". */
function list(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1] ?? ""}`;
}

function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * One sentence about the whole run at this cursor — the "Now" line.
 *
 * Derived from the fold and nothing else, so it is identical live and on
 * replay. The order of the cases is the order a person cares about: a question
 * waiting on them beats everything; then what is executing, because a shell
 * command can take half a minute; then who is talking to the model; then who
 * is between steps. A run with nothing happening says so rather than saying
 * nothing — CLAUDE.md records a local model that returned empty content five
 * times running, and "the model said nothing" has to be distinguishable from
 * "the page is broken".
 */
export function nowLine(view: RunView): string {
  const agents = view.agentOrder.map((name) => view.agents[name]).filter((agent) => agent !== undefined);
  const finished = agents.filter((agent) => agent.activity === "completed");

  switch (view.status) {
    case "pending":
      return view.eventCount === 0 ? "Waiting for the run to start." : "The run has not started yet.";
    case "paused":
      return "The run is paused.";
    case "completed":
    case "failed":
    case "cancelled": {
      const verb = view.status === "completed" ? "completed" : view.status === "failed" ? "failed" : "was cancelled";
      const denied = view.denials.length === 0 ? "" : `, ${plural(view.denials.length, "denied")}`;
      return `The run ${verb}: ${plural(agents.length, "agent")}, ${plural(view.toolCalls.length, "tool call")}${denied}.`;
    }
    case "running": {
      const waiting = pendingApprovals(view);
      if (waiting.length > 0) {
        const names = [...new Set(waiting.map((approval) => approval.agent))];
        return `${list(names)} ${names.length === 1 ? "is" : "are"} waiting for your approval.`;
      }
      const executing = agents.filter(
        (agent) => agent.activity === "executing" && !CONTROL_CALLS.has(agent.currentTool ?? ""),
      );
      if (executing.length > 0) {
        const [first] = executing;
        if (first !== undefined && executing.length === 1) return `${first.name} is ${executingLabel(first)}.`;
        return `${list(executing.map((agent) => agent.name))} are running tools.`;
      }
      const calling = agents.filter((agent) => agent.activity === "calling");
      if (calling.length > 0) {
        return `${list(calling.map((agent) => agent.name))} ${calling.length === 1 ? "is" : "are"} asking the model.`;
      }
      const thinking = agents.filter((agent) => agent.activity === "thinking");
      if (thinking.length > 0) {
        const done = finished.length === 0 ? "" : `${plural(finished.length, "agent")} finished; `;
        return `${done}${list(thinking.map((agent) => agent.name))} ${thinking.length === 1 ? "is" : "are"} deciding what to do next.`;
      }
      // Only delegating agents left: the supervisor's `spawn_agent` is open
      // and the worker has not yet produced an event of its own.
      const delegating = agents.filter((agent) => agent.activity === "executing");
      if (delegating.length > 0) {
        const [first] = delegating;
        const to = view.handoffs.filter((handoff) => handoff.from === first?.name).at(-1)?.to;
        return `${first?.name ?? "the supervisor"} is waiting on ${to ?? "a worker"}.`;
      }
      if (agents.length === 0) return "The run is starting.";
      if (finished.length === agents.length) return `${plural(finished.length, "agent")} finished; waiting for the run to end.`;
      return `${plural(agents.length, "agent")} in the run; nothing is happening right now.`;
    }
  }
}
