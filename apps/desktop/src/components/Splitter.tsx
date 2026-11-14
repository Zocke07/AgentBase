import { useRef, type KeyboardEvent, type PointerEvent } from "react";

/**
 * Panel-edge drag handle with parent-owned `useStoredSize` state, usable for
 * rows or columns. Double-click, Home, and Escape restore CSS size; arrows
 * move by step.
 */

export interface SplitterProps {
  /** "x" drags a width, "y" a height. */
  axis: "x" | "y";
  /** Chosen pixel size, or null for CSS default. */
  value: number | null;
  /** Current displayed size for default-originating drag or keyboard input. */
  measure: () => number;
  min: number;
  /** Dynamic maximum panel size. */
  max: () => number;
  onChange: (value: number | null) => void;
  /** What the handle resizes, for assistive technology. */
  label: string;
  /** Handle side; size grows toward it. */
  side: "end" | "start";
  /**
   * The stylesheet's size, announced while the viewer has chosen none. With
   * it the handle's markup never depends on a measurement, so a tree drawn
   * once and one drawn again agree; without it the handle measures.
   */
  fallback?: number | undefined;
}

const STEP = 24;

export function Splitter({ axis, value, measure, min, max, onChange, label, side, fallback }: SplitterProps) {
  const drag = useRef<{ from: number; size: number } | null>(null);
  const clamp = (size: number) => Math.min(max(), Math.max(min, Math.round(size)));
  // Start-edge handles grow in reverse direction.
  const sign = side === "end" ? 1 : -1;
  const at = (event: PointerEvent<HTMLDivElement>) => (axis === "x" ? event.clientX : event.clientY);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const grow = axis === "x" ? "ArrowRight" : "ArrowDown";
    const shrink = axis === "x" ? "ArrowLeft" : "ArrowUp";
    if (event.key === grow || event.key === shrink) {
      event.preventDefault();
      const direction = (event.key === grow ? 1 : -1) * sign;
      onChange(clamp((value ?? measure()) + direction * STEP));
    } else if (event.key === "Home" || event.key === "Escape") {
      event.preventDefault();
      onChange(null);
    }
  };

  return (
    <div
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-label={label}
      aria-valuenow={value ?? fallback ?? measure()}
      tabIndex={0}
      className={`splitter splitter--${axis} splitter--${side}`}
      title="Drag to resize. Double-click to reset."
      onPointerDown={(event) => {
        event.preventDefault();
        // Capture retains drag beyond handle; jsdom lacks it.
        if (typeof event.currentTarget.setPointerCapture === "function") {
          event.currentTarget.setPointerCapture(event.pointerId);
        }
        drag.current = { from: at(event), size: value ?? measure() };
      }}
      onPointerMove={(event) => {
        if (drag.current === null) return;
        onChange(clamp(drag.current.size + sign * (at(event) - drag.current.from)));
      }}
      onPointerUp={(event) => {
        drag.current = null;
        if (typeof event.currentTarget.releasePointerCapture === "function") {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
      onDoubleClick={() => {
        onChange(null);
      }}
      onKeyDown={onKeyDown}
    />
  );
}
