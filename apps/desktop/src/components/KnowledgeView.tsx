import type {
  KnowledgeGraph,
  KnowledgeIndex,
  KnowledgeNote,
  MemoryIndex,
  MemoryItem,
  MemoryStatus,
  SearchHit,
  SpaceResponse,
} from "@agentspace/schemas";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import * as api from "../lib/api";
import { obsidianAvailable, openInObsidian } from "../lib/folder";
import { fuzzyFilter } from "../lib/fuzzy";
import { forceLayout } from "../lib/graphLayout";
import { countWords, toggleTaskLine } from "../lib/markdown";
import { useFetched } from "../state/useFetched";

import { KnowledgeEvaluationView } from "./KnowledgeEvaluation";
import { Markdown } from "./Markdown";
import { MemoryInbox } from "./MemoryInbox";
import { NoteEditor } from "./NoteEditor";
import { NoteTree } from "./NoteTree";
import { QuickSwitcher } from "./QuickSwitcher";

/**
 * A space's local Markdown vault, laid out the way Obsidian lays out one: a
 * file explorer on the left, the note in the middle in source, preview or
 * both, and the note's links and backlinks beneath it. Notes are ordinary
 * files; nothing here is stored anywhere but the folder.
 */

export interface KnowledgeViewProps {
  space: SpaceResponse;
  /** Opens the run a memory came from; absent where no run view is reachable. */
  onOpenRun?: (runId: string) => void;
  /**
   * A note another section asked to open; a new `nonce` is a new request.
   * `inbox` opens it beside the memory inbox rather than the file tree.
   */
  openRequest?: { path: string; heading: string | null; nonce: number; inbox?: boolean } | undefined;
  /** Bumped when another section changed a memory, so the inbox is re-read. */
  reloadNonce?: number;
  /** How many memories wait for a decision, for a badge outside this view. */
  onInboxCount?: ((proposed: number) => void) | undefined;
}

type ViewMode = "split" | "write" | "preview" | "graph" | "evaluate";
type BrowserMode = "notes" | "memories";
type NoteFilter = "all" | "pinned" | "orphans" | "unresolved";
type GraphScope = "vault" | "local";

const EMPTY_GRAPH: KnowledgeGraph = { nodes: [], edges: [] };
const TEMPLATE_FOLDER = "templates/";
const DAILY_FOLDER = "daily/";
const NEW_NOTE = "---\ntags: []\n---\n# New note\n\n";
/** How long a confirmation stays on screen before it goes by itself. */
const TOAST_MS = 6_000;

export function KnowledgeView({
  space,
  onOpenRun,
  openRequest,
  reloadNonce = 0,
  onInboxCount,
}: KnowledgeViewProps) {
  const [index, setIndex] = useState<KnowledgeIndex | null>(null);
  const [memories, setMemories] = useState<MemoryIndex | null>(null);
  const [browserMode, setBrowserMode] = useState<BrowserMode>("notes");
  const [note, setNote] = useState<KnowledgeNote | null>(null);
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  // What the editor last agreed with the disk about; the difference is "unsaved".
  const [baseline, setBaseline] = useState("");
  const [creating, setCreating] = useState(false);
  const [mode, setMode] = useState<ViewMode>("split");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph>(EMPTY_GRAPH);
  const [graphScope, setGraphScope] = useState<GraphScope>("vault");
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
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [switcher, setSwitcher] = useState(false);
  const [linksOpen, setLinksOpen] = useState(true);
  // Asked once: the shell looks for Obsidian on disk, and outside it the
  // answer is no without a round trip.
  const obsidian = useFetched(obsidianAvailable, false).data;
  // A note asked for while another has unsaved changes waits for a decision.
  const [pendingOpen, setPendingOpen] = useState<{ path: string; heading: string | null } | null>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const preview = useRef<HTMLElement>(null);
  const wantedHeading = useRef<string | null>(null);

  const dirty = content !== baseline;

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
  }, [space.id, reloadNonce]);

  useEffect(() => {
    importInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  useEffect(() => {
    if (memories !== null) onInboxCount?.(memories.proposed);
  }, [memories, onInboxCount]);

  useEffect(() => {
    if (toast === null) return undefined;
    const timer = window.setTimeout(() => {
      setToast(null);
    }, TOAST_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [toast]);

  const settle = (loaded: KnowledgeNote) => {
    setNote(loaded);
    setPath(loaded.path);
    setContent(loaded.content);
    setBaseline(loaded.content);
    setCreating(false);
    setDeleteAsked(false);
    setMoving(false);
  };

  const openNote = useCallback(
    async (wanted: string, heading: string | null = null) => {
      setBusy(true);
      setError(null);
      setPendingOpen(null);
      try {
        const loaded = await api.getKnowledgeNote(space.id, wanted);
        settle(loaded);
        wantedHeading.current = heading;
        setMode((current) => (current === "graph" || current === "evaluate" ? "split" : current));
      } catch (failure) {
        setError(asMessage(failure));
      } finally {
        setBusy(false);
      }
    },
    [space.id],
  );

  // Once the preview has the note, scroll to the heading a link named.
  useEffect(() => {
    const heading = wantedHeading.current;
    if (heading === null || note === null) return;
    wantedHeading.current = null;
    const frame = window.requestAnimationFrame(() => {
      const target = [...(preview.current?.querySelectorAll<HTMLElement>("[data-heading]") ?? [])].find(
        (element) => element.dataset.heading?.toLocaleLowerCase() === heading.toLocaleLowerCase(),
      );
      target?.scrollIntoView({ block: "start" });
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [note]);

  /** Open a note unless unsaved work would be lost, in which case ask first. */
  const requestOpen = useCallback(
    (wanted: string, heading: string | null = null) => {
      if (dirty && wanted !== note?.path) {
        setPendingOpen({ path: wanted, heading });
        return;
      }
      void openNote(wanted, heading);
    },
    [dirty, note?.path, openNote],
  );

  // Another section asked for a note (a citation, a memory path).
  const lastRequest = useRef<number | null>(null);
  useEffect(() => {
    if (openRequest === undefined || openRequest.nonce === lastRequest.current) return;
    lastRequest.current = openRequest.nonce;
    setBrowserMode(openRequest.inbox === true ? "memories" : "notes");
    requestOpen(openRequest.path, openRequest.heading);
  }, [openRequest, requestOpen]);

  const resolveLink = useCallback(
    (target: string): string | null => {
      const clean = target.trim().replace(/\.md$/i, "");
      if (clean === "") return null;
      const candidates = index?.notes ?? [];
      const exact = candidates.find((item) => item.path.replace(/\.md$/i, "") === clean);
      if (exact !== undefined) return exact.path;
      const tail = clean.split("/").at(-1)?.toLocaleLowerCase();
      return (
        candidates.find(
          (item) => item.path.replace(/\.md$/i, "").split("/").at(-1)?.toLocaleLowerCase() === tail,
        )?.path ??
        candidates.find((item) => item.title.toLocaleLowerCase() === clean.toLocaleLowerCase())?.path ??
        null
      );
    },
    [index],
  );

  const followLink = (target: string, heading: string | null) => {
    const resolved = resolveLink(target);
    if (resolved !== null) {
      requestOpen(resolved, heading);
      return;
    }
    if (target.trim() === "" && heading !== null && note !== null) {
      wantedHeading.current = heading;
      setNote({ ...note });
      return;
    }
    setToast(`No note is called "${target}" yet. Create it from the Open dialog (Ctrl/Cmd+O).`);
  };

  const filterByTag = (tag: string) => {
    setBrowserMode("notes");
    setHits(null);
    setNoteFilter("all");
    setTagChip(tag);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      let saved: KnowledgeNote;
      if (note !== null && path !== note.path) {
        const moved = await api.moveKnowledgeNote(space.id, note.path, path);
        saved = moved.note;
        setToast(
          `Moved note and updated ${String(moved.updated_links)} link${moved.updated_links === 1 ? "" : "s"}. Backup: ${moved.backup_path}`,
        );
      } else {
        saved = await api.saveKnowledgeNote(space.id, path, content);
        setToast("Saved. Retrieval now uses this version.");
      }
      settle(saved);
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
      setBaseline("");
      await reload();
      setToast(`${note.path} was deleted.`);
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

  const curateMemory = async (memory: MemoryItem, changes: { status?: MemoryStatus; pinned?: boolean }) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateMemory(space.id, memory.path, changes);
      await reload();
      setToast("Memory trust state updated. Retrieval reflects it immediately.");
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
        setBaseline("");
      }
      await reload();
      setToast(`${memory.title} was forgotten.`);
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
      setToast(
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
      setBaseline(pinned.content);
      await reload();
      setToast(pinned.pinned ? "Pinned. It now passes every retrieval filter." : "Unpinned.");
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
    setBaseline(nextContent);
    setMode((current) => (current === "graph" || current === "evaluate" ? "split" : current));
    setDeleteAsked(false);
    setMoving(false);
    setPendingOpen(null);
    setBrowserMode("notes");
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
      requestOpen(dailyPath);
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
      const name = file.webkitRelativePath || file.name;
      return name.toLocaleLowerCase().endsWith(".md") && !name.split("/").some((part) => part.startsWith("."));
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
      setToast(
        `Imported ${String(imported.created)} new and ${String(imported.updated)} updated notes; skipped ${String(imported.skipped)} conflicts.${imported.backup_path === null ? "" : ` Backup: ${imported.backup_path}`}`,
      );
    } catch (failure) {
      setError(asMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  // The dialect's shortcuts, only while this section is the one on screen.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      const element = root.current;
      if (element?.closest("[hidden]") !== null) return;
      const key = event.key.toLocaleLowerCase();
      if (key === "o") {
        event.preventDefault();
        setSwitcher(true);
      } else if (key === "s" && (note !== null || creating) && !busy && path.trim() !== "") {
        event.preventDefault();
        void save();
      } else if (key === "e" && (note !== null || creating)) {
        event.preventDefault();
        setMode((current) => (current === "write" ? "preview" : current === "preview" ? "split" : "write"));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  });

  const stats = index?.stats;
  const selected = note !== null || creating;
  const allNotes = index?.notes ?? [];
  const filtered = allNotes.filter(
    (item) =>
      (noteFilter === "all" ||
        (noteFilter === "pinned" && item.pinned === true) ||
        (noteFilter === "orphans" && (item.backlinks ?? []).length === 0) ||
        (noteFilter === "unresolved" && (item.unresolved_links ?? []).length > 0)) &&
      (tagChip === null || (item.tags ?? []).includes(tagChip)),
  );
  // Typing narrows the tree at once; Enter asks retrieval for ranked excerpts.
  const visibleNotes =
    query.trim() === "" ? filtered : fuzzyFilter(query.trim(), filtered, (item) => `${item.title} ${item.path}`).map((match) => match.item);
  const topTags = tagCounts(allNotes).slice(0, 12);
  const words = selected ? countWords(content) : 0;
  const folder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const fileName = path.slice(folder === "" ? 0 : folder.length + 1);

  return (
    <div className="knowledge" data-testid="knowledge-view" ref={root}>
      <aside className="knowledge__browser">
        <div className="knowledge__browser-head">
          <div className="knowledge__browser-title">
            <h2>{space.name}</h2>
            <p>
              {stats?.note_count ?? 0} notes · {stats?.link_count ?? 0} links · {stats?.tag_count ?? 0} tags
            </p>
            {stats !== undefined && ((stats.orphan_count ?? 0) > 0 || (stats.unresolved_link_count ?? 0) > 0) && (
              <small>
                {stats.orphan_count ?? 0} orphan{stats.orphan_count === 1 ? "" : "s"} ·{" "}
                {stats.unresolved_link_count ?? 0} unresolved link{stats.unresolved_link_count === 1 ? "" : "s"}
              </small>
            )}
          </div>
          <div className="knowledge__new">
            <button
              type="button"
              className="knowledge__icon-button"
              title="Open a note (Ctrl/Cmd+O)"
              aria-label="Open a note"
              onClick={() => {
                setSwitcher(true);
              }}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M8.5 3a5.5 5.5 0 0 1 4.4 8.8l4 4-1.1 1.1-4-4A5.5 5.5 0 1 1 8.5 3zm0 1.6a3.9 3.9 0 1 0 0 7.8 3.9 3.9 0 0 0 0-7.8z" />
              </svg>
            </button>
            <button
              type="button"
              className="knowledge__icon-button"
              title="New note"
              aria-label="New note"
              onClick={() => {
                startNote("knowledge/untitled.md", NEW_NOTE);
              }}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M5 2.5h6.5L15.5 6.5V17.5h-10.5zm1.5 1.5v12h7.5V7.5h-3V4zM9.2 9h1.6v2.2H13v1.6h-2.2V15H9.2v-2.2H7v-1.6h2.2z" />
              </svg>
            </button>
            <button
              type="button"
              className="knowledge__icon-button"
              title="Today's daily note"
              aria-label="Daily note"
              disabled={busy}
              onClick={() => void dailyNote()}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M4 4h12v13H4zm1.5 4.5v7h9v-7zM6 2.5h1.8V5H6zm6.2 0H14V5h-1.8zM7 10h2v2H7zm4 0h2v2h-2zm-4 3h2v2H7z" />
              </svg>
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
                <option value="">Template…</option>
                {templates.map((template) => (
                  <option key={template.path} value={template.path}>
                    {template.title}
                  </option>
                ))}
              </select>
            )}
          </div>
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
            Files
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
            Memory inbox
            {memories !== null && memories.proposed > 0 && (
              <span className="knowledge__badge">{memories.proposed}</span>
            )}
          </button>
        </div>

        {browserMode === "notes" && (
          <form
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
              type="search"
              value={query}
              placeholder="Filter notes; Enter searches their text"
              onChange={(event) => {
                setQuery(event.target.value);
                if (event.target.value.trim() === "") setHits(null);
              }}
            />
            <button type="submit" className="button button--small" disabled={busy}>
              Search
            </button>
            <details className="knowledge__advanced">
              <summary>Filters and import</summary>
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
              <div className="knowledge__import">
                <input
                  ref={importInput}
                  className="sr-only"
                  aria-label="Import Obsidian vault folder"
                  type="file"
                  multiple
                  onChange={(event) => void importVault(event)}
                />
                <button type="button" className="link" disabled={busy} onClick={() => importInput.current?.click()}>
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
            </details>
          </form>
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
            onOpen={(wanted) => {
              requestOpen(wanted);
            }}
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
                onClick={() => {
                  requestOpen(hit.path, hit.heading ?? null);
                }}
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
          <div className="knowledge__notes">
            {visibleNotes.length > 0 && (
              <NoteTree notes={visibleNotes} activePath={note?.path ?? null} onOpen={requestOpen} />
            )}
            {index !== null && index.notes.length === 0 && (
              <p className="knowledge__empty">Create a note or open this space as an Obsidian vault.</p>
            )}
            {index !== null && index.notes.length > 0 && visibleNotes.length === 0 && (
              <p className="knowledge__empty">No notes match this filter.</p>
            )}
          </div>
        )}
      </aside>

      <main className="knowledge__workspace">
        <div className="knowledge__toolbar">
          <div className="knowledge__modes" role="group" aria-label="Knowledge view">
            {(["write", "preview", "split"] as const).map((choice) => (
              <button
                type="button"
                key={choice}
                aria-pressed={mode === choice}
                title={choice === "split" ? "Source and preview side by side" : `${choice === "write" ? "Source" : "Reading view"} (Ctrl/Cmd+E cycles)`}
                onClick={() => {
                  setMode(choice);
                }}
              >
                {choice === "split" ? "Split" : choice === "write" ? "Write" : "Preview"}
              </button>
            ))}
            <span className="knowledge__modes-gap" />
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
            {obsidian && (
              <button
                type="button"
                className="button button--small"
                title="Open this space's folder as a vault in Obsidian"
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
                {note !== null &&
                  (deleteAsked ? (
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
                  ))}
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
                {dirty && !moving && (
                  <span className="knowledge__dirty" data-testid="unsaved">
                    Unsaved
                  </span>
                )}
                <button
                  type="button"
                  className={`button button--small${dirty || moving || creating ? " button--primary" : ""}`}
                  disabled={busy || path.trim() === ""}
                  title="Ctrl/Cmd+S"
                  onClick={() => void save()}
                >
                  {moving ? "Move note" : "Save note"}
                </button>
              </>
            )}
          </div>
        </div>

        {error !== null && (
          <p className="form-error knowledge__notice" role="alert">
            {error}
            <button
              type="button"
              className="link"
              onClick={() => {
                setError(null);
              }}
            >
              dismiss
            </button>
          </p>
        )}

        {pendingOpen !== null && (
          <div className="knowledge__guard" role="alertdialog" aria-label="Unsaved changes" data-testid="unsaved-guard">
            <span>
              {creating ? "The new note" : path} has unsaved changes. Open {pendingOpen.path} anyway?
            </span>
            <button
              type="button"
              className="button button--small button--danger"
              onClick={() => {
                const wanted = pendingOpen;
                setBaseline(content);
                void openNote(wanted.path, wanted.heading);
              }}
            >
              Discard and open
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => {
                setPendingOpen(null);
              }}
            >
              Keep editing
            </button>
          </div>
        )}

        {mode === "graph" ? (
          <KnowledgeGraphView
            graph={graph}
            scope={graphScope}
            focus={note?.path ?? null}
            onScope={setGraphScope}
            onOpen={(wanted) => {
              requestOpen(wanted);
            }}
          />
        ) : mode === "evaluate" ? (
          <KnowledgeEvaluationView spaceId={space.id} />
        ) : selected ? (
          <>
            <div className="knowledge__note-head">
              {creating || moving ? (
                <label className="knowledge__path">
                  <span>{moving ? "New path" : "Note path"}</span>
                  <input
                    aria-label="Note path"
                    value={path}
                    onChange={(event) => {
                      setPath(event.target.value);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void save();
                      }
                    }}
                  />
                  {moving && (
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setMoving(false);
                        if (note !== null) setPath(note.path);
                      }}
                    >
                      cancel
                    </button>
                  )}
                </label>
              ) : (
                <div className="knowledge__crumbs" aria-label="Note path">
                  {folder !== "" &&
                    folder.split("/").map((part, position) => (
                      <span key={`${String(position)}:${part}`}>
                        <span className="knowledge__crumb">{part}</span>
                        <span className="knowledge__crumb-sep" aria-hidden="true">
                          {"›"}
                        </span>
                      </span>
                    ))}
                  <span className="knowledge__crumb knowledge__crumb--file">{fileName}</span>
                  {note?.pinned === true && (
                    <span className="knowledge__pin" title="Pinned: passes every retrieval filter">
                      {"★"}
                    </span>
                  )}
                </div>
              )}
              {note !== null && <NoteMetadata note={note} onTag={filterByTag} />}
            </div>

            <div className={`knowledge__document knowledge__document--${mode}`}>
              {mode !== "preview" && <NoteEditor value={content} notes={allNotes} onChange={setContent} />}
              {mode !== "write" && (
                <article className="knowledge__preview" aria-label="Markdown preview" ref={preview}>
                  <Markdown
                    source={content}
                    onLink={followLink}
                    onTag={filterByTag}
                    onToggleTask={(line, checked) => {
                      setContent((current) => toggleTaskLine(current, line, checked));
                    }}
                  />
                </article>
              )}
            </div>

            {note !== null && (
              <NoteLinks
                note={note}
                open={linksOpen}
                onToggle={() => {
                  setLinksOpen((current) => !current);
                }}
                onOpen={(wanted) => {
                  requestOpen(wanted);
                }}
              />
            )}

            <div className="knowledge__status" aria-label="Note status">
              <span>
                {words} word{words === 1 ? "" : "s"} · {Math.max(1, Math.ceil(words / 200))} min read
              </span>
              {note !== null && <span>updated {new Date(note.updated_at).toLocaleString()}</span>}
              <span className="knowledge__status-hint">
                Ctrl/Cmd+S saves · Ctrl/Cmd+E switches view · Ctrl/Cmd+O opens a note · type [[ to link
              </span>
            </div>
          </>
        ) : (
          <div className="knowledge__welcome">
            <h2>Shared knowledge for people and agents</h2>
            <p>
              Notes are ordinary Markdown files in this space's folder, and the folder is an Obsidian vault.
              AgentSpace retrieves cited excerpts from them for every run; completed runs propose memories back
              into the inbox.
            </p>
            <div className="knowledge__welcome-actions">
              <button
                type="button"
                className="button button--primary"
                onClick={() => {
                  startNote("knowledge/untitled.md", NEW_NOTE);
                }}
              >
                Create a note
              </button>
              <button type="button" className="button" disabled={busy} onClick={() => void dailyNote()}>
                Today's daily note
              </button>
              <button
                type="button"
                className="button"
                onClick={() => {
                  setSwitcher(true);
                }}
              >
                Open a note…
              </button>
            </div>
            <dl className="knowledge__cheatsheet" aria-label="Formatting reference">
              <div>
                <dt>
                  <code>[[note]]</code>
                </dt>
                <dd>link to a note; type <code>[[</code> in the editor to pick one</dd>
              </div>
              <div>
                <dt>
                  <code>#tag</code>
                </dt>
                <dd>tag a note, inline or in its properties</dd>
              </div>
              <div>
                <dt>
                  <code>&gt; [!tip] Title</code>
                </dt>
                <dd>a callout; note, warning, question, example and the rest</dd>
              </div>
              <div>
                <dt>
                  <code>- [ ] task</code>
                </dt>
                <dd>a checkbox you can tick in the preview</dd>
              </div>
              <div>
                <dt>
                  <code>==text==</code>
                </dt>
                <dd>a highlight</dd>
              </div>
            </dl>
          </div>
        )}

        {toast !== null && (
          <div className="knowledge__toast" role="status">
            <span>{toast}</span>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => {
                setToast(null);
              }}
            >
              {"✕"}
            </button>
          </div>
        )}
      </main>

      {switcher && (
        <QuickSwitcher
          notes={allNotes}
          onOpen={(wanted) => {
            setSwitcher(false);
            requestOpen(wanted);
          }}
          onCreate={(wanted) => {
            setSwitcher(false);
            const stem = wanted.replace(/\.md$/i, "").split("/").at(-1) ?? "New note";
            startNote(wanted, `---\ntags: []\n---\n# ${stem}\n\n`);
          }}
          onClose={() => {
            setSwitcher(false);
          }}
        />
      )}
    </div>
  );
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

function importedPath(path: string): string {
  const clean = path.replaceAll("\\", "/").replace(/^\/+/, "");
  const parts = clean.split("/").filter(Boolean);
  return parts.length > 1 ? parts.slice(1).join("/") : clean;
}

/** The note's tags and properties as a strip under the path, as Obsidian shows them above the body. */
function NoteMetadata({ note, onTag }: { note: KnowledgeNote; onTag: (tag: string) => void }) {
  const properties = Object.entries(note.properties ?? {}).filter(([name]) => name !== "tags" && name !== "tag");
  if ((note.tags ?? []).length === 0 && properties.length === 0) return null;
  return (
    <div className="knowledge__metadata">
      {(note.tags ?? []).map((tag) => (
        <button
          type="button"
          className="knowledge__tag"
          key={tag}
          title="Show notes with this tag"
          onClick={() => {
            onTag(tag);
          }}
        >
          #{tag}
        </button>
      ))}
      {properties.map(([name, value]) => (
        <span className="knowledge__property" key={name}>
          <strong>{name}</strong> {value}
        </span>
      ))}
    </div>
  );
}

/** Outgoing links, linked mentions and unresolved names, beneath the note as Obsidian's backlinks pane. */
function NoteLinks({
  note,
  open,
  onToggle,
  onOpen,
}: {
  note: KnowledgeNote;
  open: boolean;
  onToggle: () => void;
  onOpen: (path: string) => void;
}) {
  const links = note.links ?? [];
  const backlinks = note.backlinks ?? [];
  const unresolved = note.unresolved_links ?? [];
  const total = links.length + backlinks.length + unresolved.length;
  return (
    <section className={`knowledge__links${open ? "" : " knowledge__links--closed"}`} aria-label="Links">
      <button type="button" className="knowledge__links-toggle" aria-expanded={open} onClick={onToggle}>
        <span className={`tree__chevron${open ? " tree__chevron--open" : ""}`} aria-hidden="true" />
        Links
        <span className="knowledge__links-count">
          {backlinks.length} linked mention{backlinks.length === 1 ? "" : "s"} · {links.length} outgoing
          {unresolved.length > 0 && ` · ${String(unresolved.length)} unresolved`}
        </span>
      </button>
      {open && (
        <div className="knowledge__links-body">
          {total === 0 && <p className="knowledge__links-empty">Nothing links here yet, and this note links nowhere.</p>}
          {backlinks.length > 0 && (
            <div className="knowledge__links-group">
              <h4>Linked mentions</h4>
              <div className="knowledge__links-list">
                {backlinks.map((path) => (
                  <button
                    type="button"
                    className="knowledge__relation"
                    key={`from:${path}`}
                    onClick={() => {
                      onOpen(path);
                    }}
                  >
                    {"←"} <span className="sr-only">Backlink from </span>
                    {path}
                  </button>
                ))}
              </div>
            </div>
          )}
          {links.length > 0 && (
            <div className="knowledge__links-group">
              <h4>Outgoing links</h4>
              <div className="knowledge__links-list">
                {links.map((path) => (
                  <button
                    type="button"
                    className="knowledge__relation"
                    key={`to:${path}`}
                    onClick={() => {
                      onOpen(path);
                    }}
                  >
                    {"→"} {path}
                  </button>
                ))}
              </div>
            </div>
          )}
          {unresolved.length > 0 && (
            <div className="knowledge__links-group">
              <h4>Unresolved</h4>
              <div className="knowledge__links-list">
                {unresolved.map((target) => (
                  <span
                    className="knowledge__relation knowledge__relation--unresolved"
                    key={`missing:${target}`}
                    title="No note has this name yet"
                  >
                    ? {target}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

interface NoteGraphData extends Record<string, unknown> {
  label: string;
  degree: number;
  focus: boolean;
}

function KnowledgeGraphView({
  graph,
  scope,
  focus,
  onScope,
  onOpen,
}: {
  graph: KnowledgeGraph;
  scope: GraphScope;
  focus: string | null;
  onScope: (scope: GraphScope) => void;
  onOpen: (path: string) => void;
}) {
  const { nodes, edges } = useMemo(() => graphElements(graph, scope, focus), [graph, scope, focus]);
  return (
    <div className="knowledge__graph-wrap">
      <div className="knowledge__graph-bar">
        <div className="knowledge__modes" role="group" aria-label="Graph scope">
          <button
            type="button"
            aria-pressed={scope === "vault"}
            onClick={() => {
              onScope("vault");
            }}
          >
            Whole vault
          </button>
          <button
            type="button"
            aria-pressed={scope === "local"}
            disabled={focus === null}
            title={focus === null ? "Open a note first" : `Notes within one link of ${focus}`}
            onClick={() => {
              onScope("local");
            }}
          >
            Around this note
          </button>
        </div>
        <span className="knowledge__graph-hint">
          {graph.nodes.length} notes · {graph.edges.length} links · click a note to open it
        </span>
      </div>
      {nodes.length === 0 ? (
        <div className="knowledge__welcome">
          <p>{scope === "local" ? "This note links nowhere and nothing links to it." : "No linked notes yet."}</p>
        </div>
      ) : (
        <div className="knowledge__graph" aria-label="Knowledge graph">
          <ReactFlow
            key={`${scope}:${focus ?? ""}`}
            nodes={nodes}
            edges={edges}
            nodeTypes={graphNodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
            defaultEdgeOptions={{ type: "straight" }}
            minZoom={0.15}
            maxZoom={2}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            onNodeClick={(_event, node) => {
              onOpen(node.id);
            }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      )}
    </div>
  );
}

function NoteBubble({ data }: { data: NoteGraphData }) {
  const size = data.degree >= 8 ? "large" : data.degree >= 3 ? "medium" : "small";
  return (
    <div className={`note-bubble note-bubble--${size}${data.focus ? " note-bubble--focus" : ""}`} title={data.label}>
      {/* Without handles React Flow draws no edge touching this node; they are hidden by the stylesheet. */}
      <Handle type="target" position={Position.Top} className="note-bubble__port" />
      <Handle type="source" position={Position.Bottom} className="note-bubble__port" />
      <span className="note-bubble__dot" aria-hidden="true" />
      <span className="note-bubble__label">{data.label}</span>
    </div>
  );
}

const graphNodeTypes = { note: NoteBubble };

function graphElements(
  graph: KnowledgeGraph,
  scope: GraphScope,
  focus: string | null,
): { nodes: Node<NoteGraphData>[]; edges: Edge[] } {
  let keep = new Set(graph.nodes.map((node) => node.path));
  if (scope === "local" && focus !== null) {
    keep = new Set([focus]);
    for (const edge of graph.edges) {
      if (edge.source === focus) keep.add(edge.target);
      if (edge.target === focus) keep.add(edge.source);
    }
  }
  const nodesKept = graph.nodes.filter((node) => keep.has(node.path));
  const edgesKept = graph.edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target));
  const degree = new Map<string, number>();
  for (const edge of edgesKept) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  const placed = forceLayout(
    nodesKept.map((node) => node.path),
    edgesKept.map((edge) => [edge.source, edge.target] as const),
  );
  const nodes: Node<NoteGraphData>[] = nodesKept.map((node) => ({
    id: node.path,
    type: "note",
    position: placed.get(node.path) ?? { x: 0, y: 0 },
    data: { label: node.title, degree: degree.get(node.path) ?? 0, focus: node.path === focus },
  }));
  const edges: Edge[] = edgesKept.map((edge, position) => ({
    id: `${edge.source}:${edge.target}:${String(position)}`,
    source: edge.source,
    target: edge.target,
    className: "knowledge__graph-edge",
  }));
  return { nodes, edges };
}

function asMessage(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}
