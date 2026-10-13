import type { TextFileSummary } from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { failureMessage, isMissing } from "../lib/errors";
import { VIEW_LABELS, VISUAL_TEMPLATES, viewsFor, type FileView } from "../lib/fileViews";
import { openWorkbook, revealAvailable, revealFolder } from "../lib/folder";
import { STARTERS } from "../lib/pipeline";
import { scrollToActive } from "../lib/scroll";
import { fileKind, uniquePath, type FileKind } from "../lib/visualization";
import { isWorkingFile } from "../state/files";
import { sectionOf } from "../state/sections";
import { useFetched } from "../state/useFetched";

import { ChartFile, DashboardFile, DataChart, DataPreview, DiagramFile } from "./FileViews";

/**
 * Space-folder config/data files and generated Excel workbooks. The text
 * editor validates JSON before saving and uses sidecar note-equivalent path
 * rules; workbooks stay binary and are downloaded. A data file can be drawn
 * as a chart, and a saved chart, dashboard or diagram opens drawn.
 */

export interface FilesPanelProps {
  spaceId: string;
  /** The space's folder on disk, where the shell opens a workbook from. */
  folder?: string | undefined;
  /** Render browser list or workspace editor. */
  part: "list" | "editor";
  /** Parent-shared editor file. */
  open: OpenFile | null;
  onOpen: (file: OpenFile | null) => void;
  /** File write/delete; parent may reload folder consumers. */
  onChanged?: (() => void) | undefined;
  /** Parent bump after other-half file changes; reload list. */
  reloadNonce?: number | undefined;
  /**
   * Which files the list shows: under Technical Details only the raw data,
   * settings and records; workbooks and charts are in User Summary.
   */
  scope?: "technical" | "all" | undefined;
  /** Told whenever the open file gains or loses unsaved changes. */
  onDirtyChange?: ((dirty: boolean) => void) | undefined;
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
  if (isWorkbook(path)) return "Excel workbook";
  return DRAWN_TYPES[fileKind(path)] ?? fileType(path);
}

function isWorkbook(path: string): boolean {
  return path.toLowerCase().endsWith(".xlsx");
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

export function FilesPanel({
  spaceId,
  folder,
  part,
  open,
  onOpen,
  onChanged,
  reloadNonce = 0,
  scope = "all",
  onDirtyChange,
}: FilesPanelProps) {
  const load = useCallback(() => api.listFiles(spaceId), [spaceId]);
  const files = useFetched(load, null);
  const everything = files.data?.files ?? NO_FILES;
  const list = scope === "technical" ? everything.filter((file) => sectionOf(file.path) === "technical") : everything;
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
              {scope === "all" && (
                <optgroup label="Charts and diagrams">
                  {VISUAL_TEMPLATES.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.label}
                    </option>
                  ))}
                </optgroup>
              )}
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
            The files could not be listed: {files.error}{" "}
            <button type="button" className="link" onClick={reload}>
              Try again
            </button>
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
          Pick a file on the left, or create one. These are the plain-text inputs, collected data and records in the
          space folder that agents read with read_file.
        </p>
        <p>
          Each opens in Preview, as a table where it has rows. Text shows its source for editing, and Chart draws a
          CSV or JSON file; a saved chart opens with your results in User Summary.
        </p>
      </div>
    );
  }

  if (isWorkbook(open.path) && !open.fresh) {
    return (
      <Workbook
        key={`${spaceId}:${open.path}`}
        spaceId={spaceId}
        folder={folder}
        path={open.path}
        onClose={() => {
          onOpen(null);
        }}
      />
    );
  }

  return (
    <FileEditor
      key={`${spaceId}:${open.path}:${String(open.fresh)}`}
      spaceId={spaceId}
      open={open}
      files={everything}
      onDirtyChange={onDirtyChange}
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

/**
 * Workbooks stay binary. In the app the shell opens one in the person's
 * spreadsheet app, or shows its folder; a browser tab downloads a copy.
 */
function Workbook({
  spaceId,
  folder,
  path,
  onClose,
}: {
  spaceId: string;
  folder: string | undefined;
  path: string;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const identity = pathParts(path);
  const onDisk = revealAvailable() && folder !== undefined ? `${folder}/${path}` : null;

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failureMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    const blob = await api.downloadFile(spaceId, path);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = identity.name;
    link.click();
    // Revoking at once can cancel the download before it starts.
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 60_000);
  };

  return (
    <div className="file-editor" data-testid="files-editor">
      <div className="file-editor__head">
        <div className="file-editor__identity">
          <span className="file-editor__eyebrow">Excel workbook</span>
          <h2>{identity.name}</h2>
          <p>{identity.directory === "" ? "Space root" : `${identity.directory}/`}</p>
        </div>
        <div className="file-editor__actions">
          <button type="button" className="button button--small" onClick={onClose}>
            Close
          </button>
          {onDisk === null ? (
            <button type="button" className="button button--small button--primary" disabled={busy} onClick={() => void act(download)}>
              {busy ? "Downloading…" : "Download Excel workbook"}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="button button--small"
                disabled={busy}
                onClick={() => void act(() => revealFolder(onDisk.slice(0, onDisk.lastIndexOf("/"))))}
              >
                Show in folder
              </button>
              <button
                type="button"
                className="button button--small button--primary"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    try {
                      await openWorkbook(onDisk);
                    } catch (failure) {
                      throw new Error(
                        `${failureMessage(failure)} Show in folder opens its folder instead, where you can open it yourself.`,
                        { cause: failure },
                      );
                    }
                  })
                }
              >
                Open in spreadsheet app
              </button>
            </>
          )}
        </div>
      </div>
      <p className="file-editor__purpose">
        Each month has its own workbook. Every market session gets a sheet with one row per stock: the prediction
        for 1 day, 2 days, 3 days, 1 week and 1 month ahead, and the actual closing price beside it once that day
        has traded. The last sheet lists every forecast with its method, assumptions and sources.
      </p>
      <p className="file-editor__hint">
        Later runs fill in actual prices, so reopen the workbook after a run to see them.
      </p>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function FileEditor({
  spaceId,
  open,
  files,
  onSaved,
  onDeleted,
  onCancel,
  onDirtyChange,
}: {
  spaceId: string;
  open: OpenFile;
  /** The space's files, for the data and charts a chart or dashboard can use. */
  files: readonly TextFileSummary[];
  onSaved: (path: string) => void;
  onDeleted: () => void;
  onCancel: () => void;
  onDirtyChange?: ((dirty: boolean) => void) | undefined;
}) {
  const starter = STARTERS.find((candidate) => candidate.path === open.path);
  const purpose = open.fresh ? (open.purpose ?? starter?.why) : starter?.why;
  const [path, setPath] = useState(open.path);
  const [content, setContent] = useState(open.fresh ? (open.content ?? starter?.content ?? "") : "");
  // What the disk holds; null until read, so nothing unread can be saved over it.
  const [baseline, setBaseline] = useState<string | null>(open.fresh ? "" : null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteAsked, setDeleteAsked] = useState(false);
  const [closeAsked, setCloseAsked] = useState(false);

  useEffect(() => {
    if (open.fresh) return undefined;
    let live = true;
    void api
      .getFile(spaceId, open.path)
      .then((file) => {
        if (!live) return;
        setContent(file.content);
        setBaseline(file.content);
        setLoadError(null);
      })
      .catch((failure: unknown) => {
        if (!live) return;
        setLoadError(
          isMissing(failure)
            ? `${open.path} is no longer in this space; a run or another window may have removed it.`
            : failureMessage(failure),
        );
      });
    return () => {
      live = false;
    };
  }, [spaceId, open.path, open.fresh, attempt]);

  const loading = baseline === null && loadError === null;
  const dirty = baseline !== null && content !== baseline;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  // Leaving clears the mark, saved or discarded.
  useEffect(
    () => () => {
      onDirtyChange?.(false);
    },
    [onDirtyChange],
  );

  const isJson = path.trim().toLowerCase().endsWith(".json");
  const identity = pathParts(path);
  const kind = fileKind(path);
  // A file opens in its first view, a Preview where it has one; a new file
  // has nothing to preview yet. The person's choice holds while it fits.
  const views = viewsFor(kind);
  const [chosenView, setChosenView] = useState<FileView | null>(null);
  const opening = open.fresh && views[0] === "preview" ? "text" : (views[0] ?? "text");
  const view = chosenView !== null && views.includes(chosenView) ? chosenView : opening;

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
        setError(`Not valid JSON: ${failureMessage(failure)}`);
        return;
      }
    }
    setBusy(true);
    try {
      // A new file never replaces one already at its path.
      const saved = await api.writeFile(spaceId, wanted, content, { create: open.fresh });
      setBaseline(saved.content);
      onSaved(saved.path);
    } catch (failure) {
      setError(failureMessage(failure));
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
      // Already gone is what was asked for.
      if (isMissing(failure)) onDeleted();
      else setError(failureMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  if (loadError !== null) {
    return (
      <div className="file-editor" data-testid="files-editor">
        <div className="file-editor__head">
          <div className="file-editor__identity">
            <span className="file-editor__eyebrow">{EYEBROWS[kind]}</span>
            <h2>{identity.name}</h2>
            <p>{identity.directory === "" ? "Space root" : `${identity.directory}/`}</p>
          </div>
          <div className="file-editor__actions">
            <button type="button" className="button button--small" onClick={onCancel}>
              Close
            </button>
            <button
              type="button"
              className="button button--small button--primary"
              onClick={() => {
                setLoadError(null);
                setAttempt((current) => current + 1);
              }}
            >
              Try again
            </button>
          </div>
        </div>
        <p className="field-error" role="alert">
          This file could not be opened: {loadError}
        </p>
        <p className="file-editor__hint">Nothing was changed. It cannot be edited until it opens.</p>
      </div>
    );
  }

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
                disabled={busy || loading}
                onClick={() => {
                  setDeleteAsked(true);
                  setCloseAsked(false);
                }}
              >
                Delete…
              </button>
            ))}
          {closeAsked ? (
            <span className="roster__confirm" role="alertdialog" aria-label="Unsaved changes">
              <span>Close without saving your changes?</span>
              <button type="button" className="button button--small button--danger" onClick={onCancel}>
                Discard and close
              </button>
              <button
                type="button"
                className="button button--small"
                onClick={() => {
                  setCloseAsked(false);
                }}
              >
                Keep editing
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="button button--small"
              disabled={busy}
              onClick={() => {
                if (dirty) {
                  setCloseAsked(true);
                  setDeleteAsked(false);
                } else {
                  onCancel();
                }
              }}
            >
              Close
            </button>
          )}
          <button
            type="button"
            className="button button--small button--primary"
            disabled={busy || loading || (!dirty && !open.fresh)}
            onClick={() => void save()}
          >
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
      {loading ? (
        <p className="file-editor__loading" role="status">
          Opening {identity.name}…
        </p>
      ) : view === "preview" ? (
        <DataPreview path={path} content={content} />
      ) : view === "text" ? (
        <textarea
          className="file-editor__text"
          aria-label="File contents"
          spellCheck={false}
          value={content}
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
        {view === "preview"
          ? "Preview only reads the file. Choose Text to change it."
          : view === "text" && isJson
            ? "JSON is checked before it is saved. An agent with read_file sees this file; one with write_file may change it, behind the same approval as any write."
            : view === "text"
              ? "An agent with read_file sees this file; one with write_file may change it, behind the same approval as any write."
              : "Saved as an ordinary file: an agent with write_file can create or change it, behind the same approval as any write."}
      </p>
    </div>
  );
}
