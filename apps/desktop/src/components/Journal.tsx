import { useEffect, useMemo, useRef, useState } from "react";

import * as api from "../lib/api";
import { whenLabel } from "../lib/format";
import { dayHeading, monthHeading, shortDay, type JournalDay, type JournalEntry } from "../state/journal";

import { Markdown } from "./Markdown";

/**
 * The Journal's two halves: the dates down the browser, and every report on
 * one page beside it, newest first. Nothing here writes: each report stays
 * its own file, and the page only reads them in order.
 */

/** A date picked in the index; the nonce tells a second pick of it apart. */
export interface JournalFocus {
  date: string;
  nonce: number;
}

/** Dates drawn at once; older ones follow when asked for. */
const DATES_PER_PAGE = 7;

export interface JournalIndexProps {
  days: readonly JournalDay[];
  /** The kinds present, offered as a filter when there is more than one. */
  kinds: readonly string[];
  kind: string | null;
  onKind: (kind: string | null) => void;
  current: string | null;
  onPick: (date: string) => void;
}

export function JournalIndex({ days, kinds, kind, onKind, current, onPick }: JournalIndexProps) {
  const months: { month: string; days: JournalDay[] }[] = [];
  for (const day of days) {
    const month = day.date.slice(0, 7);
    const last = months.at(-1);
    if (last?.month === month) last.days.push(day);
    else months.push({ month, days: [day] });
  }
  return (
    <div className="journal-index" data-testid="journal-index">
      {kinds.length > 1 && (
        <label className="journal-index__filter">
          <span>Show</span>
          <select
            value={kind ?? ""}
            onChange={(event) => {
              onKind(event.target.value === "" ? null : event.target.value);
            }}
          >
            <option value="">Everything</option>
            {kinds.map((choice) => (
              <option key={choice} value={choice}>
                {pluralKind(choice)}
              </option>
            ))}
          </select>
        </label>
      )}
      {days.length === 0 && <p className="knowledge__empty">No dated reports yet.</p>}
      {months.map((group) => (
        <section key={group.month} className="journal-index__month" aria-label={monthHeading(group.month)}>
          <h3 className="recent__day">{monthHeading(group.month)}</h3>
          <ul className="files__list">
            {group.days.map((day) => (
              <li key={day.date}>
                <button
                  type="button"
                  className={`files__item${current === day.date ? " files__item--active" : ""}`}
                  aria-current={current === day.date ? "true" : undefined}
                  onClick={() => {
                    onPick(day.date);
                  }}
                >
                  <span className="files__file-icon journal-index__badge" aria-hidden="true">
                    {day.date.length === 7 ? "All" : day.date.slice(8)}
                  </span>
                  <span className="files__identity">
                    <span className="files__name journal-index__day">{shortDay(day.date)}</span>
                    <span className="files__meta">{day.entries.map(entryLabel).join(" · ")}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export interface JournalPageProps {
  spaceId: string;
  days: readonly JournalDay[];
  focus: JournalFocus | null;
  onOpenNote: (path: string) => void;
  onLink: (target: string, heading: string | null) => void;
  onTag: (tag: string) => void;
}

type Loaded = { readonly text: string } | { readonly error: string };

export function JournalPage({ spaceId, days, focus, onOpenNote, onLink, onTag }: JournalPageProps) {
  const [shown, setShown] = useState(DATES_PER_PAGE);
  // Each report's text by path and version, so a rewritten one is read again.
  const [loaded, setLoaded] = useState<ReadonlyMap<string, Loaded>>(new Map());
  const requested = useRef(new Set<string>());
  const page = useRef<HTMLDivElement>(null);

  // A date picked past the page widens it, adjusted while rendering.
  const [widenedFor, setWidenedFor] = useState<number | null>(null);
  if (focus !== null && focus.nonce !== widenedFor) {
    setWidenedFor(focus.nonce);
    const at = days.findIndex((day) => day.date === focus.date);
    if (at >= shown) setShown(Math.ceil((at + 1) / DATES_PER_PAGE) * DATES_PER_PAGE);
  }

  const visible = useMemo(() => days.slice(0, shown), [days, shown]);
  useEffect(() => {
    const pending = visible.flatMap((day) => day.entries).filter((entry) => !requested.current.has(versionOf(entry)));
    if (pending.length === 0) return;
    for (const entry of pending) requested.current.add(versionOf(entry));
    void Promise.all(
      pending.map((entry) =>
        api.getKnowledgeNote(spaceId, entry.path).then(
          (note): [string, Loaded] => [versionOf(entry), { text: note.content }],
          (failure: unknown): [string, Loaded] => [
            versionOf(entry),
            { error: failure instanceof Error ? failure.message : String(failure) },
          ],
        ),
      ),
    ).then((results) => {
      setLoaded((current) => new Map([...current, ...results]));
    });
  }, [visible, spaceId]);

  // Scroll to a picked date once everything above it has its text; earlier,
  // what arrives later would push it out of view again.
  const scrolledFor = useRef<number | null>(null);
  useEffect(() => {
    if (focus === null || scrolledFor.current === focus.nonce) return;
    const at = days.findIndex((day) => day.date === focus.date);
    if (at < 0 || at >= visible.length) return;
    const ready = days.slice(0, at + 1).every((day) => day.entries.every((entry) => loaded.has(versionOf(entry))));
    if (!ready) return;
    scrolledFor.current = focus.nonce;
    const target = page.current?.querySelector<HTMLElement>(`[data-date="${focus.date}"]`);
    if (target !== undefined && target !== null && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "start" });
    }
  }, [focus, days, visible, loaded]);

  if (days.length === 0) {
    return (
      <div className="journal" data-testid="journal">
        <div className="knowledge__welcome">
          <h2>Nothing dated yet</h2>
          <p>
            Each day's decision, its portfolio review and the weekly review collect here as the automations write
            them, newest first. Any note with a date in its file name joins them, such as a daily note.
          </p>
        </div>
      </div>
    );
  }

  const reports = days.reduce((count, day) => count + day.entries.length, 0);
  const remaining = days.length - visible.length;
  return (
    <div className="journal" data-testid="journal" ref={page}>
      <div className="journal__inner">
        <header className="journal__head">
          <h2>Journal</h2>
          <p>
            {plural(reports, "report")} from {plural(days.length, "date")}, newest first. Each report stays its own
            file; this page reads them in order.
          </p>
        </header>
        {visible.map((day) => (
          <section key={day.date} className="journal__day" data-date={day.date} aria-label={dayHeading(day.date)}>
            <h3 className="journal__date">{dayHeading(day.date)}</h3>
            {day.entries.map((entry) => {
              const item = loaded.get(versionOf(entry));
              return (
                <article key={entry.path} className="journal__entry" aria-label={`${entryLabel(entry)}, ${entry.path}`}>
                  <header className="journal__entry-head">
                    <div className="journal__entry-name">
                      <strong>{entryLabel(entry)}</strong>
                      <span className="journal__path">
                        {entry.path} · {whenLabel(entry.updatedAt)}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="button button--small"
                      aria-label={`Open note ${entry.path}`}
                      onClick={() => {
                        onOpenNote(entry.path);
                      }}
                    >
                      Open note
                    </button>
                  </header>
                  {item === undefined ? (
                    <p className="journal__loading">Loading…</p>
                  ) : "error" in item ? (
                    <p className="field-error" role="alert">
                      {item.error}
                    </p>
                  ) : (
                    <Markdown source={item.text} onLink={onLink} onTag={onTag} className="journal__body" />
                  )}
                </article>
              );
            })}
          </section>
        ))}
        {remaining > 0 && (
          <button
            type="button"
            className="button journal__more"
            onClick={() => {
              setShown((current) => current + DATES_PER_PAGE);
            }}
          >
            Show {plural(Math.min(remaining, DATES_PER_PAGE), "older date")}
          </button>
        )}
      </div>
    </div>
  );
}

/** The pipeline's reports by kind; any other dated note by its title. */
function entryLabel(entry: JournalEntry): string {
  return entry.kind === "Note" ? entry.title : entry.kind;
}

function pluralKind(kind: string): string {
  return kind === "Note" ? "Other dated notes" : `${kind}s`;
}

function versionOf(entry: JournalEntry): string {
  return `${entry.updatedAt} ${entry.path}`;
}

function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? "" : "s"}`;
}
