import type { MemoryIndex, MemoryItem, MemoryStatus } from "@agentbase/schemas";
import { useState } from "react";

import { Markdown } from "./Markdown";

/**
 * A review queue for context that later runs may retrieve. The common choice
 * stays prominent while editing, pinning, combining and deletion stay tucked
 * behind secondary controls.
 */

export interface MemoryInboxProps {
  memories: MemoryIndex | null;
  busy: boolean;
  forgetAsked: string | null;
  selection: string[];
  mergeTitle: string;
  onOpen: (path: string) => void;
  onOpenRun: ((runId: string) => void) | undefined;
  onCurate: (memory: MemoryItem, changes: { status?: MemoryStatus; pinned?: boolean }) => void;
  onAskForget: (path: string | null) => void;
  onForget: (memory: MemoryItem) => void;
  onToggleSelect: (path: string) => void;
  onMergeTitle: (title: string) => void;
  onMerge: () => void;
}

type MemoryView = MemoryStatus | "all";

const STATUS_LABEL: Record<MemoryStatus, string> = {
  proposed: "Needs review",
  approved: "Kept",
  archived: "Dismissed",
};

export function MemoryInbox({
  memories,
  busy,
  forgetAsked,
  selection,
  mergeTitle,
  onOpen,
  onOpenRun,
  onCurate,
  onAskForget,
  onForget,
  onToggleSelect,
  onMergeTitle,
  onMerge,
}: MemoryInboxProps) {
  const [view, setView] = useState<MemoryView>("proposed");
  const [organizing, setOrganizing] = useState(false);

  if (memories === null) return <p className="knowledge__empty">Loading saved context…</p>;
  if (memories.items.length === 0) {
    return (
      <p className="knowledge__empty">
        Nothing to review yet. Useful run summaries and agent proposals will appear here.
      </p>
    );
  }

  const visible = view === "all" ? memories.items : memories.items.filter((memory) => memory.status === view);
  const stopOrganizing = () => {
    for (const selected of selection) onToggleSelect(selected);
    setOrganizing(false);
    setView("proposed");
  };

  return (
    <>
      <div className="knowledge__memory-intro">
        <p>Keep useful summaries so later runs can find them. Dismiss anything that should not influence future work.</p>
        <div className="knowledge__memory-filters" role="group" aria-label="Show saved context">
          <FilterButton
            active={view === "proposed"}
            label={`Needs review ${String(memories.proposed)}`}
            onClick={() => { setView("proposed"); }}
          />
          <FilterButton
            active={view === "approved"}
            label={`Kept ${String(memories.approved)}`}
            onClick={() => { setView("approved"); }}
          />
          <FilterButton
            active={view === "archived"}
            label={`Dismissed ${String(memories.archived)}`}
            onClick={() => { setView("archived"); }}
          />
        </div>
        {!organizing && (
          <details className="knowledge__memory-organize">
            <summary>Organize</summary>
            <p>Combine overlapping summaries into one cleaner memory.</p>
            <button
              type="button"
              className="button button--small"
              onClick={() => {
                setOrganizing(true);
                setView("all");
              }}
            >
              Combine memories
            </button>
          </details>
        )}
      </div>

      {organizing && (
        <div className="knowledge__merge" data-testid="memory-merge">
          <p>Select at least two memories to combine. Dismissed memories cannot be selected.</p>
          <input
            aria-label="Merged memory title"
            placeholder="Combined memory title (optional)"
            value={mergeTitle}
            onChange={(event) => { onMergeTitle(event.target.value); }}
          />
          <div className="knowledge__merge-actions">
            <button
              type="button"
              className="button button--small button--primary"
              disabled={busy || selection.length < 2}
              onClick={onMerge}
            >
              Combine {selection.length} selected
            </button>
            <button type="button" className="button button--small" disabled={busy} onClick={stopOrganizing}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {visible.length === 0 ? (
        <p className="knowledge__empty">
          {view === "proposed"
            ? "You are caught up. Nothing needs review."
            : view === "approved"
              ? "No memories have been kept for future runs."
              : "No memories have been dismissed."}
        </p>
      ) : (
        <ol className="knowledge__memories">
          {visible.map((memory) => (
            <li className="knowledge__memory" key={memory.path}>
              <div className="knowledge__memory-head">
                {organizing && memory.status !== "archived" && (
                  <label className="knowledge__memory-select">
                    <input
                      type="checkbox"
                      aria-label={`Select ${memory.title} for combining`}
                      checked={selection.includes(memory.path)}
                      onChange={() => { onToggleSelect(memory.path); }}
                    />
                  </label>
                )}
                <button type="button" className="link knowledge__memory-title" onClick={() => { onOpen(memory.path); }}>
                  {memory.title}
                </button>
                <span className={`knowledge__memory-status knowledge__memory-status--${memory.status}`}>
                  {STATUS_LABEL[memory.status]}
                </span>
              </div>

              <div className="knowledge__memory-text">
                <Markdown source={memory.outcome || memory.goal || "Empty memory"} className="md--compact" />
              </div>

              <small>
                {(memory.merged_from ?? []).length > 0
                  ? "Combined by you"
                  : memory.source === "run"
                    ? "From a run"
                    : "Proposed by an agent"}
                {" · "}
                {new Date(memory.created_at).toLocaleDateString()}
                {memory.pinned ? " · always included" : ""}
              </small>

              {(memory.citations ?? []).length > 0 && (
                <div className="knowledge__citations" aria-label="Supporting citations">
                  {(memory.citations ?? []).map((citation) => {
                    const target = citationPath(citation);
                    return target === null ? (
                      <code key={citation}>{citation}</code>
                    ) : (
                      <button
                        type="button"
                        className="knowledge__relation"
                        key={citation}
                        onClick={() => { onOpen(target); }}
                      >
                        {citation}
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="knowledge__memory-actions">
                {memory.status !== "approved" && (
                  <button
                    type="button"
                    className="button button--small button--primary"
                    disabled={busy}
                    onClick={() => { onCurate(memory, { status: "approved" }); }}
                  >
                    Keep for future runs
                  </button>
                )}
                {memory.status !== "archived" && (
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy}
                    onClick={() => { onCurate(memory, { status: "archived" }); }}
                  >
                    Dismiss
                  </button>
                )}
              </div>

              <details className="knowledge__memory-more">
                <summary>More actions</summary>
                <div className="knowledge__memory-more-actions">
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy}
                    onClick={() => { onOpen(memory.path); }}
                  >
                    Edit full note
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy}
                    onClick={() => { onCurate(memory, { pinned: !memory.pinned }); }}
                  >
                    {memory.pinned ? "Use when relevant" : "Always include"}
                  </button>
                  {memory.run_id !== null && onOpenRun !== undefined && (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() => { onOpenRun(memory.run_id ?? ""); }}
                    >
                      Open source run
                    </button>
                  )}
                  {forgetAsked === memory.path ? (
                    <span className="roster__confirm">
                      <span>Delete permanently?</span>
                      <button
                        type="button"
                        className="button button--small button--danger"
                        disabled={busy}
                        onClick={() => { onForget(memory); }}
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        className="button button--small"
                        disabled={busy}
                        onClick={() => { onAskForget(null); }}
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={busy}
                      onClick={() => { onAskForget(memory.path); }}
                    >
                      Delete permanently…
                    </button>
                  )}
                </div>
                {(memory.tags ?? []).length > 0 && <small>{(memory.tags ?? []).map((tag) => `#${tag}`).join(" ")}</small>}
                {(memory.merged_from ?? []).length > 0 && (
                  <small>Combined from {(memory.merged_from ?? []).join(", ")}</small>
                )}
                {memory.merged_into !== null && memory.merged_into !== undefined && (
                  <small>
                    Combined into{" "}
                    <button type="button" className="link" onClick={() => { onOpen(memory.merged_into ?? ""); }}>
                      {memory.merged_into}
                    </button>
                  </small>
                )}
              </details>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function FilterButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick}>
      {label}
    </button>
  );
}

/** `[[path#heading]]` or `[[path]]` to the note path the vault would resolve it to. */
function citationPath(citation: string): string | null {
  const match = /^\[\[([^\]#|]+)/.exec(citation.trim());
  const stem = match?.[1]?.trim();
  return stem === undefined || stem === "" ? null : `${stem.replace(/\.md$/i, "")}.md`;
}
