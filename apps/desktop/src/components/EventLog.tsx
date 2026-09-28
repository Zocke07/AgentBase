import type { Event } from "@agentbase/schemas";
import { useEffect, useMemo, useRef, useState } from "react";

import { clockTime, eventFamily } from "../lib/format";
import { captureText, sentenceFor } from "../state/describe";

import { Markdown } from "./Markdown";

/**
 * Raw event-log panel for checking reduced views. Filters, opened rows, and
 * scroll position are user state. Hide tokens by default; rows show sentence,
 * raw-type chip, and expandable payload. Virtualize fixed-height rows and
 * measure opened payloads once.
 */

/** Collapsed row height in CSS pixels; matches `.log__row`. */
const ROW_PX = 30;
/** Overscan rows per viewport edge, preventing scroll gaps. */
const OVERSCAN = 12;

export interface EventLogProps {
  events: readonly Event[];
  /** Applied events; later rows are unscrubbed future. */
  cursor: number;
  agents: readonly string[];
  selectedAgent: string | null;
  onSelectAgent: (agent: string | null) => void;
  /** Save event prose as vault note; absent without vault. */
  onCapture?: ((event: Event) => void) | undefined;
  /**
   * Folded to one line naming the latest step. The rows stay mounted behind
   * `hidden`, so filters, opened rows and the reading position survive.
   */
  collapsed?: boolean;
  /** Offer the fold control; absent, the log is always open. */
  onCollapsedChange?: ((collapsed: boolean) => void) | undefined;
}

/** The rows' element id, for the fold control's `aria-controls`. Fixed rather
    than `useId`, which differs between two renders the replay test compares. */
const ROWS_ID = "event-log-rows";

export function EventLog({
  events,
  cursor,
  agents,
  selectedAgent,
  onSelectAgent,
  onCapture,
  collapsed = false,
  onCollapsedChange,
}: EventLogProps) {
  const [chosenType, setType] = useState<string>("all");
  const [showTokens, setShowTokens] = useState(false);
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<ReadonlySet<number>>(() => new Set());
  // Opened payload heights by `seq`; zero until first render.
  const [payloadHeights, setPayloadHeights] = useState<ReadonlyMap<number, number>>(() => new Map());
  const scroller = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ scrollTop: 0, height: 0 });
  // Tail-follow only when already at end; preserve reading position otherwise.
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

  // The folded log's one line: the newest step, never a streamed token.
  const latest = useMemo(() => applied.findLast((event) => event.type !== "llm.token") ?? null, [applied]);

  // Missing filter values become `all`, not an empty list.
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

  // Prefix starts account for variable opened-payload heights.
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

  // Element-derived viewport; initial zero renders few rows until observer fires.
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

  // Follow tail while reader remains there. A hidden element loses its
  // scroll offset, so unfolding puts the reader back where they were.
  useEffect(() => {
    const element = scroller.current;
    if (element === null || collapsed) return;
    if (atEnd) element.scrollTop = total;
    else if (element.scrollTop !== viewport.scrollTop) element.scrollTop = viewport.scrollTop;
    // The reading position is only restored on unfolding, not chased on scroll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total, atEnd, collapsed]);

  const onScroll = () => {
    const element = scroller.current;
    if (element === null) return;
  // Use spacer and live element heights to avoid a render-lagged tail state.
    const height = element.clientHeight || viewport.height;
    const remaining = total - element.scrollTop - height;
    setAtEnd(remaining < 4);
    setViewport({ scrollTop: element.scrollTop, height });
  };

  // Compute visible plus overscan rows; clamp after filters shorten the list.
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
    <section className={`log${collapsed ? " log--collapsed" : ""}`} data-testid="event-log">
      <header className="log__filters">
        {onCollapsedChange !== undefined && (
          <button
            type="button"
            className="log__fold"
            aria-expanded={!collapsed}
            aria-controls={ROWS_ID}
            title={collapsed ? "Show every step of the run" : "Hide the steps and keep only the latest one"}
            onClick={() => {
              onCollapsedChange(!collapsed);
            }}
          >
            <span className="log__fold-icon" aria-hidden="true" />
            Event log
          </button>
        )}
        {collapsed ? (
          <>
            <span className="log__latest" data-testid="log-latest" title={latest === null ? undefined : sentenceFor(latest)}>
              {latest === null ? "Nothing has happened yet." : sentenceFor(latest)}
            </span>
            <span className="log__count">
              {cursor} event{cursor === 1 ? "" : "s"}
            </span>
          </>
        ) : (
          <>
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
          </>
        )}
      </header>

      <div className="log__rows" id={ROWS_ID} ref={scroller} onScroll={onScroll} hidden={collapsed}>
        <ol className="log__list" style={{ height: `${String(total)}px` }}>
          {/* Folded, the spacer keeps its height and no row is built. */}
          {(collapsed ? [] : rows.slice(start, end)).map((event, offset) => {
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
          {rows.length === 0 && !collapsed && <li className="log__empty">No events match this filter.</li>}
        </ol>
      </div>

      {!atEnd && !collapsed && (
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
 * Binary-search row containing `y`. `offsets` includes total height, so values
 * past end resolve to final row.
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
