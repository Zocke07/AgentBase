import type {
  KnowledgeEvaluation,
  KnowledgeEvaluationCase,
  KnowledgeGraph,
  KnowledgeIndex,
  KnowledgeNote,
  MemoryIndex,
  MemoryItem,
  MemoryStatus,
  SearchHit,
  SpaceResponse,
} from "@agentspace/schemas";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";

import * as api from "../lib/api";
import { openInObsidian, revealAvailable } from "../lib/folder";

export interface KnowledgeViewProps {
  space: SpaceResponse;
  /** Opens the run a memory came from; absent where no run view is reachable. */
  onOpenRun?: (runId: string) => void;
}

type ViewMode = "split" | "write" | "preview" | "graph" | "evaluate";
type BrowserMode = "notes" | "memories";
type NoteFilter = "all" | "pinned" | "orphans" | "unresolved";

const EMPTY_GRAPH: KnowledgeGraph = { nodes: [], edges: [] };
const TEMPLATE_FOLDER = "templates/";
const DAILY_FOLDER = "daily/";

/**
 * A space's local Markdown vault: browse and edit source, preview it safely,
 * follow links and backlinks, search the same chunks RAG uses, and inspect the graph.
 */
export function KnowledgeView({ space, onOpenRun }: KnowledgeViewProps) {
  const [index, setIndex] = useState<KnowledgeIndex | null>(null);
  const [memories, setMemories] = useState<MemoryIndex | null>(null);
  const [browserMode, setBrowserMode] = useState<BrowserMode>("notes");
  const [note, setNote] = useState<KnowledgeNote | null>(null);
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [mode, setMode] = useState<ViewMode>("split");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph>(EMPTY_GRAPH);
  const [busy, setBusy] = useState(false);
  const [deleteAsked, setDeleteAsked] = useState(false);
  const [forgetAsked, setForgetAsked] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [overwriteImport, setOverwriteImport] = useState(false);
  const [folderFilter, setFolderFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [noteFilter, setNoteFilter] = useState<NoteFilter>("all");
  const [tagChip, setTagChip] = useState<string | null>(null);
  const [mergeSelection, setMergeSelection] = useState<string[]>([]);
  const [mergeTitle, setMergeTitle] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const importInput = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    const [nextIndex, nextMemories] = await Promise.all([
      api.listKnowledge(space.id),
      api.listMemories(space.id),
    ]);
    setIndex(nextIndex);
    setMemories(nextMemories);
    return nextIndex;
  }, [space.id]);

  useEffect(() => {
    void Promise.all([api.listKnowledge(space.id), api.listMemories(space.id)])
      .then(([nextIndex, nextMemories]) => {
        setIndex(nextIndex);
        setMemories(nextMemories);
      })
      .catch((failure: unknown) => {
        setError(asMessage(failure));
      });
  }, [space.id]);

  useEffect(() => {
    importInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const openNote = useCallback(
    async (wanted: string) => {
      setBusy(true);
      setError(null);
      try {
        const loaded = await api.getKnowledgeNote(space.id, wanted);
        setNote(loaded);
        setPath(loaded.path);
        setContent(loaded.content);
        setCreating(false);
        setDeleteAsked(false);
        setMoving(false);
        if (mode === "graph" || mode === "evaluate") setMode("split");
      } catch (failure) {
        setError(asMessage(failure));
      } finally {
        setBusy(false);
      }
    },
    [mode, space.id],
  );

  const resolveLink = useCallback(
    (target: string): string | null => {
      const clean = target.split("#", 1)[0]?.split("|", 1)[0]?.trim().replace(/\.md$/i, "");
      if (!clean) return null;
      const candidates = index?.notes ?? [];
      const exact = candidates.find((item) => item.path.replace(/\.md$/i, "") === clean);
      if (exact !== undefined) return exact.path;
      const tail = clean.split("/").at(-1)?.toLocaleLowerCase();
      return (
        candidates.find(
          (item) => item.path.replace(/\.md$/i, "").split("/").at(-1)?.toLocaleLowerCase() === tail,
        )?.path ?? null
      );
    },
    [index],
  );

  const save = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      let saved: KnowledgeNote;
      if (note !== null && path !== note.path) {
        const moved = await api.moveKnowledgeNote(space.id, note.path, path);
        saved = moved.note;
        setMessage(
          `Moved note and updated ${String(moved.updated_links)} link${moved.updated_links === 1 ? "" : "s"}. Backup: ${moved.backup_path}`,
        );
      } else {
        saved = await api.saveKnowledgeNote(space.id, path, content);
        setMessage("Saved. Retrieval now uses this version.");
      }
      setNote(saved);
      setPath(saved.path);
      setContent(saved.content);
      setCreating(false);
      setDeleteAsked(false);
      setMoving(false);
      await reload();
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (note === null) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteKnowledgeNote(space.id, note.path);
      setNote(null);
      setPath("");
      setContent("");
      await reload();
      setMessage(`${note.path} was deleted.`);
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (query.trim() === "") {
      setHits(null);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setHits(
        (
          await api.searchKnowledge(space.id, query, 8, {
            folders: folderFilter.trim() === "" ? [] : [folderFilter.trim()],
            tags: tagFilter.trim() === "" ? [] : [tagFilter.trim().replace(/^#/, "")],
          })
        ).hits,
      );
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const showGraph = async () => {
    setMode("graph");
    setError(null);
    try {
      setGraph(await api.getKnowledgeGraph(space.id));
    } catch (failure) {
      setError(asMessage(failure));
    }
  };

  const curateMemory = async (
    memory: MemoryItem,
    changes: { status?: MemoryStatus; pinned?: boolean },
  ) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateMemory(space.id, memory.path, changes);
      await reload();
      setMessage("Memory trust state updated. Retrieval reflects it immediately.");
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const forgetMemory = async (memory: MemoryItem) => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteKnowledgeNote(space.id, memory.path);
      setForgetAsked(null);
      setMergeSelection((current) => current.filter((item) => item !== memory.path));
      if (note?.path === memory.path) {
        setNote(null);
        setPath("");
        setContent("");
      }
      await reload();
      setMessage(`${memory.title} was forgotten.`);
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const mergeSelected = async () => {
    if (mergeSelection.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const merged = await api.mergeMemories(
        space.id,
        mergeSelection,
        mergeTitle.trim() === "" ? undefined : mergeTitle.trim(),
      );
      setMergeSelection([]);
      setMergeTitle("");
      await reload();
      setMessage(
        `Merged ${String(merged.archived_paths.length)} memories into ${merged.memory.path}; the originals are archived. Backup: ${merged.backup_path}`,
      );
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const pinCurrent = async () => {
    if (note === null) return;
    setBusy(true);
    setError(null);
    try {
      const pinned = await api.pinKnowledgeNote(space.id, note.path, !note.pinned);
      setNote(pinned);
      setContent(pinned.content);
      await reload();
      setMessage(pinned.pinned ? "Pinned. It now passes every retrieval filter." : "Unpinned.");
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const startNote = (nextPath: string, nextContent: string) => {
    setNote(null);
    setCreating(true);
    setPath(nextPath);
    setContent(nextContent);
    setMode("split");
    setDeleteAsked(false);
    setMoving(false);
    setMessage(null);
  };

  const templates = (index?.notes ?? []).filter((item) => item.path.startsWith(TEMPLATE_FOLDER));

  const newFromTemplate = async (templatePath: string) => {
    setBusy(true);
    setError(null);
    try {
      const template = await api.getKnowledgeNote(space.id, templatePath);
      const stem = templatePath.slice(TEMPLATE_FOLDER.length).replace(/\.md$/i, "");
      startNote(`${stem}-${today()}.md`, fillTemplate(template.content, stem));
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const dailyNote = async () => {
    const date = today();
    const dailyPath = `${DAILY_FOLDER}${date}.md`;
    if ((index?.notes ?? []).some((item) => item.path === dailyPath)) {
      await openNote(dailyPath);
      return;
    }
    const template = templates.find((item) => item.path === `${TEMPLATE_FOLDER}daily.md`);
    if (template === undefined) {
      startNote(dailyPath, `---\ntags: [daily]\n---\n# ${date}\n\n`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const loaded = await api.getKnowledgeNote(space.id, template.path);
      startNote(dailyPath, fillTemplate(loaded.content, date));
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const importVault = async (event: ChangeEvent<HTMLInputElement>) => {
    const selected = [...(event.target.files ?? [])];
    event.target.value = "";
    const markdown = selected.filter((file) => {
      const path = file.webkitRelativePath || file.name;
      return path.toLocaleLowerCase().endsWith(".md") && !path.split("/").some((part) => part.startsWith("."));
    });
    if (markdown.length === 0) {
      setError("That folder contains no visible Markdown notes.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const files = await Promise.all(
        markdown.map(async (file) => ({
          path: importedPath(file.webkitRelativePath || file.name),
          content: await file.text(),
        })),
      );
      const imported = await api.importKnowledge(space.id, files, overwriteImport);
      await reload();
      setMessage(
        `Imported ${String(imported.created)} new and ${String(imported.updated)} updated notes; skipped ${String(imported.skipped)} conflicts.${imported.backup_path === null ? "" : ` Backup: ${imported.backup_path}`}`,
      );
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  const stats = index?.stats;
  const selected = note !== null || creating;
  const visibleNotes = (index?.notes ?? []).filter(
    (item) =>
      (noteFilter === "all" ||
        (noteFilter === "pinned" && item.pinned === true) ||
        (noteFilter === "orphans" && (item.backlinks ?? []).length === 0) ||
        (noteFilter === "unresolved" && (item.unresolved_links ?? []).length > 0)) &&
      (tagChip === null || (item.tags ?? []).includes(tagChip)),
  );
  const topTags = tagCounts(index?.notes ?? []).slice(0, 12);

  return (
    <div className="knowledge" data-testid="knowledge-view">
      <aside className="knowledge__browser">
        <div className="knowledge__browser-head">
          <div>
            <h2>Vault</h2>
            <p>
              {stats?.note_count ?? 0} notes · {stats?.link_count ?? 0} links · {stats?.chunk_count ?? 0}{" "}
              memory chunks
            </p>
            {index !== null && (
              <small>
                indexed {index.index_status.changed_files} changed · {index.index_status.reused_files} reused ·{" "}
                {Math.round(index.index_status.duration_ms)} ms
                {index.index_status.truncated && " · over the 10,000-note limit; some notes are not indexed"}
              </small>
            )}
            {stats !== undefined && ((stats.orphan_count ?? 0) > 0 || (stats.unresolved_link_count ?? 0) > 0) && (
              <small>
                {stats.orphan_count ?? 0} orphan{stats.orphan_count === 1 ? "" : "s"} ·{" "}
                {stats.unresolved_link_count ?? 0} unresolved link{stats.unresolved_link_count === 1 ? "" : "s"}
              </small>
            )}
          </div>
          {browserMode === "notes" && (
            <div className="knowledge__new">
              <button
                type="button"
                className="button button--small"
                onClick={() => {
                  startNote("knowledge/untitled.md", "---\ntags: []\n---\n# New note\n\n");
                }}
              >
                New note
              </button>
              <button type="button" className="button button--small" disabled={busy} onClick={() => void dailyNote()}>
                Daily note
              </button>
              {templates.length > 0 && (
                <select
                  aria-label="New note from template"
                  value=""
                  disabled={busy}
                  onChange={(event) => {
                    if (event.target.value !== "") void newFromTemplate(event.target.value);
                  }}
                >
                  <option value="">From template…</option>
                  {templates.map((template) => (
                    <option key={template.path} value={template.path}>
                      {template.title}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        <div className="knowledge__browser-tabs" role="tablist" aria-label="Vault browser">
          <button
            type="button"
            role="tab"
            aria-selected={browserMode === "notes"}
            onClick={() => {
              setBrowserMode("notes");
            }}
          >
            Notes
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={browserMode === "memories"}
            onClick={() => {
              setBrowserMode("memories");
              setHits(null);
            }}
          >
            Memory inbox {memories === null ? "" : `(${String(memories.proposed)})`}
          </button>
        </div>

        {browserMode === "notes" && <form
          className="knowledge__search"
          onSubmit={(event) => {
            event.preventDefault();
            void search();
          }}
        >
          <label className="sr-only" htmlFor="knowledge-search">
            Search knowledge
          </label>
          <input
            id="knowledge-search"
            value={query}
            placeholder="Search notes, tags or titles"
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
          <button type="submit" className="button button--small" disabled={busy}>
            Search
          </button>
          <div className="knowledge__filters">
            <input
              aria-label="Folder filter"
              value={folderFilter}
              placeholder="folder"
              onChange={(event) => {
                setFolderFilter(event.target.value);
              }}
            />
            <input
              aria-label="Tag filter"
              value={tagFilter}
              placeholder="#tag"
              onChange={(event) => {
                setTagFilter(event.target.value);
              }}
            />
          </div>
        </form>}

        {browserMode === "notes" && (
          <div className="knowledge__import">
            <input
              ref={importInput}
              className="sr-only"
              aria-label="Import Obsidian vault folder"
              type="file"
              multiple
              onChange={(event) => void importVault(event)}
            />
            <button
              type="button"
              className="link"
              disabled={busy}
              onClick={() => importInput.current?.click()}
            >
              Import vault folder
            </button>
            <label>
              <input
                type="checkbox"
                checked={overwriteImport}
                onChange={(event) => {
                  setOverwriteImport(event.target.checked);
                }}
              />{" "}
              replace conflicts with backup
            </label>
          </div>
        )}

        {browserMode === "notes" && hits === null && (
          <div className="knowledge__browse-filters">
            <select
              aria-label="Show notes"
              value={noteFilter}
              onChange={(event) => {
                setNoteFilter(event.target.value as NoteFilter);
              }}
            >
              <option value="all">All notes</option>
              <option value="pinned">Pinned</option>
              <option value="orphans">Orphans (no backlinks)</option>
              <option value="unresolved">With unresolved links</option>
            </select>
            {topTags.length > 0 && (
              <div className="knowledge__chips" role="group" aria-label="Filter by tag">
                {topTags.map(([tag, count]) => (
                  <button
                    type="button"
                    key={tag}
                    className="knowledge__chip"
                    aria-pressed={tagChip === tag}
                    onClick={() => {
                      setTagChip((current) => (current === tag ? null : tag));
                    }}
                  >
                    #{tag} <span>{count}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {browserMode === "memories" ? (
          <MemoryInbox
            memories={memories}
            busy={busy}
            forgetAsked={forgetAsked}
            selection={mergeSelection}
            mergeTitle={mergeTitle}
            onOpen={(wanted) => void openNote(wanted)}
            onOpenRun={onOpenRun}
            onCurate={(memory, changes) => void curateMemory(memory, changes)}
            onAskForget={setForgetAsked}
            onForget={(memory) => void forgetMemory(memory)}
            onToggleSelect={(memoryPath) => {
              setMergeSelection((current) =>
                current.includes(memoryPath)
                  ? current.filter((item) => item !== memoryPath)
                  : [...current, memoryPath],
              );
            }}
            onMergeTitle={setMergeTitle}
            onMerge={() => void mergeSelected()}
          />
        ) : hits !== null ? (
          <div className="knowledge__results" aria-label="Retrieval results">
            <div className="knowledge__result-head">
              <strong>{hits.length} retrieval matches</strong>
              <button
                type="button"
                className="link"
                onClick={() => {
                  setHits(null);
                  setQuery("");
                }}
              >
                Clear
              </button>
            </div>
            {hits.map((hit) => (
              <button
                type="button"
                className="knowledge__result"
                key={`${hit.path}:${hit.heading ?? ""}`}
                onClick={() => void openNote(hit.path)}
              >
                <code>{hit.citation}</code>
                <span>{hit.excerpt}</span>
                <small>
                  {Math.round(hit.score * 100)}% relevance · {hit.estimated_tokens ?? 0} tokens
                </small>
                {(hit.reasons ?? []).length > 0 && <small>{(hit.reasons ?? []).join(" · ")}</small>}
              </button>
            ))}
          </div>
        ) : (
          <ol className="knowledge__notes">
            {visibleNotes.map((item) => (
              <li key={item.path}>
                <button
                  type="button"
                  className={item.path === note?.path ? "knowledge__note knowledge__note--active" : "knowledge__note"}
                  onClick={() => void openNote(item.path)}
                >
                  <strong>
                    {item.pinned === true && <span className="knowledge__pin" aria-label="Pinned">★ </span>}
                    {item.title}
                  </strong>
                  <span>{item.path}</span>
                  <small>{item.excerpt || "Empty note"}</small>
                </button>
              </li>
            ))}
            {index !== null && index.notes.length === 0 && (
              <li className="knowledge__empty">Create a note or open this space as an Obsidian vault.</li>
            )}
            {index !== null && index.notes.length > 0 && visibleNotes.length === 0 && (
              <li className="knowledge__empty">No notes match this filter.</li>
            )}
          </ol>
        )}
      </aside>

      <main className="knowledge__workspace">
        <div className="knowledge__toolbar">
          <div className="knowledge__modes" role="group" aria-label="Knowledge view">
            {(["split", "write", "preview"] as const).map((choice) => (
              <button
                type="button"
                key={choice}
                aria-pressed={mode === choice}
                onClick={() => {
                  setMode(choice);
                }}
              >
                {choice === "split" ? "Split" : choice === "write" ? "Write" : "Preview"}
              </button>
            ))}
            <button type="button" aria-pressed={mode === "graph"} onClick={() => void showGraph()}>
              Graph
            </button>
            <button
              type="button"
              aria-pressed={mode === "evaluate"}
              onClick={() => {
                setMode("evaluate");
              }}
            >
              Evaluate
            </button>
          </div>
          <div className="knowledge__actions">
            {revealAvailable() && (
              <button
                type="button"
                className="button button--small"
                onClick={() => {
                  void openInObsidian(space.folder).catch((failure: unknown) => {
                    setError(asMessage(failure));
                  });
                }}
              >
                Open in Obsidian
              </button>
            )}
            {selected && mode !== "graph" && mode !== "evaluate" && (
              <>
                {note !== null && (
                  deleteAsked ? (
                    <span className="roster__confirm">
                      <span>Delete {note.path}?</span>
                      <button
                        type="button"
                        className="button button--small button--danger"
                        disabled={busy}
                        onClick={() => void remove()}
                      >
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
                      className="button button--small button--danger"
                      onClick={() => {
                        setDeleteAsked(true);
                      }}
                    >
                      Delete note…
                    </button>
                  )
                )}
                {note !== null && !moving && (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      setMoving(true);
                      setDeleteAsked(false);
                    }}
                  >
                    Move or rename…
                  </button>
                )}
                {note !== null && !moving && (
                  <button type="button" className="button button--small" disabled={busy} onClick={() => void pinCurrent()}>
                    {note.pinned === true ? "Unpin note" : "Pin note"}
                  </button>
                )}
                <button type="button" className="button button--small button--primary" disabled={busy || path.trim() === ""} onClick={() => void save()}>
                  {moving ? "Move note" : "Save note"}
                </button>
              </>
            )}
          </div>
        </div>

        {error !== null && <p className="form-error knowledge__notice" role="alert">{error}</p>}
        {message !== null && <p className="knowledge__notice knowledge__notice--ok" role="status">{message}</p>}

        {mode === "graph" ? (
          <KnowledgeGraphView graph={graph} onOpen={(wanted) => void openNote(wanted)} />
        ) : mode === "evaluate" ? (
          <KnowledgeEvaluationView spaceId={space.id} />
        ) : selected ? (
          <>
            <label className="knowledge__path">
              <span>Note path</span>
              <input
                aria-label="Note path"
                value={path}
                disabled={note !== null && !moving}
                onChange={(event) => {
                  setPath(event.target.value);
                }}
              />
            </label>

            {note !== null && (
              <NoteMetadata note={note} onOpen={(wanted) => void openNote(wanted)} />
            )}

            <div className={`knowledge__document knowledge__document--${mode}`}>
              {mode !== "preview" && (
                <textarea
                  className="knowledge__editor"
                  aria-label="Markdown source"
                  spellCheck="true"
                  value={content}
                  onChange={(event) => {
                    setContent(event.target.value);
                    setMessage(null);
                  }}
                />
              )}
              {mode !== "write" && (
                <article className="knowledge__preview" aria-label="Markdown preview">
                  <MarkdownPreview
                    source={content}
                    onLink={(target) => {
                      const resolved = resolveLink(target);
                      if (resolved !== null) void openNote(resolved);
                    }}
                  />
                </article>
              )}
            </div>
          </>
        ) : (
          <div className="knowledge__welcome">
            <h2>Shared knowledge for people and agents</h2>
            <p>
              Notes are ordinary Markdown files. Link them with <code>[[note names]]</code>, add YAML properties,
              edit them here or in Obsidian, and AgentSpace will retrieve cited excerpts automatically for every run.
            </p>
            <p>Completed runs are saved under <code>memory/runs/</code> and become context for later work.</p>
          </div>
        )}
      </main>
    </div>
  );
}

function MemoryInbox({
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
}: {
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
}) {
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
          <p>{memory.outcome || memory.goal || "Empty memory"}</p>
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

function tagCounts(notes: readonly { tags?: string[] }[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const note of notes) {
    for (const tag of note.tags ?? []) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Obsidian's core template variables: `{{date}}` and `{{title}}`. Nothing else is interpreted. */
function fillTemplate(source: string, title: string): string {
  return source.replaceAll("{{date}}", today()).replaceAll("{{title}}", title);
}

function KnowledgeEvaluationView({ spaceId }: { spaceId: string }) {
  const [source, setSource] = useState("");
  const [result, setResult] = useState<KnowledgeEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const evaluate = async () => {
    const cases = evaluationCases(source);
    if (cases.length === 0) {
      setError("Add at least one line in the form question => expected/note.md");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.evaluateKnowledge(spaceId, cases));
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="knowledge__evaluation">
      <h2>Retrieval evaluation</h2>
      <p>
        Add one question per line, followed by <code>=&gt;</code> and one or more expected note paths.
        This measures whether the right evidence appears before changing ranking behavior.
      </p>
      <textarea
        aria-label="Retrieval evaluation cases"
        rows={9}
        value={source}
        placeholder={"How should storage work? => decisions/storage.md\nWhat improves retention? => research/retention.md"}
        onChange={(event) => { setSource(event.target.value); }}
      />
      <div className="knowledge__evaluation-actions">
        <button type="button" className="button button--primary" disabled={busy} onClick={() => void evaluate()}>
          {busy ? "Evaluating…" : "Run evaluation"}
        </button>
        {error !== null && <p className="form-error" role="alert">{error}</p>}
      </div>
      {result !== null && (
        <div className="knowledge__evaluation-result">
          <strong>
            MRR {Math.round(result.mean_reciprocal_rank * 100)}% · recall@{result.limit}{" "}
            {Math.round(result.mean_recall_at_k * 100)}%
          </strong>
          <ol>
            {result.results.map((item) => (
              <li key={item.question}>
                <span>{item.question}</span>
                <small>
                  expected {item.expected_paths.join(", ")} · retrieved {item.retrieved_paths.join(", ") || "nothing"}
                </small>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function evaluationCases(source: string): KnowledgeEvaluationCase[] {
  return source
    .split("\n")
    .map((line) => line.split("=>", 2).map((part) => part.trim()))
    .filter((parts) => parts.length === 2 && parts[0] !== "" && parts[1] !== "")
    .map(([question = "", expected = ""]) => ({
      question,
      expected_paths: expected.split(",").map((path) => path.trim()).filter(Boolean),
    }))
    .filter((item) => item.expected_paths.length > 0);
}

function importedPath(path: string): string {
  const clean = path.replaceAll("\\", "/").replace(/^\/+/, "");
  const parts = clean.split("/").filter(Boolean);
  return parts.length > 1 ? parts.slice(1).join("/") : clean;
}

function NoteMetadata({ note, onOpen }: { note: KnowledgeNote; onOpen: (path: string) => void }) {
  const properties = Object.entries(note.properties ?? {});
  return (
    <div className="knowledge__metadata">
      {(note.tags ?? []).map((tag) => <span className="knowledge__tag" key={tag}>#{tag}</span>)}
      {properties.map(([name, value]) => (
        <span className="knowledge__property" key={name}><strong>{name}</strong> {value}</span>
      ))}
      {(note.links ?? []).map((path) => (
        <button type="button" className="knowledge__relation" key={`to:${path}`} onClick={() => { onOpen(path); }}>→ {path}</button>
      ))}
      {(note.backlinks ?? []).map((path) => (
        <button type="button" className="knowledge__relation" key={`from:${path}`} onClick={() => { onOpen(path); }}>← <span className="sr-only">Backlink from </span>{path}</button>
      ))}
      {(note.unresolved_links ?? []).map((target) => (
        <span className="knowledge__relation knowledge__relation--unresolved" key={`missing:${target}`} title="No note has this name yet">
          ? {target}
        </span>
      ))}
    </div>
  );
}

function KnowledgeGraphView({ graph, onOpen }: { graph: KnowledgeGraph; onOpen: (path: string) => void }) {
  const { nodes, edges } = useMemo(() => graphElements(graph), [graph]);
  if (nodes.length === 0) return <div className="knowledge__welcome"><p>No linked notes yet.</p></div>;
  return (
    <div className="knowledge__graph" aria-label="Knowledge graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={(_event, node) => { onOpen(node.id); }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function graphElements(graph: KnowledgeGraph): { nodes: Node[]; edges: Edge[] } {
  const radius = Math.max(180, graph.nodes.length * 28);
  const nodes: Node[] = graph.nodes.map((node, index) => {
    const angle = (index / Math.max(1, graph.nodes.length)) * Math.PI * 2;
    return {
      id: node.path,
      data: { label: node.title },
      position: { x: radius + Math.cos(angle) * radius, y: radius + Math.sin(angle) * radius },
      className: "knowledge__graph-node",
    };
  });
  const edges: Edge[] = graph.edges.map((edge, index) => ({
    id: `${edge.source}:${edge.target}:${String(index)}`,
    source: edge.source,
    target: edge.target,
    className: "knowledge__graph-edge",
  }));
  return { nodes, edges };
}

function MarkdownPreview({ source, onLink }: { source: string; onLink: (target: string) => void }) {
  const body = stripFrontmatter(source);
  const lines = body.split("\n");
  const blocks: ReactNode[] = [];
  let code: string[] | null = null;

  for (const [index, line] of lines.entries()) {
    if (line.trim().startsWith("```")) {
      if (code === null) code = [];
      else {
        blocks.push(<pre key={`code-${String(index)}`}><code>{code.join("\n")}</code></pre>);
        code = null;
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading !== null) {
      const level = Math.min(heading[1]?.length ?? 1, 3);
      const children = inlineMarkdown(heading[2] ?? "", onLink, index);
      blocks.push(level === 1 ? <h1 key={index}>{children}</h1> : level === 2 ? <h2 key={index}>{children}</h2> : <h3 key={index}>{children}</h3>);
      continue;
    }
    const task = /^\s*[-*]\s+\[([ xX])\]\s+(.+)$/.exec(line);
    if (task !== null) {
      blocks.push(<p className="knowledge__task" key={index}><input type="checkbox" readOnly checked={(task[1] ?? "") !== " "} /> {inlineMarkdown(task[2] ?? "", onLink, index)}</p>);
      continue;
    }
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    if (bullet !== null) {
      blocks.push(<p className="knowledge__bullet" key={index}>• {inlineMarkdown(bullet[1] ?? "", onLink, index)}</p>);
      continue;
    }
    if (line.trim() !== "") blocks.push(<p key={index}>{inlineMarkdown(line, onLink, index)}</p>);
  }
  if (code !== null) blocks.push(<pre key="code-last"><code>{code.join("\n")}</code></pre>);
  return <>{blocks}</>;
}

function inlineMarkdown(source: string, onLink: (target: string) => void, row: number): ReactNode[] {
  const pattern = /(\[\[[^\]]+\]\]|\*\*[^*]+\*\*|`[^`]+`)/g;
  return source.split(pattern).filter(Boolean).map((part, index) => {
    const key = `${String(row)}:${String(index)}`;
    if (part.startsWith("[[") && part.endsWith("]]")) {
      const target = part.slice(2, -2);
      const label = target.split("|", 2)[1] ?? target;
      return <button type="button" className="knowledge__wiki-link" key={key} onClick={() => { onLink(target); }}>{label}</button>;
    }
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key}>{part.slice(1, -1)}</code>;
    return <Fragment key={key}>{part}</Fragment>;
  });
}

function stripFrontmatter(source: string): string {
  if (!source.startsWith("---\n")) return source;
  const end = source.indexOf("\n---", 4);
  return end < 0 ? source : source.slice(end + 4).replace(/^\n/, "");
}

function asMessage(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
