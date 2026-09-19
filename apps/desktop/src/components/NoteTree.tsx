import type { NoteSummary } from "@agentspace/schemas";
import { useState } from "react";

/**
 * The vault as folders, the way Obsidian's file explorer shows it. Folders
 * fold; the fold state is a fact about this window and lives here. Every
 * note is a button named by its title, so the same list works for a person
 * and for a screen reader.
 */

export interface NoteTreeProps {
  notes: readonly NoteSummary[];
  activePath: string | null;
  onOpen: (path: string) => void;
  /** Ask to delete a folder and everything in it; absent where folders cannot be deleted. */
  onDeleteFolder?: ((path: string, notes: number) => void) | undefined;
}

interface Folder {
  readonly name: string;
  readonly path: string;
  readonly folders: Folder[];
  readonly notes: NoteSummary[];
}

function buildTree(notes: readonly NoteSummary[]): Folder {
  const root: Folder = { name: "", path: "", folders: [], notes: [] };
  for (const note of notes) {
    const parts = note.path.split("/");
    let folder = root;
    for (const part of parts.slice(0, -1)) {
      let next = folder.folders.find((child) => child.name === part);
      if (next === undefined) {
        next = { name: part, path: folder.path === "" ? part : `${folder.path}/${part}`, folders: [], notes: [] };
        folder.folders.push(next);
      }
      folder = next;
    }
    folder.notes.push(note);
  }
  sortFolder(root);
  return root;
}

function sortFolder(folder: Folder): void {
  folder.folders.sort((left, right) => left.name.localeCompare(right.name));
  folder.notes.sort((left, right) => left.title.localeCompare(right.title) || left.path.localeCompare(right.path));
  for (const child of folder.folders) sortFolder(child);
}

function countNotes(folder: Folder): number {
  return folder.notes.length + folder.folders.reduce((total, child) => total + countNotes(child), 0);
}

export function NoteTree({ notes, activePath, onOpen, onDeleteFolder }: NoteTreeProps) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set());
  const tree = buildTree(notes);

  const toggle = (path: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderFolder = (folder: Folder, depth: number) => (
    <>
      {folder.folders.map((child) => {
        const open = !collapsed.has(child.path);
        return (
          <li key={`folder:${child.path}`} className="tree__item">
            <div className="tree__folder-row">
              <button
                type="button"
                className="tree__folder"
                style={{ paddingLeft: `${String(0.5 + depth * 0.85)}rem` }}
                aria-expanded={open}
                onClick={() => {
                  toggle(child.path);
                }}
              >
                <span className={`tree__chevron${open ? " tree__chevron--open" : ""}`} aria-hidden="true" />
                <span className="tree__name">{child.name}</span>
                <span className="tree__count">{countNotes(child)}</span>
              </button>
              {onDeleteFolder !== undefined && (
                <button
                  type="button"
                  className="tree__folder-delete"
                  aria-label={`Delete the folder ${child.path}`}
                  title={`Delete ${child.path}/ and everything in it`}
                  onClick={() => {
                    onDeleteFolder(child.path, countNotes(child));
                  }}
                >
                  {"✕"}
                </button>
              )}
            </div>
            {open && <ul className="tree__group">{renderFolder(child, depth + 1)}</ul>}
          </li>
        );
      })}
      {folder.notes.map((note) => (
        <li key={`note:${note.path}`} className="tree__item">
          <button
            type="button"
            className={`tree__note${note.path === activePath ? " tree__note--active" : ""}`}
            style={{ paddingLeft: `${String(0.5 + depth * 0.85 + 0.9)}rem` }}
            aria-current={note.path === activePath ? "true" : undefined}
            title={note.excerpt === "" ? note.path : `${note.path}\n${note.excerpt}`}
            onClick={() => {
              onOpen(note.path);
            }}
          >
            {note.pinned === true && (
              <span className="tree__pin" aria-label="Pinned">
                {"★"}
              </span>
            )}
            <span className="tree__name">{note.title}</span>
          </button>
        </li>
      ))}
    </>
  );

  return (
    <ul className="tree" aria-label="Notes">
      {renderFolder(tree, 0)}
    </ul>
  );
}
