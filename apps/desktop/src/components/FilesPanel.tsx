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

function pathParts(path: string): { directory: string; name: string } {
  const separator = path.lastIndexOf("/");
  return separator < 0
    ? { directory: "", name: path }
    : { directory: path.slice(0, separator), name: path.slice(separator + 1) };
}

function fileType(path: string): string {
  const name = pathParts(path).name;
  const separator = name.lastIndexOf(".");
  return separator < 0 ? "FILE" : name.slice(separator + 1).toUpperCase();
}

function fileGroup(path: string): string {
  return path.includes("/") ? path.slice(0, path.indexOf("/")) : "";
}

function nestedDirectory(path: string): string {
  const { directory } = pathParts(path);
  if (!directory.includes("/")) return "";
  return `${directory.slice(directory.indexOf("/") + 1)}/`;
}

function groupLabel(group: string): string {
  return group === "" ? "Space root" : group;
}

export function FilesPanel({ spaceId, part, open, onOpen, onChanged, reloadNonce = 0 }: FilesPanelProps) {
  const load = useCallback(() => api.listFiles(spaceId), [spaceId]);
  const files = useFetched(load, null);
  const list = files.data?.files ?? NO_FILES;
  const [query, setQuery] = useState("");
  const { reload } = files;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);

  if (part === "list") {
    const matching = list.filter((file) => file.path.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    const groups = new Map<string, TextFileSummary[]>();
    for (const file of matching) {
      const group = fileGroup(file.path);
      groups.set(group, [...(groups.get(group) ?? []), file]);
    }
    const orderedGroups = [...groups.entries()].sort(([left], [right]) => {
      if (left === "") return -1;
      if (right === "") return 1;
      return left.localeCompare(right);
    });

    return (
      <div className="files" data-testid="files-list">
        <div className="files__head">
          <div>
            <strong>Agent files</strong>
            <span className="files__count">
              {list.length} file{list.length === 1 ? "" : "s"}
            </span>
          </div>
          <button
            type="button"
            className="button button--small button--primary"
            onClick={() => {
              onOpen({ path: "", fresh: true });
            }}
          >
            New file
          </button>
        </div>
        <div className="files__tools">
          <label>
            <span className="sr-only">Filter agent files</span>
            <input
              type="search"
              value={query}
              placeholder="Filter by name or folder"
              onChange={(event) => {
                setQuery(event.target.value);
              }}
            />
          </label>
          <label>
            <span className="sr-only">Create from template</span>
            <select
              aria-label="Create from template"
              value=""
              onChange={(event) => {
                if (event.target.value !== "") onOpen({ path: event.target.value, fresh: true });
              }}
            >
              <option value="">From template…</option>
              {STARTERS.map((starter) => (
                <option key={starter.path} value={starter.path}>
                  {starter.path}
                </option>
              ))}
            </select>
          </label>
        </div>
        {files.error !== null && (
          <p className="field-error" role="alert">
            {files.error}
          </p>
        )}
        {list.length === 0 && files.data !== null && (
          <div className="files__empty">
            <p>No agent files yet.</p>
            <p>Create a blank file or choose a starter template above. Agent files hold structured inputs and generated outputs.</p>
          </div>
        )}
        {list.length > 0 && matching.length === 0 && (
          <p className="files__no-match">No files match “{query.trim()}”.</p>
        )}
        <div className="files__groups">
          {orderedGroups.map(([group, groupedFiles], position) => (
            <section className="files__group" key={group || "root"} aria-labelledby={`file-group-${String(position)}`}>
              <div className="files__group-head">
                <h3 id={`file-group-${String(position)}`}>{groupLabel(group)}</h3>
                <span>{groupedFiles.length}</span>
              </div>
              <ul className="files__list">
                {groupedFiles.map((file) => {
                  const parts = pathParts(file.path);
                  const nested = nestedDirectory(file.path);
                  return (
                    <li key={file.path}>
                      <button
                        type="button"
                        className={`files__item${open?.path === file.path ? " files__item--active" : ""}`}
                        aria-current={open?.path === file.path ? "true" : undefined}
                        aria-label={`${file.path}, ${fileType(file.path)}, ${sizeLabel(file.size)}`}
                        title={`${file.path} · ${sizeLabel(file.size)}`}
                        onClick={() => {
                          onOpen({ path: file.path, fresh: false });
                        }}
                      >
                        <span className="files__file-icon" aria-hidden="true">{fileType(file.path).slice(0, 1)}</span>
                        <span className="files__identity">
                          <span className="files__name">{parts.name}</span>
                          <span className="files__meta">
                            {nested !== "" && `${nested} · `}{fileType(file.path)} · {sizeLabel(file.size)}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </div>
    );
  }

  if (open === null) {
    return (
      <div className="files__placeholder" data-testid="files-editor">
        <p>Pick an agent file on the left, or create one. These are plain-text inputs and outputs in the space folder; agents read them with read_file.</p>
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
  const identity = pathParts(path);
  const kind = fileType(path);

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
        <div className="file-editor__identity">
          <span className="file-editor__eyebrow">Agent file</span>
          <h2>{identity.name || "New agent file"}</h2>
          {path !== "" && (
            <p>{identity.directory === "" ? "Space root" : `${identity.directory}/`} · {kind}</p>
          )}
        </div>
        <div className="file-editor__actions">
          {!loading && dirty && <span className="file-editor__dirty">Unsaved changes</span>}
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
      {open.fresh && (
        <label className="file-editor__path-field">
          <span>File path</span>
          <input
            value={path}
            placeholder="config/watchlist.json"
            aria-label="File path"
            onChange={(changed) => {
              setPath(changed.target.value);
            }}
          />
          <small>Use folders to keep inputs, research, and generated outputs organized.</small>
        </label>
      )}
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
