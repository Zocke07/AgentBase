import type { TextFileSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { VIEW_LABELS, VISUAL_TEMPLATES, viewsFor, type FileView } from "../lib/fileViews";
import { STARTERS } from "../lib/pipeline";
import { scrollToActive } from "../lib/scroll";
import { fileKind, uniquePath, type FileKind } from "../lib/visualization";
import { isWorkingFile } from "../state/files";
import { useFetched } from "../state/useFetched";

import { ChartFile, DashboardFile, DataChart, DiagramFile } from "./FileViews";

/**
 * Space-folder plain-text config/data files (for example, watchlist JSON, raw
 * JSON, positions CSV). The editor validates JSON before saving and uses
 * sidecar note-equivalent path rules. A data file can be drawn as a chart,
 * and a saved chart, dashboard or diagram opens drawn.
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
  /** A new file's first text, from a template. */
  content?: string | undefined;
  /** What the template is for, shown above the new file. */
  purpose?: string | undefined;
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

/** A drawn file by what it is; any other by its extension. */
const DRAWN_TYPES: Partial<Record<FileKind, string>> = {
  chart: "Chart",
  dashboard: "Dashboard",
  diagram: "Diagram",
};

function typeLabel(path: string): string {
  return DRAWN_TYPES[fileKind(path)] ?? fileType(path);
}

/** The editor's small heading over the file name. */
const EYEBROWS: Readonly<Record<FileKind, string>> = {
  data: "Data file",
  chart: "Saved chart",
  dashboard: "Dashboard",
  diagram: "Diagram",
  text: "Agent file",
};

const SAVE_LABELS: Readonly<Record<FileKind, string>> = {
  data: "Save file",
  chart: "Save chart",
  dashboard: "Save dashboard",
  diagram: "Save diagram",
  text: "Save file",
};

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
  // Folders whose fold the person changed from its default.
  const [toggled, setToggled] = useState<ReadonlySet<string>>(new Set());
  const { reload } = files;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);

  // A file opened from a run's list can sit far down; bring it into view.
  const listRef = useRef<HTMLDivElement>(null);
  const openPath = open?.path;
  useEffect(() => {
    if (part !== "list" || openPath === undefined) return;
    scrollToActive(listRef.current, ".files__item--active");
  }, [part, openPath, list.length]);

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
      <div className="files" data-testid="files-list" ref={listRef}>
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
                const chosen = event.target.value;
                if (chosen === "") return;
                const visual = VISUAL_TEMPLATES.find((template) => template.id === chosen);
                onOpen(
                  visual === undefined
                    ? { path: chosen, fresh: true }
                    : {
                        path: uniquePath(
                          visual.path,
                          list.map((file) => file.path),
                        ),
                        fresh: true,
                        content: visual.content,
                        purpose: visual.purpose,
                      },
                );
              }}
            >
              <option value="">From template…</option>
              <optgroup label="Charts and diagrams">
                {VISUAL_TEMPLATES.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Investment pipeline">
                {STARTERS.map((starter) => (
                  <option key={starter.path} value={starter.path}>
                    {starter.path}
                  </option>
                ))}
              </optgroup>
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
          {orderedGroups.map(([group, groupedFiles], position) => {
            // A folder of the runs' working data starts folded, so the inputs a
            // person keeps stand out. A search, or the open file, unfolds it.
            const byDefault = groupedFiles.every((file) => isWorkingFile(file.path));
            const folded =
              query.trim() === "" &&
              (open === null || fileGroup(open.path) !== group) &&
              (toggled.has(group) ? !byDefault : byDefault);
            return (
              <section className="files__group" key={group || "root"} aria-labelledby={`file-group-${String(position)}`}>
                <div className="files__group-head">
                  <h3 id={`file-group-${String(position)}`}>
                    <button
                      type="button"
                      className="files__group-toggle"
                      aria-expanded={!folded}
                      onClick={() => {
                        setToggled((current) => {
                          const next = new Set(current);
                          if (next.has(group)) next.delete(group);
                          else next.add(group);
                          return next;
                        });
                      }}
                    >
                      <span className={`tree__chevron${folded ? "" : " tree__chevron--open"}`} aria-hidden="true" />
                      {groupLabel(group)}
                    </button>
                  </h3>
                  <span>{groupedFiles.length}</span>
                </div>
                {!folded && (
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
                            aria-label={`${file.path}, ${typeLabel(file.path)}, ${sizeLabel(file.size)}`}
                            title={`${file.path} · ${sizeLabel(file.size)}`}
                            onClick={() => {
                              onOpen({ path: file.path, fresh: false });
                            }}
                          >
                            <span className="files__file-icon" aria-hidden="true">{typeLabel(file.path).slice(0, 1)}</span>
                            <span className="files__identity">
                              <span className="files__name">{parts.name}</span>
                              <span className="files__meta">
                                {nested !== "" && `${nested} · `}{typeLabel(file.path)} · {sizeLabel(file.size)}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      </div>
    );
  }

  if (open === null) {
    return (
      <div className="files__placeholder" data-testid="files-editor">
        <p>
          Pick an agent file on the left, or create one. These are plain-text inputs and outputs in the space folder;
          agents read them with read_file.
        </p>
        <p>
          A CSV or JSON file can be drawn as a chart, and a saved chart, dashboard or diagram opens drawn. New ones
          start from the template list.
        </p>
      </div>
    );
  }

  return (
    <FileEditor
      key={`${spaceId}:${open.path}:${String(open.fresh)}`}
      spaceId={spaceId}
      open={open}
      files={list}
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
  files,
  onSaved,
  onDeleted,
  onCancel,
}: {
  spaceId: string;
  open: OpenFile;
  /** The space's files, for the data and charts a chart or dashboard can use. */
  files: readonly TextFileSummary[];
  onSaved: (path: string) => void;
  onDeleted: () => void;
  onCancel: () => void;
}) {
  const starter = STARTERS.find((candidate) => candidate.path === open.path);
  const purpose = open.fresh ? (open.purpose ?? starter?.why) : starter?.why;
  const [path, setPath] = useState(open.path);
  const [content, setContent] = useState(open.fresh ? (open.content ?? starter?.content ?? "") : "");
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
  const kind = fileKind(path);
  // A file opens in its first view; the person's choice holds while it fits.
  const views = viewsFor(kind);
  const [chosenView, setChosenView] = useState<FileView | null>(null);
  const view = chosenView !== null && views.includes(chosenView) ? chosenView : (views[0] ?? "text");

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
          <span className="file-editor__eyebrow">{EYEBROWS[kind]}</span>
          <h2>{identity.name || "New agent file"}</h2>
          {path !== "" && (
            <p>{identity.directory === "" ? "Space root" : `${identity.directory}/`} · {typeLabel(path)}</p>
          )}
        </div>
        <div className="file-editor__actions">
          {views.length > 1 && (
            <div className="knowledge__modes file-editor__views" role="group" aria-label="Show as">
              {views.map((choice) => (
                <button
                  type="button"
                  key={choice}
                  aria-pressed={view === choice}
                  disabled={loading}
                  onClick={() => {
                    setChosenView(choice);
                  }}
                >
                  {VIEW_LABELS[choice]}
                </button>
              ))}
            </div>
          )}
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
            {busy ? "Saving…" : SAVE_LABELS[kind]}
          </button>
        </div>
      </div>
      {purpose !== undefined && (
        <p className="file-editor__purpose">
          <strong>Purpose:</strong> {purpose}
        </p>
      )}
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
      {view === "text" || loading ? (
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
      ) : view === "chart" && kind === "data" ? (
        <DataChart spaceId={spaceId} path={path} content={content} dirty={dirty} files={files} onSaved={onSaved} />
      ) : view === "chart" ? (
        <ChartFile spaceId={spaceId} content={content} onContent={setContent} files={files} />
      ) : view === "dashboard" ? (
        <DashboardFile spaceId={spaceId} content={content} onContent={setContent} files={files} />
      ) : (
        <DiagramFile content={content} title={identity.name.replace(/\.(?:mmd|mermaid)$/i, "")} onContent={setContent} />
      )}
      <p className="file-editor__hint">
        {view === "text" && isJson ? "JSON is checked before it is saved. " : ""}
        {view === "text"
          ? "An agent with read_file sees this file; one with write_file may change it, behind the same approval as any write."
          : "Saved as an ordinary file: an agent with write_file can create or change it, behind the same approval as any write."}
      </p>
    </div>
  );
}
