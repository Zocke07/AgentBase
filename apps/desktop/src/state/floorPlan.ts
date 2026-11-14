import type { AgentDef, Run, ScheduleResponse, ToolResponse } from "@agentbase/schemas";

import { modelLabel } from "../lib/format";

import type { Desk } from "./office";

/**
 * The Agents section as a floor plan (Phase 20, brief 7.13): each agent
 * definition drawn as a desk at rest, with the office's own figure. It
 * projects the roster, which is API state, not a run's log, so it is not
 * under replay identity (decision D9); it is still pure, so the same roster
 * always draws the same room.
 *
 * An agent the supervisor may not use has its chair pushed in: the desk is
 * drawn empty, as a run's empty chair is, and its words say why.
 */

/**
 * A desk at rest, with nothing on it: the one literal every desk drawn
 * outside a run starts from. The lamp is out (the activity is
 * `completed`): a lit lamp means someone is at work.
 */
export function restDesk(name: string, fields: Partial<Desk> = {}): Desk {
  return {
    name,
    lead: false,
    ghost: false,
    role: null,
    model: null,
    activity: "completed",
    face: "dot",
    family: null,
    stateLabel: "Ready",
    activityLabel: "ready",
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
    accessibleName: name,
    ...fields,
  };
}

export function restingDesk(agent: AgentDef): Desk {
  const available = agent.enabled !== false;
  const stateLabel = available ? "Available" : "Not available";
  return restDesk(agent.name, {
    ghost: !available,
    role: agent.role,
    model: agent.model === undefined || agent.model === null ? null : modelLabel(agent.model),
    stateLabel,
    activityLabel: available ? "available to the supervisor" : "not available to the supervisor",
    maxSteps: agent.max_steps ?? null,
    accessibleName: `${agent.name} ${stateLabel}. ${agent.role}`,
  });
}

export type RiskLevel = "low" | "medium" | "high" | "unknown";

export interface ToolOnDesk {
  readonly name: string;
  readonly risk: RiskLevel;
}

const RISKS: readonly RiskLevel[] = ["high", "medium", "low", "unknown"];

/**
 * The tools an agent may call, riskiest first, each with the risk the
 * sidecar gives it. A tool the sidecar does not list (removed, or not
 * offered in this space) is `unknown`, never assumed safe.
 */
export function toolsOnDesk(agent: AgentDef, tools: readonly ToolResponse[]): ToolOnDesk[] {
  const risk = new Map(tools.map((tool) => [tool.name, tool.risk]));
  return (agent.allowed_tools ?? [])
    .map((name): ToolOnDesk => {
      const given = risk.get(name);
      return { name, risk: given === "low" || given === "medium" || given === "high" ? given : "unknown" };
    })
    .sort((left, right) => RISKS.indexOf(left.risk) - RISKS.indexOf(right.risk) || left.name.localeCompare(right.name));
}

/** "3 tools, 1 high risk": the count in words, so risk never rests on colour. */
export function toolsSummary(tools: readonly ToolOnDesk[]): string {
  if (tools.length === 0) return "No tools";
  const high = tools.filter((tool) => tool.risk === "high").length;
  const count = `${String(tools.length)} tool${tools.length === 1 ? "" : "s"}`;
  return high === 0 ? count : `${count}, ${String(high)} high risk`;
}

// --- Home's office (brief 7.13) -----------------------------------------------

/**
 * Home's desk for a run that is going. Home reads the runs list and opens no
 * event stream, so the desk works at the run's level: its status and
 * whether a question waits on it, never what its agents are doing.
 */
export function runDesk(run: Run, status: Run["status"], waiting: boolean): Desk {
  const name = run.title ?? run.goal;
  const [activity, face, stateLabel] = waiting
    ? (["waiting", "question", "Waiting for you"] as const)
    : status === "running"
      ? (["thinking", "thinking", "Working"] as const)
      : status === "paused"
        ? (["completed", "dot", "Paused"] as const)
        : (["spawned", "dot", "Starting"] as const);
  return restDesk(name, {
    role: run.goal,
    activity,
    face,
    stateLabel,
    activityLabel: stateLabel.toLocaleLowerCase(),
    quiet: !waiting,
    accessibleName: `${name} ${stateLabel}.`,
  });
}

/**
 * The soonest enabled schedule with a time ahead of `now`, for the wall
 * calendar. A time already past (a run missed while the app was closed)
 * is not "next".
 */
export function nextAutomation(schedules: readonly ScheduleResponse[], now: number): { name: string; at: string } | null {
  let soonest: { name: string; at: string } | null = null;
  for (const schedule of schedules) {
    const at = schedule.next_run_at ?? null;
    if (schedule.enabled === false || at === null || Date.parse(at) <= now) continue;
    if (soonest === null || Date.parse(at) < Date.parse(soonest.at)) soonest = { name: schedule.name, at };
  }
  return soonest;
}
