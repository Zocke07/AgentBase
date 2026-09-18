import type { MemoryIndex, MemoryItem, MemoryStatus } from "@agentspace/schemas";

import { Markdown } from "./Markdown";

/**
 * The memory inbox: a run's outcome or an agent's proposal starts as
 * `proposed`, and is retrieved only once a person approves or pins it. The
 * inbox also archives, merges (originals archived and backed up) and forgets
 * memories, and shows where each came from.
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
  if (memories === null) return <p className="knowledge__empty">Loading memories…</p>;
  if (memories.items.length === 0) {
    return <p className="knowledge__empty">Completed runs and agent proposals will appear here.</p>;
  }
  return (
    <>
      <p className="knowledge__inbox-summary">
        {memories.proposed} proposed · {memories.approved} approved · {memories.archived} archived. Only
        approved and pinned memories are retrieved.
      </p>
      {selection.length > 0 && (
        <div className="knowledge__merge" data-testid="memory-merge">
          <input
            aria-label="Merged memory title"
            placeholder="Title for the merged memory (optional)"
            value={mergeTitle}
            onChange={(event) => { onMergeTitle(event.target.value); }}
          />
          <button
            type="button"
            className="button button--small button--primary"
            disabled={busy || selection.length < 2}
            onClick={onMerge}
          >
            Merge {selection.length} selected
          </button>
        </div>
      )}
    <ol className="knowledge__memories">
      {memories.items.map((memory) => (
        <li className="knowledge__memory" key={memory.path}>
          <div className="knowledge__memory-head">
            <label className="knowledge__memory-select">
              <input
                type="checkbox"
                aria-label={`Select ${memory.title} for merging`}
                checked={selection.includes(memory.path)}
                disabled={memory.status === "archived"}
                onChange={() => { onToggleSelect(memory.path); }}
              />
            </label>
            <button type="button" className="link" onClick={() => { onOpen(memory.path); }}>
              {memory.title}
            </button>
            <span className={`knowledge__memory-status knowledge__memory-status--${memory.status}`}>
              {memory.status}
            </span>
          </div>
          <div className="knowledge__memory-text">
            <Markdown source={memory.outcome || memory.goal || "Empty memory"} className="md--compact" />
          </div>
          <small>
            {(memory.merged_from ?? []).length > 0
              ? "merged by you"
              : memory.source === "run"
                ? "from a run"
                : "proposed by an agent"}{" "}
            · created{" "}
            {new Date(memory.created_at).toLocaleDateString()} · confidence {memory.confidence}
            {memory.pinned ? " · pinned" : ""}
            {(memory.tags ?? []).length > 0 && ` · ${(memory.tags ?? []).map((tag) => `#${tag}`).join(" ")}`}
          </small>
          {memory.run_id !== null && (
            <small>
              run <code>{memory.run_id}</code>
              {onOpenRun !== undefined && (
                <>
                  {" "}
                  <button type="button" className="link" onClick={() => { onOpenRun(memory.run_id ?? ""); }}>
                    Open run
                  </button>
                </>
              )}
            </small>
          )}
          {(memory.citations ?? []).length > 0 && (
            <div className="knowledge__citations" aria-label="Supporting citations">
              {(memory.citations ?? []).map((citation) => {
                const target = citationPath(citation);
                return target === null ? (
                  <code key={citation}>{citation}</code>
                ) : (
                  <button type="button" className="knowledge__relation" key={citation} onClick={() => { onOpen(target); }}>
                    {citation}
                  </button>
                );
              })}
            </div>
          )}
          {(memory.merged_from ?? []).length > 0 && (
            <small>merged from {(memory.merged_from ?? []).join(", ")}</small>
          )}
          {memory.merged_into !== null && memory.merged_into !== undefined && (
            <small>
              merged into{" "}
              <button type="button" className="link" onClick={() => { onOpen(memory.merged_into ?? ""); }}>
                {memory.merged_into}
              </button>
            </small>
          )}
          <div className="knowledge__memory-actions">
            <button type="button" className="button button--small" disabled={busy} onClick={() => { onOpen(memory.path); }}>
              Edit
            </button>
            {memory.status !== "approved" && (
              <button
                type="button"
                className="button button--small button--primary"
                disabled={busy}
                onClick={() => { onCurate(memory, { status: "approved" }); }}
              >
                Approve
              </button>
            )}
            {memory.status !== "archived" && (
              <button
                type="button"
                className="button button--small"
                disabled={busy}
                onClick={() => { onCurate(memory, { status: "archived" }); }}
              >
                Archive
              </button>
            )}
            <button
              type="button"
              className="button button--small"
              disabled={busy}
              onClick={() => { onCurate(memory, { pinned: !memory.pinned }); }}
            >
              {memory.pinned ? "Unpin" : "Pin"}
            </button>
            {forgetAsked === memory.path ? (
              <span className="roster__confirm">
                <span>Forget permanently?</span>
                <button
                  type="button"
                  className="button button--small button--danger"
                  disabled={busy}
                  onClick={() => { onForget(memory); }}
                >
                  Forget
                </button>
                <button
                  type="button"
                  className="button button--small"
                  disabled={busy}
                  onClick={() => { onAskForget(null); }}
                >
                  Keep
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="button button--small button--danger"
                disabled={busy}
                onClick={() => { onAskForget(memory.path); }}
              >
                Forget…
              </button>
            )}
          </div>
        </li>
      ))}
    </ol>
    </>
  );
}


/** `[[path#heading]]` or `[[path]]` to the note path the vault would resolve it to. */
function citationPath(citation: string): string | null {
  const match = /^\[\[([^\]#|]+)/.exec(citation.trim());
  const stem = match?.[1]?.trim();
  return stem === undefined || stem === "" ? null : `${stem.replace(/\.md$/i, "")}.md`;
}

