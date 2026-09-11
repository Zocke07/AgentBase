import type { Event } from "@agentspace/schemas";
import { useEffect, useMemo, useRef, useState } from "react";

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
 * The same goes for which rows are opened and where the list is scrolled.
 *
 * **Tokens are hidden by default.** 232 of a real run's 288 events were
 * `llm.token`; they are what the agent detail shows as text, and in the log
 * they buried everything else. The toggle says how many there are.
 *
 * **A row opens to its whole payload.** A one-liner cannot show a tool result
 * or the message list an `llm.request` carried, and those are precisely what
 * a person checking the reduced view against the log needs to read.
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
    case "channel.inbound": {
      // The identity is the internal name the sender's external id resolved
      // to. The display name is the sender's own and is shown after it, never
      // instead of it — a chat user can rename themselves to anything.
      const displayName = read("display_name");
      const who = displayName === null ? "" : ` (${displayName})`;
      return `${read("channel") ?? "?"} · ${read("identity") ?? "?"}${who} — ${ellipsise(
        read("text") ?? "",
        90,
      )}`;
    }
    case "channel.outbound":
      return `${read("channel") ?? "?"} · ${shown("edits")} edits to ${read("thread_ref") ?? "?"}`;
    default:
      return "";
  }
}

export function EventLog({ events, cursor, agents, selectedAgent, onSelectAgent }: EventLogProps) {
  const [chosenType, setType] = useState<string>("all");
  const [showTokens, setShowTokens] = useState(false);
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<ReadonlySet<number>>(() => new Set());
  const list = useRef<HTMLOListElement>(null);
  // Whether the list is scrolled to its end. New rows keep it there; a person
  // who scrolled up to read is left where they are, with a way back down.
  const [atEnd, setAtEnd] = useState(true);

  const applied = useMemo(() => events.slice(0, cursor), [events, cursor]);

  const { families, types, tokenCount } = useMemo(() => {
    const seenTypes = new Set<string>();
    let tokens = 0;
    for (const event of applied) {
      seenTypes.add(event.type);
      if (event.type === "llm.token") tokens += 1;
    }
    const sorted = [...seenTypes].sort((left, right) => left.localeCompare(right));
    const familyNames = [...new Set(sorted.map(eventFamily))];
    return { families: familyNames, types: sorted, tokenCount: tokens };
  }, [applied]);

  // The filter outlives the log it was chosen against: switch to a run with no
  // `channel.*` rows, or scrub to before the first `tool.*`, and a filter on
  // that type hides every row behind a select showing nothing. A value the
  // current rows do not contain is not a filter, it is "all".
  const type =
    chosenType === "all" || types.includes(chosenType) || families.includes(chosenType)
      ? chosenType
      : "all";

  const needle = search.trim().toLowerCase();
  const rows = useMemo(
    () =>
      applied
        .filter((event) => showTokens || event.type !== "llm.token")
        .filter((event) => selectedAgent === null || event.agent_id === selectedAgent)
        .filter(
          (event) =>
            type === "all" ||
            event.type === type ||
            (families.includes(type) && eventFamily(event.type) === type),
        )
        .filter(
          (event) =>
            needle === "" ||
            `${event.type} ${event.agent_id ?? ""} ${describe(event)}`.toLowerCase().includes(needle),
        ),
    [applied, showTokens, selectedAgent, type, families, needle],
  );

  // Follow the tail while the reader is at it.
  useEffect(() => {
    const element = list.current;
    if (element === null || !atEnd) return;
    element.scrollTop = element.scrollHeight;
  }, [rows.length, atEnd]);

  const onScroll = () => {
    const element = list.current;
    if (element === null) return;
    const remaining = element.scrollHeight - element.scrollTop - element.clientHeight;
    setAtEnd(remaining < 4);
  };

  const toggle = (seq: number) => {
    setOpened((current) => {
      const next = new Set(current);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

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
            value={type}
            onChange={(changed) => {
              setType(changed.target.value);
            }}
          >
            <option value="all">all types</option>
            {families.map((family) => (
              <optgroup key={family} label={`${family}.*`}>
                <option value={family}>{family}.* (all)</option>
                {types
                  .filter((name) => eventFamily(name) === family)
                  .map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>

        <label className="log__search">
          <span className="log__filter-label">Find</span>
          <input
            type="search"
            value={search}
            placeholder="text in any row"
            onChange={(changed) => {
              setSearch(changed.target.value);
            }}
          />
        </label>

        <label className="log__toggle">
          <input
            type="checkbox"
            checked={showTokens}
            onChange={(changed) => {
              setShowTokens(changed.target.checked);
            }}
          />
          <span>show tokens ({tokenCount})</span>
        </label>

        <span className="log__count">
          {rows.length} of {cursor} events
        </span>
      </header>

      <ol className="log__rows" ref={list} onScroll={onScroll}>
        {rows.map((event) => {
          const isOpen = opened.has(event.seq);
          return (
            <li key={event.seq} className={`log__item log__item--${eventFamily(event.type)}`}>
              <button
                type="button"
                className={`log__row log__row--${eventFamily(event.type)}${isOpen ? " log__row--open" : ""}`}
                aria-expanded={isOpen}
                onClick={() => {
                  toggle(event.seq);
                }}
              >
                <span className="log__seq">{event.seq}</span>
                <span className="log__time">{clockTime(event.ts)}</span>
                <span className="log__agent">{event.agent_id ?? "—"}</span>
                <span className="log__type">{event.type}</span>
                <span className="log__detail">{describe(event)}</span>
              </button>
              {isOpen && (
                <pre className="log__payload" data-testid="log-payload">
                  {JSON.stringify(event.payload ?? {}, null, 2)}
                </pre>
              )}
            </li>
          );
        })}
        {rows.length === 0 && <li className="log__empty">No events match this filter.</li>}
      </ol>

      {!atEnd && (
        <button
          type="button"
          className="button button--small log__newest"
          onClick={() => {
            setAtEnd(true);
          }}
        >
          ↓ newest
        </button>
      )}
    </section>
  );
}
