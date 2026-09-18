import type { Event } from "@agentspace/schemas";
import { useEffect, useMemo, useRef, useState } from "react";

import { clockTime, eventFamily } from "../lib/format";
import { captureText, sentenceFor } from "../state/describe";

import { Markdown } from "./Markdown";

/**
 * The event log panel: the raw log, which is what you check the reduced view
 * against. Filters, opened rows and scroll position are component state
 * (facts about the person, not the run). Tokens are hidden by default; every
 * row is a sentence with the raw type as a chip beside it; a row opens to its
 * whole payload. Only the rows in view are in the DOM: rows are a fixed
 * height, and an opened payload is measured once it renders.
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
  /** Save an event's prose as a vault note; absent where no vault is reachable. */
  onCapture?: ((event: Event) => void) | undefined;
}

export function EventLog({
  events,
  cursor,
  agents,
  selectedAgent,
  onSelectAgent,
  onCapture,
}: EventLogProps) {
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

  // A filter value the current rows do not contain is "all", not a filter that hides everything.
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
    // Against the spacer's height and the element's live height, so "at the
    // end" agrees with the row arithmetic and does not lag by a render.
    const height = element.clientHeight || viewport.height;
    const remaining = total - element.scrollTop - height;
    setAtEnd(remaining < 4);
    setViewport({ scrollTop: element.scrollTop, height });
  };

  // The rows overlapping the viewport, plus overscan. Following the tail, the
  // position is the end; otherwise it is clamped, since a filter can shorten the list.
  const scrollTop = atEnd
    ? Math.max(0, total - viewport.height)
    : Math.max(0, Math.min(viewport.scrollTop, total - viewport.height));
  const firstVisible = rowAt(offsets, scrollTop);
  const lastVisible = rowAt(offsets, scrollTop + viewport.height);
  const start = Math.max(0, firstVisible - OVERSCAN);
  const end = Math.min(rows.length, lastVisible + 1 + OVERSCAN);

  const measured = (seq: number, element: HTMLDivElement | null) => {
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
                  <div
                    className="log__detail"
                    ref={(element) => {
                      measured(event.seq, element);
                    }}
                  >
                    {/* The prose an agent wrote, read as it was written; the
                        payload below it is what a bug report needs. */}
                    {captureText(event) !== null && (
                      <div className="log__prose" data-testid="log-prose">
                        <Markdown source={captureText(event) ?? ""} className="md--compact" />
                        {onCapture !== undefined && (
                          <button
                            type="button"
                            className="button button--small log__capture"
                            onClick={() => {
                              onCapture(event);
                            }}
                          >
                            Save as note
                          </button>
                        )}
                      </div>
                    )}
                    <pre className="log__payload" data-testid="log-payload">
                      {JSON.stringify(event.payload ?? {}, null, 2)}
                    </pre>
                  </div>
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
 * over the row starts. `offsets` has one more entry than there are rows (the
 * total), so a `y` past the end lands on the last row.
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
