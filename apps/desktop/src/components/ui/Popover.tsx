import {
  useCallback,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { placePanel, type Align, type Placed, type Side } from "../../lib/anchor";
import { usePresence } from "../../state/usePresence";

import { focusableIn, isTopLayer, useLayer } from "./layers";

/**
 * A panel anchored to the control that opened it (Phase 20, brief 6.6): it
 * opens on one side of the anchor, flips at the window's edges, takes focus
 * when it opens and gives it back when it closes, and closes on Escape or a
 * press outside. Menus and the header's popovers are built on it.
 *
 * It renders into `document.body`, so no scrolling or clipped ancestor can
 * cut it off, and it is placed with `position: fixed` from the anchor's box.
 * The owner holds `open`; the popover only reports that it should close.
 */

/** Escape, a press outside, Tab leaving the panel, or its anchor going out of sight. */
export type PopoverCloseReason = "escape" | "outside" | "tab";

export interface PopoverProps {
  open: boolean;
  onClose: (reason: PopoverCloseReason) => void;
  /** The control the panel belongs to. A press on it is not "outside". */
  anchor: RefObject<HTMLElement | null>;
  /** Where focus returns on closing, when the anchor itself takes none. */
  returnFocus?: RefObject<HTMLElement | null> | undefined;
  side?: Side | undefined;
  align?: Align | undefined;
  role?: "dialog" | "menu" | "listbox" | "group" | undefined;
  label?: string | undefined;
  labelledBy?: string | undefined;
  id?: string | undefined;
  className?: string | undefined;
  testId?: string | undefined;
  /**
   * Where focus goes once the panel is placed: the panel itself, its first
   * focusable element, or whatever the function picks (a menu's first row).
   */
  focus?: "panel" | "first" | ((panel: HTMLElement) => HTMLElement | null) | undefined;
  /** How long the closing animation runs before the panel is removed. */
  exitMs?: number | undefined;
  children: ReactNode;
}

const samePlace = (left: Placed | null, right: Placed): boolean =>
  left !== null &&
  left.top === right.top &&
  left.left === right.left &&
  left.side === right.side &&
  left.maxHeight === right.maxHeight;

export function Popover(props: PopoverProps) {
  const { open, anchor, returnFocus, exitMs = 120 } = props;
  const presence = usePresence(open, exitMs);
  /** The panel was removed while it held focus, which the page then lost. */
  const heldFocusRef = useRef(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Closed with focus still inside (a row was chosen): give it back to the
  // anchor rather than let it fall to the page.
  const focusBackRef = returnFocus ?? anchor;
  useLayoutEffect(() => {
    if (!open && (heldFocusRef.current || panelRef.current?.contains(document.activeElement) === true)) {
      focusBackRef.current?.focus();
    }
    heldFocusRef.current = false;
  }, [open, focusBackRef]);

  if (!presence.mounted) return null;
  return (
    <PopoverPanel {...props} closing={presence.closing} panelRef={panelRef} heldFocusRef={heldFocusRef} focusBackRef={focusBackRef} />
  );
}

interface PanelProps extends PopoverProps {
  closing: boolean;
  panelRef: RefObject<HTMLDivElement | null>;
  heldFocusRef: RefObject<boolean>;
  focusBackRef: RefObject<HTMLElement | null>;
}

/** Mounted only while the panel is on screen, so each opening starts unplaced. */
function PopoverPanel({
  open,
  onClose,
  anchor,
  side = "bottom",
  align = "start",
  role,
  label,
  labelledBy,
  id,
  className,
  testId,
  focus = "panel",
  children,
  closing,
  panelRef,
  heldFocusRef,
  focusBackRef,
  returnFocus,
}: PanelProps) {
  const close = useEffectEvent((reason: PopoverCloseReason) => {
    onClose(reason);
  });
  // Where the panel came from, for closing it when that is hidden: the
  // element focus returns to when there is one (a context menu's anchor is
  // a point in the body, its thing is in a section).
  const layer = useLayer(
    open,
    () => returnFocus?.current ?? anchor.current,
    () => {
      onClose("outside");
    },
  );
  const [placed, setPlaced] = useState<Placed | null>(null);

  const attach = useCallback(
    (node: HTMLDivElement) => {
      panelRef.current = node;
      return () => {
        // Runs before the node leaves the document, so focus is still in it.
        if (node.contains(document.activeElement)) heldFocusRef.current = true;
        panelRef.current = null;
      };
    },
    [panelRef, heldFocusRef],
  );

  const place = useEffectEvent(() => {
    const target = anchor.current;
    const element = panelRef.current;
    if (target === null || element === null) return;
    const box = target.getBoundingClientRect();
    const next = placePanel(
      { top: box.top, left: box.left, width: box.width, height: box.height },
      { width: element.offsetWidth, height: element.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
      { side, align },
    );
    setPlaced((current) => (samePlace(current, next) ? current : next));
  });

  // The observer reports the panel's size as soon as it is watched, before
  // the first paint, and again whenever its content changes it.
  useLayoutEffect(() => {
    const element = panelRef.current;
    if (element === null) return undefined;
    const observer = new ResizeObserver(() => {
      place();
    });
    observer.observe(element);
    // A scroll can fire many times a frame, and each placing reads layout.
    let frame = 0;
    const onMove = (event: Event) => {
      // The panel's own content scrolling moves nothing it is placed by.
      if (event.target instanceof Node && element.contains(event.target)) return;
      if (frame !== 0) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        place();
      });
    };
    window.addEventListener("resize", onMove);
    // Capture: a scroll inside any ancestor moves the anchor too.
    window.addEventListener("scroll", onMove, true);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [panelRef]);

  // Focus moves in once the panel is placed: a hidden element takes none.
  const isPlaced = placed !== null;
  const moveFocusIn = useEffectEvent((element: HTMLElement) => {
    const target = typeof focus === "function" ? focus(element) : focus === "first" ? (focusableIn(element)[0] ?? null) : null;
    (target ?? element).focus();
    // A target that cannot take focus (it sits in a closed group, say) must
    // not leave the keyboard outside a panel it cannot Tab into.
    if (!element.contains(document.activeElement)) element.focus();
  });
  useLayoutEffect(() => {
    if (!open || !isPlaced) return;
    const element = panelRef.current;
    if (element !== null && !element.contains(document.activeElement)) moveFocusIn(element);
  }, [open, isPlaced, panelRef]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (!isTopLayer(layer)) return;
      if (event.key === "Escape") {
        close("escape");
        focusBackRef.current?.focus();
        return;
      }
      // The panel is at the end of the document, not after its anchor, so
      // Tab past either end would wander off. Leaving it that way closes it
      // and puts focus back on the anchor, from where Tab carries on.
      const element = panelRef.current;
      // A menu handles Tab itself, and says so by preventing the default.
      if (event.key !== "Tab" || event.defaultPrevented) return;
      if (!element?.contains(document.activeElement)) return;
      const stops = focusableIn(element);
      const edge = event.shiftKey ? stops[0] : stops.at(-1);
      if (edge === undefined || document.activeElement === edge || (event.shiftKey && document.activeElement === element)) {
        event.preventDefault();
        close("tab");
        focusBackRef.current?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (!isTopLayer(layer) || !(event.target instanceof Node)) return;
      if (panelRef.current?.contains(event.target) === true || anchor.current?.contains(event.target) === true) return;
      close("outside");
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, layer, anchor, focusBackRef, panelRef]);

  const classes = ["popover", closing ? "popover--closing" : "", className ?? ""].filter((part) => part !== "").join(" ");

  return createPortal(
    <div
      ref={attach}
      id={id}
      className={classes}
      role={role}
      aria-label={label}
      aria-labelledby={labelledBy}
      tabIndex={-1}
      data-side={placed?.side ?? side}
      data-testid={testId}
      style={
        placed === null
          ? { top: 0, left: 0, visibility: "hidden" }
          : { top: placed.top, left: placed.left, maxHeight: placed.maxHeight }
      }
    >
      {children}
    </div>,
    document.body,
  );
}
