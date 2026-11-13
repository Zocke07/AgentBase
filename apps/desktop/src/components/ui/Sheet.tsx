import { useEffect, useEffectEvent, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { usePresence } from "../../state/usePresence";
import { Icon } from "../icons/Icon";

import { focusableIn, isTopLayer, useLayer } from "./layers";

/**
 * A modal dialog (Phase 20, brief 6.6): the window behind it is dimmed, Tab
 * stays inside it, and focus returns to where it was when the sheet closes.
 * Escape, the close button and a press on the dimmed area close it, unless
 * it is `blocking`: a sheet holding a change that would be lost stays until
 * the person chooses.
 */

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  /** Shown as the sheet's heading, and its name for a screen reader. */
  title?: string | undefined;
  /** The name when there is no visible title. */
  label?: string | undefined;
  size?: "small" | "medium" | "large" | undefined;
  /** `top` sits near the window's top edge, as a palette does. */
  placement?: "centre" | "top" | undefined;
  /** Escape and a press outside do nothing, and there is no close button. */
  blocking?: boolean | undefined;
  /** Actions, in a row at the sheet's foot. */
  footer?: ReactNode;
  className?: string | undefined;
  testId?: string | undefined;
  children: ReactNode;
}

export function Sheet({
  open,
  onClose,
  title,
  label,
  size = "medium",
  placement = "centre",
  blocking = false,
  footer,
  className,
  testId,
  children,
}: SheetProps) {
  const presence = usePresence(open, 200);
  const panel = useRef<HTMLDivElement>(null);
  const returnTo = useRef<Element | null>(null);
  const close = useEffectEvent(() => {
    onClose();
  });
  // What had focus when it opened is where it was opened from: if that goes
  // out of sight (its section is hidden), the sheet goes with it.
  const layer = useLayer(
    open,
    () => returnTo.current,
    () => {
      onClose();
    },
  );

  // Focus moves in when the sheet opens and back out when it closes.
  useLayoutEffect(() => {
    if (!open) return undefined;
    returnTo.current = document.activeElement;
    const element = panel.current;
    if (element !== null && !element.contains(document.activeElement)) {
      const first = element.querySelector<HTMLElement>("[data-autofocus]") ?? focusableIn(element)[0] ?? element;
      first.focus();
    }
    return () => {
      const previous = returnTo.current;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open || blocking) return undefined;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && isTopLayer(layer)) close();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open, blocking, layer]);

  if (!presence.mounted) return null;

  // Tab cycles within the sheet: the window behind it is not reachable.
  const trap = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || panel.current === null) return;
    const stops = focusableIn(panel.current);
    const first = stops[0];
    const last = stops.at(-1);
    if (first === undefined || last === undefined) {
      event.preventDefault();
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === panel.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const classes = [
    "sheet",
    `sheet--${size}`,
    placement === "top" ? "sheet--top" : "",
    presence.closing ? "sheet--closing" : "",
  ]
    .filter((part) => part !== "")
    .join(" ");

  return createPortal(
    <div
      className={classes}
      role="presentation"
      onMouseDown={(event) => {
        if (!blocking && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className={`sheet__panel${className === undefined ? "" : ` ${className}`}`}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? label}
        tabIndex={-1}
        data-testid={testId}
        onKeyDown={trap}
      >
        {title !== undefined && (
          <header className="sheet__head">
            <h2 className="sheet__title">{title}</h2>
            {!blocking && (
              <button type="button" className="icon-button" aria-label="Close" title="Close (Esc)" onClick={onClose}>
                <Icon name="x" size={16} />
              </button>
            )}
          </header>
        )}
        <div className="sheet__body">{children}</div>
        {footer !== undefined && <footer className="sheet__foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
