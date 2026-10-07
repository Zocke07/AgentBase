import type { NoteSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { whenLabel } from "../lib/format";
import { isWorkingFile, splitPath } from "../state/files";
import { useFetched } from "../state/useFetched";

/**
 * Notes and agent files together, newest first: what a person or a run
 * changed last, without knowing which tab or folder it went to. Run memories
 * stay in Saved context, where they are managed.
 */

export interface RecentFilesProps {
  spaceId: string;
  /** The vault index's notes. */
  notes: readonly NoteSummary[];
  /** Bumped when files may have changed; rereads the data files. */
  reloadNonce?: number | undefined;
  onOpenNote: (path: string) => void;
  onOpenFile: (path: string) => void;
}

interface Entry {
  readonly path: string;
  readonly kind: "note" | "file";
  readonly title: string | null;
  readonly updatedAt: string;
}

/** Enough to cover a day of the pipeline's outputs without a long scroll. */
const RECENT_LIMIT = 40;

export function RecentFiles({ spaceId, notes, reloadNonce = 0, onOpenNote, onOpenFile }: RecentFilesProps) {
  const load = useCallback(() => api.listFiles(spaceId), [spaceId]);
  const files = useFetched(load, null);
  // Days whose working files the person unfolded.
  const [unfolded, setUnfolded] = useState<ReadonlySet<string>>(new Set());
  const { reload } = files;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);

  const entries: Entry[] = [
    ...notes
      .filter((note) => !note.path.startsWith("memory/"))
      .map((note): Entry => ({ path: note.path, kind: "note", title: note.title, updatedAt: note.updated_at })),
    ...(files.data?.files ?? []).map(
      (file): Entry => ({ path: file.path, kind: "file", title: null, updatedAt: file.updated_at }),
    ),
  ]
    .sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt))
    .slice(0, RECENT_LIMIT);

  if (entries.length === 0) {
    return (
      <p className="knowledge__empty" data-testid="recent-files">
        Nothing has been written in this space yet.
      </p>
    );
  }

  const groups: { label: string; entries: Entry[] }[] = [];
  for (const entry of entries) {
    const label = dayLabel(entry.updatedAt);
    const last = groups.at(-1);
    if (last?.label === label) last.entries.push(entry);
    else groups.push({ label, entries: [entry] });
  }

  const row = (entry: Entry) => {
    const { name, folder } = splitPath(entry.path);
    const type = entry.kind === "note" ? "Note" : extension(name);
    return (
      <li key={entry.path}>
        <button
          type="button"
          className="files__item"
          data-path={entry.path}
          title={entry.path}
          onClick={() => {
            if (entry.kind === "note") onOpenNote(entry.path);
            else onOpenFile(entry.path);
          }}
        >
          <span className="files__file-icon" aria-hidden="true">
            {type.slice(0, 1)}
          </span>
          <span className="files__identity">
            <span className="files__name">{name}</span>
            <span className="files__meta">
              {[folder === "" ? "Space root" : `${folder}/`, entry.title ?? type, timeLabel(entry.updatedAt)].join(" · ")}
            </span>
          </span>
        </button>
      </li>
    );
  };

  return (
    <div className="recent" data-testid="recent-files">
      {groups.map((group) => (
        <section key={group.label} className="recent__group" aria-label={group.label}>
          <h3 className="recent__day">{group.label}</h3>
          <ul className="files__list">
            {group.entries.filter((entry) => !isWorkingFile(entry.path)).map(row)}
            {group.entries.some((entry) => isWorkingFile(entry.path)) && (
              <WorkingFiles
                entries={group.entries.filter((entry) => isWorkingFile(entry.path))}
                open={unfolded.has(group.label)}
                onToggle={() => {
                  setUnfolded((current) => {
                    const next = new Set(current);
                    if (next.has(group.label)) next.delete(group.label);
                    else next.add(group.label);
                    return next;
                  });
                }}
                row={row}
              />
            )}
          </ul>
        </section>
      ))}
    </div>
  );
}

function extension(name: string): string {
  const separator = name.lastIndexOf(".");
  return separator < 0 ? "File" : name.slice(separator + 1).toUpperCase();
}

/** Today, Yesterday, or Earlier, in the viewer's own calendar. */
function dayLabel(iso: string): string {
  const at = new Date(iso);
  const today = new Date();
  const days = Math.round((startOfDay(today) - startOfDay(at)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return "Earlier";
}

function startOfDay(at: Date): number {
  return new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
}

/** `19:12` today; the weekday and date before that. */
function timeLabel(iso: string): string {
  if (dayLabel(iso) !== "Today") return whenLabel(iso);
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/**
 * A day's working data as one line until asked for: the raw prices, theses
 * and checks the runs write for each other outnumber the reports a person
 * reads, and buried them.
 */
function WorkingFiles({
  entries,
  open,
  onToggle,
  row,
}: {
  entries: readonly Entry[];
  open: boolean;
  onToggle: () => void;
  row: (entry: Entry) => React.ReactNode;
}) {
  const count = `${String(entries.length)} working file${entries.length === 1 ? "" : "s"}`;
  return (
    <>
      <li>
        <button type="button" className="recent__fold" aria-expanded={open} onClick={onToggle}>
          <span className={`tree__chevron${open ? " tree__chevron--open" : ""}`} aria-hidden="true" />
          {open ? `Hide ${count}` : `Show ${count}`}
        </button>
      </li>
      {open && entries.map(row)}
    </>
  );
}
