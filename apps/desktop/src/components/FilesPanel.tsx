import type { TextFileSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { STARTERS } from "../lib/pipeline";
import { useFetched } from "../state/useFetched";

/**
 * Space-folder plain-text config/data files (for example, watchlist JSON, raw
 * JSON, positions CSV). Source-only list/editor validates JSON before saving
 * and uses sidecar note-equivalent path rules.
 */

export interface FilesPanelProps {
  spaceId: string;
  /** Render browser list or workspace editor. */
  part: "list" | "editor";
  /** Parent-shared editor file. */
  open: OpenFile | null;
  onOpen: (file: OpenFile | null) => void;
  /** File write/delete; parent may reload folder consumers. */
  onChanged?: (() => void) | undefined;
  /** Parent bump after other-half file changes; reload list. */
  reloadNonce?: number | undefined;
}

export interface OpenFile {
  path: string;
  /** True for a file that does not exist yet: the path is still being typed. */
  fresh: boolean;
}

const NO_FILES: TextFileSummary[] = [];

/** "1.2 KB" and the like, for the list. */
function sizeLabel(size: number): string {
  if (size < 1024) return `${String(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}


export function FilesPanel({ spaceId, part, open, onOpen, onChanged, reloadNonce = 0 }: FilesPanelProps) {
  const load = useCallback(() => api.listFiles(spaceId), [spaceId]);
  const files = useFetched(load, null);
  const list = files.data?.files ?? NO_FILES;
  const { reload } = files;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);

  if (part === "list") {
    return (
      <div className="files" data-testid="files-list">
        <div className="files__head">
          <span className="files__count">
            {list.length} file{list.length === 1 ? "" : "s"}
          </span>
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              onOpen({ path: "", fresh: true });
            }}
          >
            New file
          </button>
        </div>
        {files.error !== null && (
          <p className="field-error" role="alert">
            {files.error}
          </p>
        )}
        {list.length === 0 && files.data !== null && (
          <div className="files__empty">
            <p>No agent data yet. These structured files are inputs and outputs for agents; each starter input begins from a template:</p>
            <ul>
              {STARTERS.map((starter) => (
                <li key={starter.path}>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => {
                      onOpen({ path: starter.path, fresh: true });
                    }}
                  >
                    {starter.path}
                  </button>{" "}
                  <span className="files__why">{starter.why}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <ul className="files__list">
          {list.map((file) => (
            <li key={file.path}>
              <button
                type="button"
                className={`files__item${open?.path === file.path ? " files__item--active" : ""}`}
                aria-current={open?.path === file.path ? "true" : undefined}
                title={`${file.path} · ${sizeLabel(file.size)}`}
                onClick={() => {
                  onOpen({ path: file.path, fresh: false });
                }}
              >
                <span className="files__path">{file.path}</span>
                <span className="files__size">{sizeLabel(file.size)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  if (open === null) {
    return (
      <div className="files__placeholder" data-testid="files-editor">
        <p>Pick an agent data file on the left, or create one. These are plain-text inputs and outputs in the space folder; agents read them with read_file.</p>
      </div>
    );
  }

  return (
    <FileEditor
      key={`${spaceId}:${open.path}:${String(open.fresh)}`}
      spaceId={spaceId}
      open={open}
      onSaved={(path) => {
        files.reload();
        onOpen({ path, fresh: false });
        onChanged?.();
      }}
      onDeleted={() => {
        files.reload();
        onOpen(null);
        onChanged?.();
      }}
      onCancel={() => {
        onOpen(null);
      }}
    />
  );
}

function FileEditor({
  spaceId,
  open,
  onSaved,
  onDeleted,
  onCancel,
}: {
  spaceId: string;
  open: OpenFile;
  onSaved: (path: string) => void;
  onDeleted: () => void;
  onCancel: () => void;
}) {
  const starter = STARTERS.find((candidate) => candidate.path === open.path);
  const [path, setPath] = useState(open.path);
  const [content, setContent] = useState(open.fresh ? (starter?.content ?? "") : "");
  const [baseline, setBaseline] = useState(open.fresh ? "" : null as string | null);
  const [loading, setLoading] = useState(!open.fresh);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteAsked, setDeleteAsked] = useState(false);

  useEffect(() => {
    if (open.fresh) return undefined;
    let live = true;
    void api
      .getFile(spaceId, open.path)
      .then((file) => {
        if (!live) return;
        setContent(file.content);
        setBaseline(file.content);
        setLoading(false);
      })
      .catch((failure: unknown) => {
        if (!live) return;
        setError(failure instanceof Error ? failure.message : String(failure));
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [spaceId, open.path, open.fresh]);

  const dirty = baseline === null ? true : content !== baseline;
  const isJson = path.trim().toLowerCase().endsWith(".json");

  const save = async () => {
    setError(null);
    const wanted = path.trim();
    if (wanted === "") {
      setError("Give the file a path inside the space, for example config/watchlist.json.");
      return;
    }
    if (isJson) {
      try {
        JSON.parse(content);
      } catch (failure) {
        setError(`Not valid JSON: ${failure instanceof Error ? failure.message : String(failure)}`);
        return;
      }
    }
    setBusy(true);
    try {
      const saved = await api.writeFile(spaceId, wanted, content);
      setBaseline(saved.content);
      onSaved(saved.path);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteFile(spaceId, open.path);
      onDeleted();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="file-editor" data-testid="files-editor">
      <div className="file-editor__head">
        {open.fresh ? (
          <label className="knowledge__path">
            <span>Path</span>
            <input
              value={path}
              placeholder="config/watchlist.json"
              aria-label="File path"
              onChange={(changed) => {
                setPath(changed.target.value);
              }}
            />
          </label>
        ) : (
          <code className="file-editor__path">{open.path}</code>
        )}
        <div className="file-editor__actions">
          {!open.fresh &&
            (deleteAsked ? (
              <span className="roster__confirm">
                <span>Delete {open.path}? A copy is kept under .agentbase/backups.</span>
                <button type="button" className="button button--small button--danger" disabled={busy} onClick={() => void remove()}>
                  Delete
                </button>
                <button
                  type="button"
                  className="button button--small"
                  disabled={busy}
                  onClick={() => {
                    setDeleteAsked(false);
                  }}
                >
                  Keep
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="button button--small"
                disabled={busy}
                onClick={() => {
                  setDeleteAsked(true);
                }}
              >
                Delete…
              </button>
            ))}
          <button type="button" className="button button--small" disabled={busy} onClick={onCancel}>
            Close
          </button>
          <button type="button" className="button button--small button--primary" disabled={busy || loading || !dirty} onClick={() => void save()}>
            {busy ? "Saving…" : "Save file"}
          </button>
        </div>
      </div>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <textarea
        className="file-editor__text"
        aria-label="File contents"
        spellCheck={false}
        value={loading ? "Loading…" : content}
        disabled={loading}
        onChange={(changed) => {
          setContent(changed.target.value);
        }}
      />
      <p className="file-editor__hint">
        {isJson ? "JSON is checked before it is saved. " : ""}
        An agent with read_file sees this file; one with write_file may change it, behind the same
        approval as any write.
      </p>
    </div>
  );
}
