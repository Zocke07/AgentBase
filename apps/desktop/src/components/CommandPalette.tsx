import { useId, useMemo, useState } from "react";

import { rankCommands, type PaletteCommand } from "../lib/palette";
import { currentPlatform } from "../lib/platform";
import { shortcut, shortcutLabel } from "../lib/shortcuts";

import { Sheet } from "./ui/Sheet";

/**
 * The command palette (Phase 20, brief 6.4), opened by Ctrl/Cmd+K or the
 * toolbar's search button: one field that finds sections, actions, spaces,
 * runs, agents and notes. Arrow keys move through the rows, Enter acts and
 * Escape closes it, giving focus back to where it was.
 *
 * It is a combobox over a listbox: focus stays in the field while the
 * arrows move the highlighted row, which the field names as its active
 * descendant, so a screen reader hears each row as it is reached.
 */

export interface CommandPaletteProps {
  open: boolean;
  commands: readonly PaletteCommand[];
  onClose: () => void;
  /** A line under the list: what is still being read, or could not be. */
  status?: string | undefined;
}

export function CommandPalette({ open, commands, onClose, status }: CommandPaletteProps) {
  return (
    <Sheet open={open} onClose={onClose} label="Find anything" placement="top" className="palette__panel" testId="palette">
      {/* Mounted afresh on each opening, so the field starts empty. */}
      {open && <PaletteBody commands={commands} onClose={onClose} status={status} />}
    </Sheet>
  );
}

function PaletteBody({ commands, onClose, status }: Omit<CommandPaletteProps, "open">) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const id = useId();
  const platform = currentPlatform();
  const sections = useMemo(() => rankCommands(query, commands), [query, commands]);
  const rows = sections.flatMap((section) => section.commands);
  const selected = Math.min(cursor, Math.max(rows.length - 1, 0));
  const optionId = (index: number) => `${id}-option-${String(index)}`;

  const choose = (command: PaletteCommand | undefined) => {
    if (command === undefined) return;
    onClose();
    // After the sheet has closed and handed focus back, so an action that
    // moves focus (into Home's goal, say) keeps it.
    requestAnimationFrame(() => {
      command.run();
    });
  };

  // Each row's place in the whole list, which the arrow keys walk.
  const offsets = sections.map((_, at) => sections.slice(0, at).reduce((sum, section) => sum + section.commands.length, 0));
  return (
    <>
      <input
        className="palette__input"
        role="combobox"
        aria-label="Find a section, an action, a space, a run, an agent or a note"
        aria-expanded={rows.length > 0}
        aria-controls={`${id}-list`}
        aria-activedescendant={rows.length > 0 ? optionId(selected) : undefined}
        aria-autocomplete="list"
        placeholder="Find a section, an action, a run, an agent or a note"
        value={query}
        data-autofocus=""
        data-testid="palette-input"
        onChange={(event) => {
          setQuery(event.target.value);
          setCursor(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setCursor(rows.length === 0 ? 0 : (selected + 1) % rows.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setCursor(rows.length === 0 ? 0 : (selected - 1 + rows.length) % rows.length);
          } else if (event.key === "Enter") {
            event.preventDefault();
            choose(rows[selected]);
          }
        }}
      />
      <div className="palette__list" id={`${id}-list`} role="listbox" aria-label="Results">
        {sections.map((section, sectionAt) => (
          <div key={section.group} role="group" aria-labelledby={`${id}-${section.group}`} className="palette__group">
            <div className="palette__heading" id={`${id}-${section.group}`} role="presentation">
              {section.group}
            </div>
            {section.commands.map((command, row) => {
              const at = (offsets[sectionAt] ?? 0) + row;
              const keys = command.shortcut === undefined ? null : shortcutLabel(shortcut(command.shortcut).keys, platform);
              return (
                <div
                  key={command.id}
                  id={optionId(at)}
                  role="option"
                  aria-selected={at === selected}
                  className={`palette__row${at === selected ? " palette__row--selected" : ""}`}
                  data-testid={`palette-${command.id}`}
                  onMouseMove={() => {
                    if (at !== selected) setCursor(at);
                  }}
                  onClick={() => {
                    choose(command);
                  }}
                >
                  <span className="palette__text">
                    <span className="palette__title">{command.label}</span>
                    {command.detail !== undefined && command.detail !== "" && (
                      <span className="palette__detail">{command.detail}</span>
                    )}
                  </span>
                  {keys !== null && <kbd className="palette__keys">{keys}</kbd>}
                </div>
              );
            })}
          </div>
        ))}
        {rows.length === 0 && (
          <p className="palette__empty">
            {query.trim() === "" ? "Nothing to show yet." : `Nothing matches "${query.trim()}".`}
          </p>
        )}
      </div>
      {status !== undefined && (
        <p className="palette__loading" role="status">
          {status}
        </p>
      )}
    </>
  );
}
