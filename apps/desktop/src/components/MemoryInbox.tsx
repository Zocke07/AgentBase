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
  management: "automatic" | "review" | "off";
  managementModel: string;
  onManagement: (mode: "automatic" | "review" | "off") => void;
}

type MemoryView = MemoryStatus | "all";

const STATUS_LABEL: Record<MemoryStatus, string> = {
  proposed: "Needs attention",
  approved: "Available",
  archived: "History",
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
  management,
  managementModel,
  onManagement,
}: MemoryInboxProps) {
  const [view, setView] = useState<MemoryView>("proposed");
  const [organizing, setOrganizing] = useState(false);

  if (memories === null) return <p className="knowledge__empty">Loading saved context…</p>;

  const visible = view === "all" ? memories.items : memories.items.filter((memory) => memory.status === view);
  const stopOrganizing = () => {
    for (const selected of selection) onToggleSelect(selected);
    setOrganizing(false);
    setView("proposed");
  };

  return (
    <>
      <div className="knowledge__memory-intro">
        <div className="knowledge__memory-management">
          <label>
            <span>Saved context management</span>
            <select
              value={management}
              onChange={(event) => {
                onManagement(event.target.value as "automatic" | "review" | "off");
              }}
            >
              <option value="automatic">Automatic</option>
              <option value="review">Review every item</option>
              <option value="off">Off</option>
            </select>
          </label>
          <p>
            {management === "automatic"
              ? `${managementModel} manages saved context after each successful run. Only uncertain or conflicting items need your attention.`
              : management === "review"
                ? "Every generated summary and proposal waits for your decision before later runs can use it."
                : "Run summaries and agent proposals are not saved while management is off."}
          </p>
          <small>Changes are backed up and each item records why it changed.</small>
        </div>
        <div className="knowledge__memory-filters" role="group" aria-label="Show saved context">
          <FilterButton
            active={view === "proposed"}
            label={`Needs attention ${String(memories.proposed)}`}
            onClick={() => { setView("proposed"); }}
          />
          <FilterButton
            active={view === "approved"}
            label={`Available ${String(memories.approved)}`}
            onClick={() => { setView("approved"); }}
          />
          <FilterButton
            active={view === "archived"}
            label={`History ${String(memories.archived)}`}
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
            ? "You are caught up. Nothing needs attention."
            : view === "approved"
              ? "No saved context is available to future runs."
              : "There is no saved-context history yet."}
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

              {memory.managed_at !== null && memory.managed_at !== undefined && (
                <p className="knowledge__memory-management-note">
                  <strong>
                    {memory.status === "proposed" ? "Sent to your attention" : "Managed automatically"}
                  </strong>
                  {memory.management_model !== null && memory.management_model !== undefined
                    ? ` by ${memory.management_model}`
                    : ""}
                  {memory.management_reason !== null && memory.management_reason !== undefined
                    ? `: ${memory.management_reason}`
                    : "."}
                  {memory.management_backup !== null && memory.management_backup !== undefined
                    ? " A recoverable copy was saved."
                    : ""}
                </p>
              )}

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
