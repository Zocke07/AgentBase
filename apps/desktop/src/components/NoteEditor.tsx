import type { NoteSummary } from "@agentspace/schemas";
import { useLayoutEffect, useRef, useState } from "react";

import { fuzzyFilter } from "../lib/fuzzy";
import { openWikilinkAt } from "../lib/markdown";

/**
 * The Markdown source, with the two things Obsidian's editor does that a bare
 * textarea does not: typing `[[` offers note names to complete the link, and
 * a small bar wraps the selection in the dialect's marks. The text itself is
 * the caller's; this only proposes edits to it.
 */

export interface NoteEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Every note in the vault, for link completion. */
  notes: readonly NoteSummary[];
}

const COMPLETIONS = 8;

interface Selection {
  start: number;
  end: number;
}

export function NoteEditor({ value, onChange, notes }: NoteEditorProps) {
  const area = useRef<HTMLTextAreaElement>(null);
  const pending = useRef<Selection | null>(null);
  const [completion, setCompletion] = useState<{ start: number; query: string; cursor: number } | null>(null);

  // A programmatic edit sets the caret once the new value has rendered.
  useLayoutEffect(() => {
    const wanted = pending.current;
    const element = area.current;
    if (wanted === null || element === null) return;
    pending.current = null;
    element.focus();
    element.setSelectionRange(wanted.start, wanted.end);
  }, [value]);

  const edit = (next: string, selection: Selection) => {
    pending.current = selection;
    onChange(next);
  };

  const refreshCompletion = () => {
    const element = area.current;
    if (element === null) return;
    const open = openWikilinkAt(value, element.selectionStart);
    setCompletion(open === null ? null : { start: open.start, query: open.query, cursor: 0 });
  };

  const matches =
    completion === null
      ? []
      : fuzzyFilter(completion.query, notes, (note) => `${note.title} ${note.path}`).slice(0, COMPLETIONS);

  const accept = (note: NoteSummary) => {
    if (completion === null) return;
    const target = note.path.replace(/\.md$/i, "");
    const before = value.slice(0, completion.start);
    const after = value.slice(completion.start + 2 + completion.query.length);
    const link = `[[${target}]]`;
    // Obsidian closes the link for you; if the closing brackets were already
    // typed, do not double them.
    const rest = after.startsWith("]]") ? after.slice(2) : after;
    const caret = before.length + link.length;
    setCompletion(null);
    edit(`${before}${link}${rest}`, { start: caret, end: caret });
  };

  const wrap = (before: string, after: string, placeholder: string) => {
    const element = area.current;
    if (element === null) return;
    const { selectionStart: start, selectionEnd: end } = element;
    const chosen = value.slice(start, end);
    const inner = chosen === "" ? placeholder : chosen;
    const next = `${value.slice(0, start)}${before}${inner}${after}${value.slice(end)}`;
    edit(next, { start: start + before.length, end: start + before.length + inner.length });
  };

  const prefixLines = (prefix: string) => {
    const element = area.current;
    if (element === null) return;
    const { selectionStart: start, selectionEnd: end } = element;
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    // A selection ending just after a newline stops at that newline.
    const anchor = end > start && value[end - 1] === "\n" ? end - 1 : end;
    const nextBreak = value.indexOf("\n", anchor);
    const lineEnd = nextBreak === -1 ? value.length : nextBreak;
    const block = value.slice(lineStart, lineEnd);
    const lines = block.split("\n");
    const allPrefixed = lines.every((line) => line.startsWith(prefix));
    const changed = lines.map((line) => (allPrefixed ? line.slice(prefix.length) : `${prefix}${line}`)).join("\n");
    const next = `${value.slice(0, lineStart)}${changed}${value.slice(lineEnd)}`;
    edit(next, { start: lineStart, end: lineStart + changed.length });
  };

  return (
    <div className="source">
      <div className="source__bar" role="toolbar" aria-label="Formatting">
        <button type="button" title="Bold" onClick={() => { wrap("**", "**", "bold"); }}>
          <b>B</b>
        </button>
        <button type="button" title="Italic" onClick={() => { wrap("*", "*", "italic"); }}>
          <i>I</i>
        </button>
        <button type="button" title="Highlight" onClick={() => { wrap("==", "==", "highlight"); }}>
          <mark>H</mark>
        </button>
        <button type="button" title="Strikethrough" onClick={() => { wrap("~~", "~~", "struck"); }}>
          <s>S</s>
        </button>
        <button type="button" title="Inline code" onClick={() => { wrap("`", "`", "code"); }}>
          <code>{"<>"}</code>
        </button>
        <span className="source__bar-gap" />
        <button type="button" title="Heading" onClick={() => { prefixLines("## "); }}>
          H2
        </button>
        <button type="button" title="Bullet list" onClick={() => { prefixLines("- "); }}>
          {"•"} list
        </button>
        <button type="button" title="Task" onClick={() => { prefixLines("- [ ] "); }}>
          {"☐"} task
        </button>
        <button type="button" title="Quote" onClick={() => { prefixLines("> "); }}>
          {"“"} quote
        </button>
        <button type="button" title="Callout" onClick={() => { prefixLines("> [!note] "); }}>
          {"✎"} callout
        </button>
        <span className="source__bar-gap" />
        <button type="button" title="Link to a note" onClick={() => { wrap("[[", "]]", "note"); }}>
          [[link]]
        </button>
        <button type="button" title="Tag" onClick={() => { wrap("#", "", "tag"); }}>
          #tag
        </button>
      </div>
      <div className="source__body">
        <textarea
          ref={area}
          className="knowledge__editor"
          aria-label="Markdown source"
          spellCheck="true"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            // The caret has moved with the keystroke by the time change fires.
            const open = openWikilinkAt(event.target.value, event.target.selectionStart);
            setCompletion(open === null ? null : { start: open.start, query: open.query, cursor: 0 });
          }}
          onClick={refreshCompletion}
          onKeyUp={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "Home" || event.key === "End") {
              refreshCompletion();
            }
          }}
          onBlur={() => {
            // Let a click on a completion land before the list goes away.
            window.setTimeout(() => {
              setCompletion(null);
            }, 150);
          }}
          onKeyDown={(event) => {
            if (completion === null || matches.length === 0) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setCompletion({ ...completion, cursor: Math.min(completion.cursor + 1, matches.length - 1) });
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setCompletion({ ...completion, cursor: Math.max(completion.cursor - 1, 0) });
            } else if (event.key === "Enter" || event.key === "Tab") {
              const chosen = matches[completion.cursor];
              if (chosen === undefined) return;
              event.preventDefault();
              accept(chosen.item);
            } else if (event.key === "Escape") {
              event.preventDefault();
              setCompletion(null);
            }
          }}
        />
        {completion !== null && matches.length > 0 && (
          <ol className="source__completions" aria-label="Link suggestions" data-testid="link-completions">
            {matches.map((match, index) => (
              <li key={match.item.path}>
                <button
                  type="button"
                  className={`source__completion${index === completion.cursor ? " source__completion--selected" : ""}`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    accept(match.item);
                  }}
                >
                  <span>{match.item.title}</span>
                  <small>{match.item.path}</small>
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
