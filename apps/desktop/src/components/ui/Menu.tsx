import { useId, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";

import type { Align, Side } from "../../lib/anchor";
import { Icon, type IconName } from "../icons/Icon";

import { Popover } from "./Popover";

/**
 * A menu of actions, built on `Popover` (Phase 20, brief 6.6). One row has
 * focus at a time and the arrow keys move it; typing a few letters jumps to
 * the row that starts with them; Enter or Space chooses; Tab and Escape
 * close. A disabled row still takes focus, so a screen reader announces it
 * as unavailable instead of skipping it in silence.
 */

export interface MenuAction {
  readonly id: string;
  readonly label: string;
  readonly icon?: IconName | undefined;
  /** Shown at the row's end, already in the platform's glyphs. */
  readonly shortcut?: string | undefined;
  readonly disabled?: boolean | undefined;
  /** A destructive action, in the colour that says so. */
  readonly danger?: boolean | undefined;
  /** Present on a row that is one of a set of choices: it gets a tick. */
  readonly checked?: boolean | undefined;
  readonly onSelect: () => void;
}

export interface MenuSeparator {
  readonly id: string;
  readonly separator: true;
}

export type MenuItem = MenuAction | MenuSeparator;

const isAction = (item: MenuItem): item is MenuAction => !("separator" in item);

export interface MenuProps {
  open: boolean;
  /** Called when the menu should close, a chosen row included. */
  onClose: () => void;
  anchor: RefObject<HTMLElement | null>;
  /** Where focus returns on closing, when the anchor takes none (a context menu's point). */
  returnFocus?: RefObject<HTMLElement | null> | undefined;
  label: string;
  items: readonly MenuItem[];
  side?: Side | undefined;
  align?: Align | undefined;
  id?: string | undefined;
  testId?: string | undefined;
}

/** How long typed letters stay together as one search. */
const TYPE_AHEAD_MS = 500;

export function Menu({ open, onClose, anchor, returnFocus, label, items, side, align, id, testId }: MenuProps) {
  const list = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: "", at: 0 });

  const rows = (): HTMLElement[] => [...(list.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];

  const focusRow = (index: number) => {
    const all = rows();
    if (all.length === 0) return;
    all[(index + all.length) % all.length]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = rows();
    const current = all.findIndex((row) => row === document.activeElement);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusRow(current + 1);
        return;
      case "ArrowUp":
        event.preventDefault();
        focusRow(current < 0 ? all.length - 1 : current - 1);
        return;
      case "Home":
        event.preventDefault();
        focusRow(0);
        return;
      case "End":
        event.preventDefault();
        focusRow(all.length - 1);
        return;
      case "Tab":
        // A menu is one stop: Tab closes it and focus goes back to its
        // button, from where the next Tab carries on.
        event.preventDefault();
        onClose();
        return;
      default:
    }
    if (event.key.length !== 1 || event.key === " " || event.ctrlKey || event.metaKey || event.altKey) return;
    // Type-ahead: letters typed close together are one search.
    const now = event.timeStamp;
    const text = (now - typed.current.at > TYPE_AHEAD_MS ? "" : typed.current.text) + event.key.toLocaleLowerCase();
    typed.current = { text, at: now };
    const starts = (row: HTMLElement) => (row.dataset.label ?? "").toLocaleLowerCase().startsWith(text);
    // One letter moves on from the current row; more refine from it.
    const from = text.length === 1 ? current + 1 : Math.max(current, 0);
    const order = [...all.slice(from), ...all.slice(0, from)];
    order.find(starts)?.focus();
  };

  return (
    <Popover
      open={open}
      onClose={onClose}
      anchor={anchor}
      returnFocus={returnFocus}
      side={side}
      align={align}
      role="menu"
      label={label}
      id={id}
      testId={testId}
      className="popover--menu"
      // The ticked row when there is one, else the first.
      focus={(panel) =>
        panel.querySelector<HTMLElement>('[aria-checked="true"]') ?? panel.querySelector<HTMLElement>('[role^="menuitem"]')
      }
    >
      {/* The rows are the menu's children for a screen reader: this wrapper
          only holds the keyboard. */}
      <div ref={list} className="menu" role="presentation" onKeyDown={onKeyDown}>
        <MenuRows items={items} onClose={onClose} />
      </div>
    </Popover>
  );
}

/** A menu's rows. Apart from `Menu`, only the workbench draws them, at rest. */
export function MenuRows({ items, onClose }: { items: readonly MenuItem[]; onClose: () => void }) {
  // A set of choices keeps a column for the tick on every row.
  const hasChoices = items.some((item) => isAction(item) && item.checked !== undefined);
  return items.map((item) => {
    if (!isAction(item)) return <div key={item.id} className="menu__separator" role="separator" />;
    const choice = item.checked !== undefined;
    return (
      <button
        key={item.id}
        type="button"
        className={`menu__item${item.danger === true ? " menu__item--danger" : ""}`}
        role={choice ? "menuitemradio" : "menuitem"}
        aria-checked={choice ? item.checked : undefined}
        aria-disabled={item.disabled === true ? true : undefined}
        tabIndex={-1}
        data-label={item.label}
        onPointerMove={(event) => {
          // The pointer and the keyboard share one highlight: focus.
          if (document.activeElement !== event.currentTarget) event.currentTarget.focus();
        }}
        onClick={() => {
          if (item.disabled === true) return;
          onClose();
          item.onSelect();
        }}
      >
        {hasChoices && <span className="menu__mark">{item.checked === true && <Icon name="check" size={16} />}</span>}
        {item.icon !== undefined && <Icon name={item.icon} size={16} />}
        <span className="menu__label">{item.label}</span>
        {item.shortcut !== undefined && <span className="menu__shortcut">{item.shortcut}</span>}
      </button>
    );
  });
}

export interface MenuButtonProps {
  /** Names the menu, and the button when it shows no text of its own. */
  label: string;
  items: readonly MenuItem[];
  className?: string | undefined;
  title?: string | undefined;
  disabled?: boolean | undefined;
  side?: Side | undefined;
  align?: Align | undefined;
  testId?: string | undefined;
  /** The button's content. Without it the label is the button's text. */
  children?: ReactNode;
}

/** A button that opens a menu under itself. */
export function MenuButton({
  label,
  items,
  className = "button",
  title,
  disabled,
  side,
  align,
  testId,
  children,
}: MenuButtonProps) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  return (
    <>
      <button
        ref={button}
        type="button"
        className={className}
        title={title}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={children === undefined ? undefined : label}
        data-testid={testId}
        onClick={() => {
          setOpen((was) => !was);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {children ?? label}
      </button>
      <Menu
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        anchor={button}
        label={label}
        items={items}
        side={side}
        align={align}
        id={menuId}
      />
    </>
  );
}
