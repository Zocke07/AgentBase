import type { NoteSummary } from "@agentspace/schemas";
import { useEffect, useRef, useState } from "react";

import { fuzzyFilter } from "../lib/fuzzy";

/**
 * Obsidian's quick switcher: type part of a title or path, arrow to a match,
 * Enter opens it. A query that names no existing note offers to create one,
 * which is how a vault grows in Obsidian too.
 */

export interface QuickSwitcherProps {
  notes: readonly NoteSummary[];
  onOpen: (path: string) => void;
  onCreate: (path: string) => void;
  onClose: () => void;
}

const LIMIT = 12;

export function QuickSwitcher({ notes, onOpen, onCreate, onClose }: QuickSwitcherProps) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, []);

  const matches = fuzzyFilter(query.trim(), notes, (note) => `${note.title} ${note.path}`).slice(0, LIMIT);
  const trimmed = query.trim();
  const exact = notes.some(
    (note) =>
      note.title.toLocaleLowerCase() === trimmed.toLocaleLowerCase() ||
      note.path.replace(/\.md$/i, "").toLocaleLowerCase() === trimmed.replace(/\.md$/i, "").toLocaleLowerCase(),
  );
  const creatable = trimmed !== "" && !exact;
  const createPath = `${trimmed.replace(/\.md$/i, "").replace(/^\/+/, "")}.md`;
  const rows = matches.length + (creatable ? 1 : 0);
  const selected = Math.min(cursor, Math.max(rows - 1, 0));

  const choose = (index: number) => {
    const match = matches[index];
    if (match !== undefined) {
      onOpen(match.item.path);
      return;
    }
    if (creatable) onCreate(createPath);
  };

  return (
    <div
      className="palette"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette__panel" role="dialog" aria-label="Open a note">
        <input
          ref={input}
          className="palette__input"
          aria-label="Find a note by title or path"
          placeholder="Type a note name; Enter opens it, Esc closes"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
            } else if (event.key === "ArrowDown") {
              event.preventDefault();
              setCursor((current) => Math.min(current + 1, Math.max(rows - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setCursor((current) => Math.max(current - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(selected);
            }
          }}
        />
        <ol className="palette__list" aria-label="Matching notes">
          {matches.map((match, index) => (
            <li key={match.item.path}>
              <button
                type="button"
                className={`palette__row${index === selected ? " palette__row--selected" : ""}`}
                onMouseEnter={() => {
                  setCursor(index);
                }}
                onClick={() => {
                  choose(index);
                }}
              >
                <span className="palette__title">
                  {match.item.pinned === true && <span className="tree__pin">{"★"} </span>}
                  {match.item.title}
                </span>
                <span className="palette__path">{match.item.path}</span>
              </button>
            </li>
          ))}
          {creatable && (
            <li>
              <button
                type="button"
                className={`palette__row palette__row--create${matches.length === selected ? " palette__row--selected" : ""}`}
                onMouseEnter={() => {
                  setCursor(matches.length);
                }}
                onClick={() => {
                  choose(matches.length);
                }}
              >
                <span className="palette__title">Create {createPath}</span>
                <span className="palette__path">a new note with this name</span>
              </button>
            </li>
          )}
          {rows === 0 && <li className="palette__empty">No notes yet. Type a name to create one.</li>}
        </ol>
      </div>
    </div>
  );
}
