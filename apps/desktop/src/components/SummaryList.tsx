import type { NoteSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "../lib/api";
import { whenLabel } from "../lib/format";
import { shortDay } from "../state/journal";
import { SUMMARY_GROUPS, fileNoun, summaryItems, type SummaryItem } from "../state/sections";
import { useFetched } from "../state/useFetched";

/**
 * Knowledge's User Summary: what the space's runs and its people wrote to be
 * read, grouped and newest first, each opening in Preview. The raw data,
 * settings and records behind them stay under Technical Details.
 */

export interface SummaryListProps {
  spaceId: string;
  /** The vault index's notes; null until it has been read. */
  notes: readonly NoteSummary[] | null;
  /** Bumped when files may have changed; rereads the workbooks and charts. */
  reloadNonce?: number | undefined;
  /** The path open beside the list. */
  activePath: string | null;
  onOpen: (item: SummaryItem) => void;
  /** Read every dated report as one page. */
  onReadAll: () => void;
  /** Start something new: a note, or a chart, dashboard or diagram from its template. */
  onNew: (what: NewKind) => void;
}

export type NewKind = "note" | "chart" | "dashboard" | "diagram";

/** A group shows this many until asked for the rest. */
const SHOWN = 5;

const NEW_LABELS: Readonly<Record<NewKind, string>> = {
  note: "Note",
  chart: "Chart",
  dashboard: "Dashboard",
  diagram: "Diagram",
};

export function SummaryList({ spaceId, notes, reloadNonce = 0, activePath, onOpen, onReadAll, onNew }: SummaryListProps) {
  const load = useCallback(() => api.listFiles(spaceId), [spaceId]);
  const files = useFetched(load, null);
  const { reload } = files;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);
  const [query, setQuery] = useState("");
  // Groups the person opened past their first few.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const items = useMemo(() => summaryItems(notes ?? [], files.data?.files ?? []), [notes, files.data]);
  const wanted = query.trim().toLocaleLowerCase();
  const matching =
    wanted === "" ? items : items.filter((item) => `${item.title} ${item.path}`.toLocaleLowerCase().includes(wanted));
  const loaded = notes !== null && (files.data !== null || files.error !== null);

  return (
    <div className="summary" data-testid="summary-list">
      <div className="summary__tools">
        <label>
          <span className="sr-only">Find a result</span>
          <input
            type="search"
            value={query}
            placeholder="Find a result"
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
        </label>
        <select
          aria-label="Create something new"
          value=""
          onChange={(event) => {
            const chosen = event.target.value as NewKind | "";
            if (chosen !== "") onNew(chosen);
          }}
        >
          <option value="">New…</option>
          {(Object.keys(NEW_LABELS) as NewKind[]).map((kind) => (
            <option key={kind} value={kind}>
              {NEW_LABELS[kind]}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="link summary__read-all" onClick={onReadAll}>
        All reports as one page
      </button>

      {files.error !== null && (
        <p className="field-error" role="alert">
          Workbooks and charts could not be listed: {files.error}{" "}
          <button type="button" className="link" onClick={reload}>
            Try again
          </button>
        </p>
      )}
      {!loaded && items.length === 0 && <p className="knowledge__empty">Reading this space…</p>}
      {loaded && items.length === 0 && (
        <div className="summary__empty">
          <p>Nothing to read yet.</p>
          <p>
            Decisions, portfolio reviews, market alerts and the monthly forecast workbook appear here as the daily
            pipeline writes them. The raw data and settings behind them are under Technical Details.
          </p>
        </div>
      )}
      {items.length > 0 && matching.length === 0 && (
        <p className="files__no-match">No results match “{query.trim()}”.</p>
      )}

      {SUMMARY_GROUPS.map((group) => {
        const members = matching.filter((item) => item.group === group);
        if (members.length === 0) return null;
        const open = wanted !== "" || expanded.has(group);
        const shown = open ? members : members.slice(0, SHOWN);
        return (
          <section key={group} className="files__group summary__group" aria-label={group}>
            <div className="files__group-head">
              <h3>{group}</h3>
              <span>{members.length}</span>
            </div>
            <ul className="files__list">
              {shown.map((item) => (
                <li key={item.path}>
                  <button
                    type="button"
                    className={`files__item${activePath === item.path ? " files__item--active" : ""}`}
                    aria-current={activePath === item.path ? "true" : undefined}
                    title={item.path}
                    onClick={() => {
                      onOpen(item);
                    }}
                  >
                    <span className="files__file-icon" aria-hidden="true">
                      {(item.kind === "file" ? fileNoun(item.path) : group).slice(0, 1)}
                    </span>
                    <span className="files__identity">
                      <span className="files__name">{item.title}</span>
                      <span className="files__meta">{meta(item)}</span>
                    </span>
                  </button>
                </li>
              ))}
              {wanted === "" && members.length > SHOWN && (
                <li>
                  <button
                    type="button"
                    className="recent__fold"
                    aria-expanded={open}
                    onClick={() => {
                      setExpanded((current) => {
                        const next = new Set(current);
                        if (next.has(group)) next.delete(group);
                        else next.add(group);
                        return next;
                      });
                    }}
                  >
                    <span className={`tree__chevron${open ? " tree__chevron--open" : ""}`} aria-hidden="true" />
                    {open ? "Show fewer" : `Show all ${String(members.length)}`}
                  </button>
                </li>
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** "Excel workbook · All of October", "Tue, Oct 13", or when an undated note last changed. */
function meta(item: SummaryItem): string {
  const when = item.date === null ? `Updated ${whenLabel(item.updatedAt)}` : shortDay(item.date);
  return item.kind === "file" ? `${fileNoun(item.path)} · ${when}` : when;
}
