import type { KeyboardEvent, ReactNode, RefObject } from "react";

import { Splitter } from "../Splitter";

import { IconButton } from "./controls";

/**
 * The inspector (Phase 20, brief 6.3): a pane at the right edge of a
 * section for the thing selected in it. A title row with a way to close
 * it, a handle on its left edge that resizes it (the owner keeps the width
 * with `useStoredSize`), and groups that fold.
 *
 * Where it sits when its section is too narrow to share is the owner's
 * stylesheet's business: the run's inspector covers its canvas below a
 * width of its own, because a full-screen room is wide in a small window.
 */

export interface InspectorProps {
  /** The pane's name, for a screen reader. */
  label: string;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  /** Says what closing closes, "Close the agent detail". */
  closeLabel: string;
  /** The viewer's width, or null for the stylesheet's. */
  width: number | null;
  onResize: (width: number | null) => void;
  /** The stylesheet's width in pixels, announced by the handle while `width` is null. */
  defaultWidth: number;
  minWidth: number;
  maxWidth: () => number;
  measure: () => number;
  resizeLabel: string;
  className?: string | undefined;
  testId?: string | undefined;
  panelRef?: RefObject<HTMLElement | null> | undefined;
  onKeyDown?: ((event: KeyboardEvent<HTMLElement>) => void) | undefined;
  children: ReactNode;
}

export function Inspector({
  label,
  title,
  subtitle,
  onClose,
  closeLabel,
  width,
  onResize,
  defaultWidth,
  minWidth,
  maxWidth,
  measure,
  resizeLabel,
  className,
  testId,
  panelRef,
  onKeyDown,
  children,
}: InspectorProps) {
  return (
    <aside
      ref={panelRef}
      className={`inspector${className === undefined ? "" : ` ${className}`}`}
      aria-label={label}
      data-testid={testId}
      tabIndex={-1}
      style={width === null ? undefined : { width: `${String(width)}px` }}
      onKeyDown={onKeyDown}
    >
      <Splitter
        axis="x"
        side="start"
        value={width}
        fallback={defaultWidth}
        measure={measure}
        min={minWidth}
        max={maxWidth}
        onChange={onResize}
        label={resizeLabel}
      />
      <header className="inspector__head">
        <div className="inspector__titles">
          <h3 className="inspector__title">{title}</h3>
          {subtitle !== undefined && <p className="inspector__subtitle">{subtitle}</p>}
        </div>
        <IconButton icon="x" label={closeLabel} title={`${closeLabel} (Esc)`} size={16} onClick={onClose} />
      </header>
      <div className="inspector__body">{children}</div>
    </aside>
  );
}

export interface InspectorGroupProps {
  title: string;
  /** Folded at first: what is long and seldom read, such as a prompt. */
  folded?: boolean | undefined;
  className?: string | undefined;
  testId?: string | undefined;
  children: ReactNode;
}

/** One group of an inspector, which folds under its title. */
export function InspectorGroup({ title, folded = false, className, testId, children }: InspectorGroupProps) {
  return (
    <details className={`inspector__group${className === undefined ? "" : ` ${className}`}`} open={!folded} data-testid={testId}>
      <summary className="inspector__group-title">{title}</summary>
      <div className="inspector__group-body">{children}</div>
    </details>
  );
}
