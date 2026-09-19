import { useRef, type KeyboardEvent, type PointerEvent } from "react";

/**
 * A drag handle on the edge of a panel. It owns no size of its own: the
 * parent keeps the size (see `useStoredSize`) and applies it, so the handle
 * is the same whether it sits on a column or a row. Double-click, Home or
 * Escape hands the size back to the stylesheet; the arrow keys move it a
 * step at a time.
 */

export interface SplitterProps {
  /** "x" drags a width, "y" a height. */
  axis: "x" | "y";
  /** The chosen size in pixels, or null while the stylesheet's default applies. */
  value: number | null;
  /** The size on screen right now, for a drag or a keystroke that starts from the default. */
  measure: () => number;
  min: number;
  /** The most the panel may take, read at the moment it is needed. */
  max: () => number;
  onChange: (value: number | null) => void;
  /** What the handle resizes, for assistive technology. */
  label: string;
  /** Which side of the panel the handle sits on: the size grows toward it. */
  side: "end" | "start";
}

const STEP = 24;

export function Splitter({ axis, value, measure, min, max, onChange, label, side }: SplitterProps) {
  const drag = useRef<{ from: number; size: number } | null>(null);
  const clamp = (size: number) => Math.min(max(), Math.max(min, Math.round(size)));
  // A handle at the start of a panel grows it by moving the other way.
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
      aria-valuenow={value ?? measure()}
      tabIndex={0}
      className={`splitter splitter--${axis} splitter--${side}`}
      title="Drag to resize. Double-click to reset."
      onPointerDown={(event) => {
        event.preventDefault();
        // Capture keeps the drag when the pointer outruns the handle; jsdom has no such thing.
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
