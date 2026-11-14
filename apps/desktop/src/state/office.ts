import { ellipsise, modelLabel, runOriginLabel } from "../lib/format";
import { text } from "../lib/payload";
import { FAMILY_LABEL, toolInfo, type ToolFamily } from "../lib/tools";

import { activityLabel, callPhrase, STATUS_LABEL } from "./describe";
import { writtenFiles, type WrittenFile } from "./files";
import {
  changedNothing,
  pendingApprovals,
  type Activity,
  type AgentNode,
  type ApprovalRecord,
  type RetrievedExcerpt,
  type RunClaim,
  type RunStatus,
  type RunView,
  type ToolCall,
} from "./reducer";

/** The supervisor's `agent_id`, fixed by the orchestrator so a replay can find it. */
export const SUPERVISOR = "supervisor";

/**
 * The office: a run projected as a room (Phase 20, brief section 7).
 *
 * `officeOf` turns the fold into what is in the room at the cursor: who sits
 * at which desk and what each is doing, the slips and stamps of the calls in
 * hand, the folders that carry delegated work, and what the reception, the
 * board, the library, the clock and the meter show. It is a pure function of
 * `RunView`: no clock, no random source, no network, no roster. Live and
 * replay therefore draw the same room at the same cursor, and every object
 * in it has a source in the log.
 *
 * Things that come and go last for a span of events, never a span of time.
 * A folder is in flight from its `agent.handoff` until the receiver's next
 * event; a slip stays until its agent's next model call; a speech bubble
 * until its speaker's next model call or, for one that has finished, until
 * its work is back with the sender. The spans are read from positions the
 * reducer records (`latestSeq`, `modelCallSeq`, `completedSeq`).
 *
 * What a model said is a claim and what a tool did is evidence, and the
 * model keeps them apart: `Bubble` and `Board.claim` are claims; slips,
 * stamps, tray counts, documents and costs are evidence.
 */

// --- what is on a desk --------------------------------------------------------

/** What an agent's face, a small display, shows. One per reducer activity. */
export type Face =
  /** Sat down and ready. */
  | "dot"
  /** Asking its model: the dots move while the call is open. */
  | "asking"
  /** Deciding what to do next: still dots. */
  | "thinking"
  /** A tool is running: the tool family's glyph. */
  | "tool"
  /** Waiting for a person's answer. */
  | "question"
  /** Finished. */
  | "tick"
  /** Stopped after failing the same way three times. */
  | "knot"
  /** An error it has not moved past. */
  | "alert";

/** The mark an answered call carries, in the words the log uses. */
export type Stamp =
  /** A policy answered yes: the risk level is pre-approved, or the tool is always allowed. */
  | { readonly kind: "policy"; readonly rule: "level" | "tool" | null; readonly host: string | null }
  /** An earlier yes for the run covers this call. */
  | { readonly kind: "precedent" }
  /** A person said yes, for this call or for the rest of the run. */
  | { readonly kind: "allowed"; readonly scope: "call" | "run" }
  /** A person said no. */
  | { readonly kind: "denied" }
  /** Nobody answered in time. */
  | { readonly kind: "expired" }
  /** Refused before any question: outside the space's folder. */
  | { readonly kind: "sandbox" }
  /** Refused by a rule: not on the agent's list, or never allowed. */
  | { readonly kind: "refused" };

export type SlipState =
  /** Asked for, not yet answered or run. */
  | "requested"
  /** A person is being asked. */
  | "waiting"
  /** Running. */
  | "working"
  /** Ran and answered. */
  | "done"
  /** Ran or was sent, and failed. */
  | "failed"
  /** Failed without changing anything: a missed lookup, or a refusal sent again. */
  | "missed"
  /** Not allowed to run. */
  | "refused";

/** One tool call of an agent's current step, and what became of it. */
export interface Slip {
  /** The request's seq: stable for the life of the slip. */
  readonly seq: number;
  readonly tool: string;
  readonly family: ToolFamily;
  /** "read notes.md": what the call is, after "wants to". */
  readonly action: string;
  readonly state: SlipState;
  readonly stamp: Stamp | null;
  /** The stamp, or the state when there is none, in words. */
  readonly label: string;
  /** Risk level of the question it raised, when it raised one. */
  readonly risk: string | null;
  /** The host a network call reached or would reach, when the log names it. */
  readonly host: string | null;
}

/** What an agent is saying. Always a claim, never evidence. */
export interface Bubble {
  /** `thought`: the model's text as it streams. `speech`: an `agent.message`. */
  readonly kind: "thought" | "speech";
  readonly text: string;
}

/** Trouble at a desk. An `alarm` is a failure; a `note` changed nothing. */
export interface Trouble {
  readonly kind: "alarm" | "note";
  readonly message: string;
}

/** Delegated work, carried between desks. */
export interface Folder {
  /** The handoff's seq. */
  readonly seq: number;
  readonly from: string;
  readonly to: string;
  readonly task: string;
  /**
   * `delegated`: the supervisor started the receiver and gave it this work.
   * `requested`: a worker asked for the work to go to someone and finished;
   * the supervisor decides, so the folder only shows while nobody has taken
   * the name up.
   */
  readonly kind: "delegated" | "requested";
  /**
   * `arriving`: handed over, and the receiver has not acted since.
   * `open`: on the receiver's desk while it works.
   * `returning`: the receiver finished, and the sender has not acted since.
   * `returned`: back with the sender.
   */
  readonly phase: "arriving" | "open" | "returning" | "returned";
}

export interface Desk {
  /** The agent's name: the key everything else refers to. */
  readonly name: string;
  /** The supervisor's desk, at the head of the room. */
  readonly lead: boolean;
  /** Work was handed to this name and nobody has sat down: an empty chair. */
  readonly ghost: boolean;
  readonly role: string | null;
  /** The model's own name, "Claude Haiku 4.5"; null when the log gives none. */
  readonly model: string | null;
  readonly activity: Activity;
  readonly face: Face;
  /** The family of the tool running now; null unless `face` is `tool`. */
  readonly family: ToolFamily | null;
  /** One or two words for the state: "Asking its model", "Waiting for you". */
  readonly stateLabel: string;
  /** The reducer's own sentence for the activity, as the inspector shows it. */
  readonly activityLabel: string;
  readonly bubble: Bubble | null;
  /** The calls of the agent's current step, oldest first. */
  readonly slips: readonly Slip[];
  readonly trouble: Trouble | null;
  /**
   * Nothing to say beyond its name: ready or done, with no trouble and no
   * call of its step refused, denied or left unanswered. A quiet desk's
   * plate may fold to its name; any other desk keeps its words in view.
   */
  readonly quiet: boolean;
  /** Results this agent's calls have returned. */
  readonly results: number;
  /** Files this agent's calls wrote: documents in its tray, each opening in Knowledge. */
  readonly documents: readonly WrittenFile[];
  /** Calls refused or denied. */
  readonly refusals: number;
  /** Work handed to this desk that is on it now. */
  readonly inbox: readonly Folder[];
  /** Work this desk handed out that has come back. */
  readonly returned: number;
  readonly steps: number;
  readonly maxSteps: number | null;
  readonly costMicros: number;
  /** The seq of the agent's latest event; 0 for a ghost. */
  readonly latestSeq: number;
  /**
   * "researcher Reading a feed Claude Haiku 5.5. Finds sources. 3 tool calls."
   * It opens with what the desk's plate shows, in the plate's order, so that
   * someone who speaks to the screen can say what they see (WCAG 2.5.3).
   */
  readonly accessibleName: string;
}

// --- the rest of the room -----------------------------------------------------

export interface Reception {
  /** Where the run came from, in words: "Started by you", "From Discord". */
  readonly origin: string;
  /** The channel or trigger behind those words; `window` for a person here. */
  readonly source: string;
  /** Who sent it, for a chat run: the resolved identity, then the name shown. */
  readonly sender: string | null;
  /** Questions a person still has to answer. The docked panel answers them. */
  readonly waiting: number;
  /** The risk of the most severe waiting question; null when none waits. */
  readonly waitingRisk: string | null;
}

export interface Board {
  readonly goal: string | null;
  readonly status: RunStatus;
  readonly statusLabel: string;
  /** The run's own account of how it ended: a claim. */
  readonly claim: RunClaim | null;
  /** The memory note the run wrote, pinned beside the outcome. */
  readonly memoryPath: string | null;
  /** Files the run's tools wrote, each opening in Knowledge: evidence. */
  readonly documents: readonly WrittenFile[];
  /** Event types this build does not know, named rather than swallowed. */
  readonly unrecognised: readonly string[];
}

export interface Clock {
  /** Seconds from `run.started` to the latest event; null before the start. */
  readonly elapsedSeconds: number | null;
  /** The run's time limit, when `run.started` recorded one. */
  readonly limitSeconds: number | null;
}

export interface Meter {
  readonly costMicros: number;
  /** `warn` from `budget.warning`, `over` from `budget.exceeded`. */
  readonly level: "ok" | "warn" | "over";
  /** Percent of the monthly limit, when a budget event reported it. */
  readonly percent: number | null;
  /** The warning in words, to be said aloud once; null while all is well. */
  readonly announcement: string | null;
}

export interface OfficeModel {
  /** Lights on once the run has started. */
  readonly lit: boolean;
  /** Dimmed for a cancelled or paused run. */
  readonly dimmed: boolean;
  readonly status: RunStatus;
  /** The supervisor's desk; null until it appears. */
  readonly lead: Desk | null;
  /** Worker desks and empty chairs, in the order each was first named. */
  readonly desks: readonly Desk[];
  /** Folders travelling or just back: the ones not lying on a desk. */
  readonly folders: readonly Folder[];
  readonly reception: Reception;
  readonly board: Board;
  /** One book per vault excerpt the supervisor was given. */
  readonly library: readonly RetrievedExcerpt[];
  readonly clock: Clock;
  readonly meter: Meter;
  /** The desk with the latest event, for a camera that follows the work; none once the run is over. */
  readonly focus: string | null;
  /**
   * The latest thing worth saying aloud once: an agent finishing or the
   * run ending. `key` changes when there is something new. A budget warning
   * is said from `meter.announcement`, which no completion can talk over.
   */
  readonly announcement: { readonly key: string; readonly text: string } | null;
}

// --- words --------------------------------------------------------------------

/** How many characters of streaming text a thought bubble holds. */
export const BUBBLE_CHARS = 80;

const STATE_LABEL: Readonly<Record<Face, string>> = {
  dot: "Ready",
  asking: "Asking its model",
  thinking: "Thinking",
  tool: "Using a tool",
  question: "Waiting for you",
  tick: "Done",
  knot: "Stuck",
  alert: "Hit an error",
};

/** A stamp as the words on it. */
/** Stamps that say a call did not run as asked. */
const REFUSALS: ReadonlySet<Stamp["kind"]> = new Set(["denied", "expired", "sandbox", "refused"]);

export function stampLabel(stamp: Stamp): string {
  switch (stamp.kind) {
    case "policy":
      return "Allowed by policy";
    case "precedent":
      return "Allowed for this run";
    case "allowed":
      return stamp.scope === "run" ? "Allowed, for this run" : "Allowed";
    case "denied":
      return "Denied";
    case "expired":
      return "Nobody answered";
    case "sandbox":
      return "Outside this space's folder";
    case "refused":
      return "Not allowed";
  }
}

/** Why a policy stamp was given: the rule, and the host when one was reached. */
export function stampReason(stamp: Stamp, slip: Pick<Slip, "tool" | "risk">): string | null {
  if (stamp.kind !== "policy") return null;
  const rule =
    stamp.rule === "tool"
      ? `${slip.tool} is always allowed`
      : stamp.rule === "level" && slip.risk !== null
        ? `${slip.risk} risk runs on its own`
        : null;
  const host = stamp.host === null ? null : `reaching ${stamp.host}`;
  return [rule, host].filter((part) => part !== null).join(", ") || null;
}

const SLIP_LABEL: Readonly<Record<SlipState, string>> = {
  requested: "Asked for",
  waiting: "Waiting for you",
  working: "Working",
  done: "Done",
  failed: "Failed",
  missed: "Found nothing",
  refused: "Not allowed",
};

const plural = (count: number, noun: string): string => `${String(count)} ${noun}${count === 1 ? "" : "s"}`;

// --- slips --------------------------------------------------------------------

function stampOf(approval: ApprovalRecord | undefined, sandbox: boolean, refused: boolean): Stamp | null {
  if (sandbox) return { kind: "sandbox" };
  if (approval === undefined) return refused ? { kind: "refused" } : null;
  if (approval.status === "expired") return { kind: "expired" };
  // A no that nobody was asked for, a tool that is never allowed or an
  // earlier answer standing for this call, is a rule's refusal, not a person's.
  if (approval.status === "denied") return approval.automatic ? { kind: "refused" } : { kind: "denied" };
  if (approval.automatic) {
    return approval.precedent ? { kind: "precedent" } : { kind: "policy", rule: approval.rule, host: approval.host };
  }
  if (approval.status === "approved") return { kind: "allowed", scope: approval.scope };
  return refused ? { kind: "refused" } : null;
}

/**
 * The calls of an agent's current step. The orchestrator handles a model's
 * calls one after another, so everything that happened to a call sits in the
 * log between its request and the agent's next request.
 */
function slipsFor(view: RunView, agent: AgentNode): Slip[] {
  const requests = view.requested.filter((call) => call.agent === agent.name && call.seq > (agent.modelCallSeq ?? 0));
  return requests.map((request, index): Slip => {
    const until = requests[index + 1]?.seq ?? Number.POSITIVE_INFINITY;
    const mine = (entry: { agent: string | null; tool: string | null; seq: number }): boolean =>
      entry.agent === agent.name && entry.tool === request.tool && entry.seq > request.seq && entry.seq < until;
    const approval = view.approvals.find(mine);
    const denial = view.denials.find(mine);
    const error = view.errors.find((entry) => entry.kind === "tool" && mine(entry));
    const call: ToolCall | undefined = view.toolCalls.find(mine);

    const stamp = stampOf(approval, denial?.blockedBy === "sandbox", denial !== undefined);
    const state: SlipState =
      denial !== undefined
        ? "refused"
        : error !== undefined
          ? changedNothing(error, view)
            ? "missed"
            : "failed"
          : call !== undefined
            ? call.result === null
              ? "working"
              : "done"
            : approval?.status === "pending" && !approval.automatic
              ? "waiting"
              : "requested";
    const info = toolInfo(request.tool);
    return {
      seq: request.seq,
      tool: request.tool,
      family: info.family,
      action: callPhrase(request.tool, request.args).infinitive,
      state,
      stamp,
      // A failure or a wait says more than the yes that came before it.
      label: stamp !== null && (state === "refused" || state === "working" || state === "done") ? stampLabel(stamp) : SLIP_LABEL[state],
      risk: approval?.risk ?? null,
      host: approval?.host ?? hostOf(request),
    };
  });
}

/** The host in a call's own arguments, for a fetch the log has not yet named one for. */
function hostOf(call: ToolCall): string | null {
  if (!toolInfo(call.tool).fetches) return null;
  const url = text(call.args, "url");
  if (url === null) return null;
  // Parsed as the fetch itself would be, so that text before an `@` is never
  // taken for the host. A model's argument is not always a URL.
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

// --- folders ------------------------------------------------------------------

function foldersOf(view: RunView): Folder[] {
  // The last delegation to each desk, found once, not once per folder.
  const lastDelegation = new Map<string, number>();
  view.handoffs.forEach((handoff, index) => {
    if (handoff.from === SUPERVISOR) lastDelegation.set(handoff.to, index);
  });
  return view.handoffs.map((handoff, index): Folder => {
    const to = view.agents[handoff.to];
    const from = view.agents[handoff.from];
    const kind: Folder["kind"] = handoff.from === SUPERVISOR ? "delegated" : "requested";
    const base = { seq: handoff.seq, from: handoff.from, to: handoff.to, task: handoff.task, kind };
    // A worker's handoff is a request that goes through the supervisor: it
    // waits at an empty chair while nobody of that name exists, and is the
    // supervisor's to act on once somebody does.
    if (kind === "requested") return { ...base, phase: to === undefined ? "arriving" : "returned" };
    // A later delegation to the same desk takes this one's place on it.
    const superseded = (lastDelegation.get(handoff.to) ?? index) > index;
    const phase: Folder["phase"] =
      to === undefined || to.latestSeq <= handoff.seq
        ? "arriving"
        : superseded
          ? "returned"
          : to.completedSeq === null || to.completedSeq < handoff.seq
            ? "open"
            : from === undefined || from.latestSeq < to.completedSeq
              ? "returning"
              : "returned";
    return { ...base, phase };
  });
}

// --- desks --------------------------------------------------------------------

/** Reasons an agent completes having done what it set out to do. */
const FINISHED: ReadonlySet<string | null> = new Set([null, "finished", "handoff"]);

function faceOf(agent: AgentNode, trouble: Trouble | null): Face {
  switch (agent.activity) {
    case "completed":
      // Out of steps or stuck is a stop, not a finish: it gets no tick.
      return FINISHED.has(agent.finishedReason) ? "tick" : "knot";
    case "calling":
      return "asking";
    case "executing":
      return "tool";
    case "waiting":
      // A desk that needs the viewer says so, whatever went wrong before.
      return "question";
    case "spawned":
      return trouble?.kind === "alarm" ? "alert" : "dot";
    case "thinking":
      return trouble?.kind === "alarm" ? "alert" : "thinking";
  }
}

/** How a completed agent's reason reads on its plate. */
function completionLabel(reason: string | null): string {
  switch (reason) {
    case null:
    case "finished":
      return "Done";
    case "handoff":
      return "Handed on";
    case "max_steps":
      return "Ran out of steps";
    case "stuck":
      return "Stuck";
    default:
      return "Stopped";
  }
}

function troubleOf(view: RunView, agent: AgentNode): Trouble | null {
  if (agent.lastError === null) return null;
  // The reducer keeps the message; the record says whether it changed anything.
  const record = view.errors.findLast((error) => error.agent === agent.name);
  const calm = record !== undefined && changedNothing(record, view);
  return { kind: calm ? "note" : "alarm", message: agent.lastError };
}

function bubbleOf(agent: AgentNode, returning: boolean): Bubble | null {
  if (agent.activity === "calling") {
    const tail = agent.streamedText.replace(/\s+/g, " ").trim();
    // The end of what it is saying, as a ticker shows the latest words.
    return { kind: "thought", text: tail.length > BUBBLE_CHARS ? `…${tail.slice(-BUBBLE_CHARS)}` : tail };
  }
  // An agent reports and completes in the same breath, so "until its next
  // event" would be one event. Its words stay until it asks its model
  // again, or, once it has completed, until the work is back with the sender.
  const fresh = agent.lastMessageSeq !== null && agent.lastMessageSeq > (agent.modelCallSeq ?? 0);
  if (agent.lastMessage !== null && fresh && (agent.completedSeq === null || returning)) {
    return { kind: "speech", text: ellipsise(agent.lastMessage.replace(/\s+/g, " ").trim(), 160) };
  }
  return null;
}

function deskOf(view: RunView, agent: AgentNode, folders: readonly Folder[], own: readonly ToolCall[]): Desk {
  const trouble = troubleOf(view, agent);
  const face = faceOf(agent, trouble);
  const slips = slipsFor(view, agent);
  const family = face === "tool" && agent.currentTool !== null ? toolInfo(agent.currentTool).family : null;
  const results = own.filter((call) => call.result !== null).length;
  const calls = own.length;
  const documents = writtenFiles({ toolCalls: own });
  const stateLabel =
    agent.activity === "completed"
      ? completionLabel(agent.finishedReason)
      : family !== null
        ? capitalise(FAMILY_LABEL[family])
        : STATE_LABEL[face];
  // What it said since its latest model call stays up while it works, and,
  // once it has finished, while its folder is on the way back.
  const returning = folders.some((folder) => folder.to === agent.name && folder.phase === "returning");
  const role = agent.role === null ? "" : ` ${agent.role.replace(/\.$/, "")}.`;
  const model = agent.model === null ? null : modelLabel(agent.model);
  return {
    name: agent.name,
    lead: agent.name === SUPERVISOR,
    ghost: false,
    role: agent.role,
    model,
    activity: agent.activity,
    face,
    family,
    stateLabel,
    activityLabel: activityLabel(agent),
    bubble: bubbleOf(agent, returning),
    slips,
    trouble,
    quiet: (face === "dot" || face === "tick") && trouble === null && !slips.some((slip) => slip.stamp !== null && REFUSALS.has(slip.stamp.kind)),
    results,
    documents,
    refusals: view.denials.filter((denial) => denial.agent === agent.name).length,
    inbox: folders.filter((folder) => folder.to === agent.name && folder.phase === "open"),
    returned: folders.filter((folder) => folder.kind === "delegated" && folder.from === agent.name && folder.phase === "returned").length,
    steps: agent.steps,
    maxSteps: agent.maxSteps,
    costMicros: agent.costMicros,
    latestSeq: agent.latestSeq,
    accessibleName: `${agent.name} ${stateLabel}${model === null ? "" : ` ${model}`}.${role} ${plural(calls, "tool call")}.${
      documents.length === 0 ? "" : ` Wrote ${plural(documents.length, "file")}.`
    }`,
  };
}

const capitalise = (words: string): string => words.charAt(0).toLocaleUpperCase() + words.slice(1);

function ghostDesk(name: string): Desk {
  return {
    name,
    lead: false,
    ghost: true,
    role: null,
    model: null,
    activity: "spawned",
    face: "dot",
    family: null,
    stateLabel: "Not started",
    activityLabel: "not started",
    bubble: null,
    slips: [],
    trouble: null,
    quiet: true,
    results: 0,
    documents: [],
    refusals: 0,
    inbox: [],
    returned: 0,
    steps: 0,
    maxSteps: null,
    costMicros: 0,
    latestSeq: 0,
    accessibleName: `${name} Not started. Work was handed to it and nobody took it up.`,
  };
}

/**
 * Worker desks and empty chairs in the order each name first appeared, as a
 * handoff's target or as an agent. A name keeps its place when others arrive
 * after it, so a placed desk never moves.
 */
function deskOrder(view: RunView): string[] {
  const first = new Map<string, number>();
  for (const handoff of view.handoffs) {
    if (!first.has(handoff.to)) first.set(handoff.to, handoff.seq);
  }
  for (const name of view.agentOrder) {
    const seq = view.agents[name]?.seq ?? 0;
    first.set(name, Math.min(first.get(name) ?? seq, seq));
  }
  first.delete(SUPERVISOR);
  return [...first.entries()].sort((left, right) => left[1] - right[1]).map(([name]) => name);
}

// --- the room -----------------------------------------------------------------

const RISK_ORDER = ["low", "medium", "high"];

function receptionOf(view: RunView): Reception {
  const waiting = pendingApprovals(view);
  const source = view.origin?.channel ?? view.approvalPolicy?.origin ?? "window";
  const origin =
    view.origin !== null
      ? `From ${capitalise(view.origin.channel)}`
      : capitalise(runOriginLabel(view.approvalPolicy?.origin ?? null) ?? "started by you");
  const sender = view.origin === null ? null : (view.origin.identity ?? view.origin.displayName);
  const risks = waiting.map((approval) => approval.risk).sort((left, right) => RISK_ORDER.indexOf(right) - RISK_ORDER.indexOf(left));
  return { origin, source, sender, waiting: waiting.length, waitingRisk: risks[0] ?? null };
}

function seconds(from: string | null, to: string | null): number | null {
  if (from === null || to === null) return null;
  const span = Date.parse(to) - Date.parse(from);
  return Number.isFinite(span) ? Math.max(0, Math.round(span / 1000)) : null;
}

function announcementOf(view: RunView, desks: readonly Desk[]): OfficeModel["announcement"] {
  if (view.status === "completed" || view.status === "failed" || view.status === "cancelled") {
    return { key: `run-${view.status}`, text: `The run ${view.status === "cancelled" ? "was cancelled" : view.status}.` };
  }
  const finished = desks
    .filter((desk) => desk.activity === "completed" && !desk.ghost)
    .sort((left, right) => right.latestSeq - left.latestSeq)[0];
  if (finished === undefined) return null;
  return {
    key: `done-${finished.name}-${String(finished.latestSeq)}`,
    text: finished.face === "tick" ? `${finished.name} finished.` : `${finished.name} stopped: ${finished.stateLabel.toLocaleLowerCase()}.`,
  };
}

/** The room at the cursor. */
export function officeOf(view: RunView): OfficeModel {
  const folders = foldersOf(view);
  const leadAgent = view.agents[SUPERVISOR];
  // Each agent's calls, found in one pass rather than once per desk per fact.
  const callsOf = new Map<string, ToolCall[]>();
  for (const call of view.toolCalls) {
    const list = callsOf.get(call.agent);
    if (list === undefined) callsOf.set(call.agent, [call]);
    else list.push(call);
  }
  const own = (name: string): readonly ToolCall[] => callsOf.get(name) ?? [];
  const lead = leadAgent === undefined ? null : deskOf(view, leadAgent, folders, own(leadAgent.name));
  const desks = deskOrder(view).map((name) => {
    const agent = view.agents[name];
    return agent === undefined ? ghostDesk(name) : deskOf(view, agent, folders, own(name));
  });
  const everyone = lead === null ? desks : [lead, ...desks];
  // A run that is over has no work to follow, so the camera shows the
  // room it left, and "Follow the work" says so by showing the same.
  const over = view.status === "completed" || view.status === "failed" || view.status === "cancelled";
  const focus = over
    ? null
    : (everyone.filter((desk) => !desk.ghost).sort((left, right) => right.latestSeq - left.latestSeq)[0]?.name ?? null);
  const limit = view.limits?.max_run_seconds;

  return {
    lit: view.startedTs !== null || view.status !== "pending",
    dimmed: view.status === "cancelled" || view.status === "paused",
    status: view.status,
    lead,
    desks,
    folders: folders.filter((folder) => folder.phase === "arriving" || folder.phase === "returning"),
    reception: receptionOf(view),
    board: {
      goal: view.goal,
      status: view.status,
      statusLabel: STATUS_LABEL[view.status],
      claim: view.claim,
      memoryPath: view.memoryPath,
      documents: writtenFiles(view),
      unrecognised: [...new Set(view.unrecognised)],
    },
    library: view.knowledge,
    clock: {
      elapsedSeconds: seconds(view.startedTs, view.latestTs),
      limitSeconds: typeof limit === "number" && limit > 0 ? limit : null,
    },
    meter: {
      costMicros: view.costMicros,
      level: view.budgetExceeded ? "over" : view.budget !== null ? "warn" : "ok",
      percent: view.budget?.percent ?? null,
      announcement: view.budgetExceeded
        ? "The monthly limit is reached."
        : view.budget !== null
          ? "Spending is close to the monthly limit."
          : null,
    },
    focus,
    announcement: announcementOf(view, everyone),
  };
}
