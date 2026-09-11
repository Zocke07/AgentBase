import type { Event } from "@agentspace/schemas";
import { useEffect, useMemo, useRef, useState } from "react";

import { clockTime, eventFamily } from "../lib/format";
import { sentenceFor } from "../state/describe";


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
 * **Every row is a sentence, with the raw type beside it.** The sentence is
 * `sentenceFor(event)` from the reducer's module — a pure function of the
 * event, so it is identical live and on replay — and the raw `tool.denied`
 * stays as a chip because it is what a bug report, and the type filter, need.
 *
 * **A row opens to its whole payload.** A one-liner cannot show a tool result
 * or the message list an `llm.request` carried, and those are precisely what
 * a person checking the reduced view against the log needs to read.
 *
 * **Only the rows in view are in the DOM.** A long run is thousands of
 * events, and rendering every one — then re-rendering every one on each
 * arriving token — is what made the frontend pass leave windowing as the
 * one thing it did not measure. Rows are a fixed height, so where a row sits
 * is arithmetic; an opened payload is the one variable, measured once it
 * renders and added to everything below it. The windowing is a fact about
 * the viewport, not about the log: the same rows are rendered for the same
 * scroll position live and on replay, which is what keeps the identity test
 * honest about the part of the log that is on screen.
 */

/** A collapsed row's height, in CSS pixels. Matches `.log__row` in the stylesheet. */
const ROW_PX = 30;
/** Rows rendered beyond the viewport on each side, so a scroll never shows a gap. */
const OVERSCAN = 12;

export interface EventLogProps {
  events: readonly Event[];
  /** How many events are applied. Rows beyond this are the un-scrubbed future. */
  cursor: number;
  agents: readonly string[];
  selectedAgent: string | null;
  onSelectAgent: (agent: string | null) => void;
}

export function EventLog({ events, cursor, agents, selectedAgent, onSelectAgent }: EventLogProps) {
  const [chosenType, setType] = useState<string>("all");
  const [showTokens, setShowTokens] = useState(false);
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<ReadonlySet<number>>(() => new Set());
  // The height an opened row's payload turned out to have, by `seq`. Zero
  // until it has rendered once; the row below it moves down when it has.
  const [payloadHeights, setPayloadHeights] = useState<ReadonlyMap<number, number>>(() => new Map());
  const scroller = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ scrollTop: 0, height: 0 });
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
            `${event.type} ${event.agent_id ?? ""} ${sentenceFor(event)}`.toLowerCase().includes(needle),
        ),
    [applied, showTokens, selectedAgent, type, families, needle],
  );

  // Where each row starts. A prefix sum, because an opened payload above a
  // row pushes it down by however tall the payload turned out to be.
  const { offsets, total } = useMemo(() => {
    const starts = new Array<number>(rows.length + 1);
    let y = 0;
    for (const [index, event] of rows.entries()) {
      starts[index] = y;
      y += ROW_PX + (opened.has(event.seq) ? (payloadHeights.get(event.seq) ?? 0) : 0);
    }
    starts[rows.length] = y;
    return { offsets: starts, total: y };
  }, [rows, opened, payloadHeights]);

  // The viewport's size, from the element itself. Zero until measured, which
  // renders the first few rows and nothing more; the observer fires at once.
  useEffect(() => {
    const element = scroller.current;
    if (element === null) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined) return;
      setViewport((current) => ({ ...current, height: entry.contentRect.height }));
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  // Follow the tail while the reader is at it.
  useEffect(() => {
    const element = scroller.current;
    if (element === null || !atEnd) return;
    element.scrollTop = total;
  }, [total, atEnd]);

  const onScroll = () => {
    const element = scroller.current;
    if (element === null) return;
    // Measured against the spacer's own height rather than `scrollHeight`, so
    // the answer is the same one the row arithmetic below is working from —
    // and against the element's live height rather than the remembered one,
    // which can lag it by a render on the first scroll and read "not at the
    // end" of a list that is.
    const height = element.clientHeight || viewport.height;
    const remaining = total - element.scrollTop - height;
    setAtEnd(remaining < 4);
    setViewport({ scrollTop: element.scrollTop, height });
  };

  // The rows whose extent overlaps the viewport, plus the overscan. While
  // following the tail the position *is* the end, whatever the last scroll
  // event said; otherwise a filter that shortened the list can leave the
  // remembered position past its end, so it is clamped before it is used.
  const scrollTop = atEnd
    ? Math.max(0, total - viewport.height)
    : Math.max(0, Math.min(viewport.scrollTop, total - viewport.height));
  const firstVisible = rowAt(offsets, scrollTop);
  const lastVisible = rowAt(offsets, scrollTop + viewport.height);
  const start = Math.max(0, firstVisible - OVERSCAN);
  const end = Math.min(rows.length, lastVisible + 1 + OVERSCAN);

  const measured = (seq: number, element: HTMLPreElement | null) => {
    if (element === null) return;
    const height = element.offsetHeight;
    if (height === 0 || payloadHeights.get(seq) === height) return;
    setPayloadHeights((current) => new Map(current).set(seq, height));
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

      <div className="log__rows" ref={scroller} onScroll={onScroll}>
        <ol className="log__list" style={{ height: `${String(total)}px` }}>
        {rows.slice(start, end).map((event, offset) => {
          const isOpen = opened.has(event.seq);
          return (
            <li
              key={event.seq}
              className={`log__item log__item--${eventFamily(event.type)}`}
              style={{ transform: `translateY(${String(offsets[start + offset] ?? 0)}px)` }}
            >
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
                {/* The sentence first, the raw type beside it as a chip: the
                    sentence is what a person reads, the type is what a bug
                    report needs. Both come from the same event. */}
                <span className="log__sentence">{sentenceFor(event)}</span>
                <span className="log__type">{event.type}</span>
              </button>
              {isOpen && (
                <pre
                  className="log__payload"
                  data-testid="log-payload"
                  ref={(element) => {
                    measured(event.seq, element);
                  }}
                >
                  {JSON.stringify(event.payload ?? {}, null, 2)}
                </pre>
              )}
            </li>
          );
        })}
        {rows.length === 0 && <li className="log__empty">No events match this filter.</li>}
        </ol>
      </div>

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

/**
 * The index of the row that contains vertical position `y`, by binary search
 * over the row starts. `offsets` has one more entry than there are rows — the
 * total — so a `y` past the end lands on the last row.
 */
function rowAt(offsets: readonly number[], y: number): number {
  let low = 0;
  let high = offsets.length - 2;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if ((offsets[mid] ?? 0) <= y) low = mid;
    else high = mid - 1;
  }
  return Math.max(0, low);
}
