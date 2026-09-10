import type { Event } from "@agentspace/schemas";
import { useMemo, useState } from "react";

import { clockTime, ellipsise, eventFamily, summariseArgs } from "../lib/format";
import { display, flag, record, text } from "../lib/payload";


/**
 * The event log panel — §5 Phase 7's "Event log panel, filterable by agent and
 * event type".
 *
 * This renders the raw log rather than the reduced view, because its job is to
 * be the thing you check the reduced view *against*. When a run claims it saved
 * a file, this is where you look to see that no `tool.called` for a file tool
 * ever happened.
 *
 * The filters are component state, not run state. That is deliberate and it is
 * the one place this file departs from "everything comes from the log": which
 * rows a person is looking at is a fact about the person, not about the run, and
 * putting it in `RunView` would make the same log fold to different states.
 */

export interface EventLogProps {
  events: readonly Event[];
  /** How many events are applied. Rows beyond this are the un-scrubbed future. */
  cursor: number;
  agents: readonly string[];
  selectedAgent: string | null;
  onSelectAgent: (agent: string | null) => void;
}

/** A short, human rendering of one event's payload. */
function describe(event: Event): string {
  const payload = event.payload ?? {};
  const read = (key: string): string | null => text(payload, key);
  const shown = (key: string): string => display(payload, key);

  switch (event.type) {
    case "run.started":
      return read("goal") ?? "";
    case "run.completed":
      return read("summary") ?? "";
    case "run.failed":
    case "run.cancelled":
      return read("reason") ?? "";
    case "agent.spawned":
      return read("role") ?? "";
    case "agent.thinking":
      return `step ${shown("step")}`;
    case "agent.message":
      return ellipsise(read("text") ?? "", 120);
    case "agent.handoff":
      return `→ ${read("to") ?? "?"}: ${ellipsise(read("task") ?? "", 90)}`;
    case "agent.completed":
      return `${read("reason") ?? "done"} after ${shown("steps")} steps`;
    case "llm.request":
      return `${read("provider") ?? "?"} · ${read("model") ?? "?"}`;
    case "llm.token":
      return ellipsise(read("text") ?? "", 120);
    case "llm.response":
      return `${shown("input_tokens")} in / ${shown("output_tokens")} out · ${read("stop_reason") ?? "?"}`;
    case "llm.error":
    case "tool.error":
      return ellipsise(read("error") ?? "", 120);
    case "tool.requested":
    case "tool.called":
      return `${read("tool") ?? "?"}(${summariseArgs(record(payload, "args"))})`;
    case "tool.approved":
      return `${read("tool") ?? "?"}${flag(payload, "automatic") ? " · by policy" : " · by you"}`;
    case "tool.denied": {
      // `blocked_by` is what separates an agent probing the workspace boundary
      // from a person declining a routine write. CLAUDE.md is explicit that a
      // log which collapsed the two would render them identically.
      const blockedBy = read("blocked_by");
      const by = blockedBy === null ? "" : ` [${blockedBy}]`;
      return `${read("tool") ?? "?"}${by} — ${ellipsise(read("reason") ?? "", 100)}`;
    }
    case "tool.result":
      return `${read("tool") ?? "?"} → ${ellipsise(read("result") ?? "", 100)}`;
    case "approval.requested":
      return ellipsise(read("prompt") ?? "", 120);
    case "approval.resolved":
      return `${read("status") ?? "?"}${flag(payload, "automatic") ? " (automatic)" : ""}`;
    case "budget.warning":
    case "budget.exceeded":
      return read("reason") ?? "";
    default:
      return "";
  }
}

export function EventLog({ events, cursor, agents, selectedAgent, onSelectAgent }: EventLogProps) {
  const [family, setFamily] = useState<string>("all");

  const families = useMemo(() => {
    const seen = new Set<string>();
    for (const event of events.slice(0, cursor)) seen.add(eventFamily(event.type));
    return [...seen].sort((left, right) => left.localeCompare(right));
  }, [events, cursor]);

  const rows = useMemo(
    () =>
      events
        .slice(0, cursor)
        .filter((event) => selectedAgent === null || event.agent_id === selectedAgent)
        .filter((event) => family === "all" || eventFamily(event.type) === family),
    [events, cursor, selectedAgent, family],
  );

  return (
    <section className="log" data-testid="event-log">
      <header className="log__filters">
        <label>
          <span className="log__filter-label">Agent</span>
          <select
            value={selectedAgent ?? "all"}
            onChange={(changed) => {
              onSelectAgent(changed.target.value === "all" ? null : changed.target.value);
            }}
          >
            <option value="all">all agents</option>
            {agents.map((agent) => (
              <option key={agent} value={agent}>
                {agent}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span className="log__filter-label">Type</span>
          <select
            value={family}
            onChange={(changed) => {
              setFamily(changed.target.value);
            }}
          >
            <option value="all">all types</option>
            {families.map((name) => (
              <option key={name} value={name}>
                {name}.*
              </option>
            ))}
          </select>
        </label>

        <span className="log__count">
          {rows.length} of {cursor} events
        </span>
      </header>

      <ol className="log__rows">
        {rows.map((event) => (
          <li key={event.seq} className={`log__row log__row--${eventFamily(event.type)}`}>
            <span className="log__seq">{event.seq}</span>
            <span className="log__time">{clockTime(event.ts)}</span>
            <span className="log__agent">{event.agent_id ?? "—"}</span>
            <span className="log__type">{event.type}</span>
            <span className="log__detail">{describe(event)}</span>
          </li>
        ))}
        {rows.length === 0 && <li className="log__empty">No events match this filter.</li>}
      </ol>
    </section>
  );
}
