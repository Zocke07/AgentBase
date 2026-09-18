import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { Section } from "../lib/sections";
import { TOUR_STEPS } from "../lib/tour";

/**
 * The first-run tour: a handful of steps that each point at a real part of
 * the window (the rail, the goal box, the keys) and say what it is for,
 * ending on the demo run so a new user sees a live canvas without a key.
 * It draws its own spotlight from the target's rectangle; there is no
 * dependency for this, and the sections it points into stay mounted behind
 * `hidden`, so a step first switches sections and then measures.
 *
 * Whether it shows is the sidecar's `onboarding_completed` setting, owned by
 * the shell; this component only says when it was finished or skipped.
 */

export interface TourProps {
  open: boolean;
  section: Section;
  onSection: (section: Section) => void;
  /** Finished, or skipped: either way it does not come back on its own. */
  onClose: () => void;
  /** Start the scripted demo run and open it; absent where the sidecar is not ready. */
  onDemo?: (() => Promise<void>) | undefined;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** Room around the spotlight, and the card's distance from it. */
const RING = 6;
const GAP = 12;
const CARD_WIDTH = 340;

function measure(target: string | null): Box | null {
  if (target === null) return null;
  const element = document.querySelector(`[data-tour="${target}"]`);
  if (!(element instanceof HTMLElement)) return null;
  if (element.closest("[hidden]") !== null) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return { top: rect.top - RING, left: rect.left - RING, width: rect.width + RING * 2, height: rect.height + RING * 2 };
}

/** Where the card goes: beside the spotlight when there is room, else beneath, always on screen. */
function place(box: Box | null, viewport: { width: number; height: number }): { top: number; left: number } | null {
  if (box === null) return null;
  const width = Math.min(CARD_WIDTH, viewport.width - 32);
  let left = box.left + box.width + GAP;
  let top = box.top;
  if (left + width > viewport.width - 16) {
    left = Math.max(16, Math.min(box.left, viewport.width - width - 16));
    top = box.top + box.height + GAP;
  }
  if (top > viewport.height - 200) top = Math.max(16, box.top - 200 - GAP);
  return { top, left };
}

export function Tour({ open, section, onSection, onClose, onDemo }: TourProps) {
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const step = TOUR_STEPS[index] ?? TOUR_STEPS[0];
  const last = index === TOUR_STEPS.length - 1;

  // Each step switches to its section first; the shell applies that on its
  // next render, so the measurement waits a frame for the target to show.
  useLayoutEffect(() => {
    if (!open || step === undefined) return undefined;
    if (step.section !== null && step.section !== section) onSection(step.section);
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        setBox(measure(step.target));
      });
    });
    const onResize = () => {
      setBox(measure(step.target));
    };
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
    };
  }, [open, step, section, onSection]);

  useEffect(() => {
    if (open) nextButton.current?.focus();
  }, [open, index]);

  const close = useCallback(() => {
    setIndex(0);
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "ArrowRight" && !last) {
        event.preventDefault();
        setIndex((current) => Math.min(current + 1, TOUR_STEPS.length - 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setIndex((current) => Math.max(current - 1, 0));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open, last, close]);

  if (!open || step === undefined) return null;

  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const position = place(box, viewport);

  const demo = async () => {
    if (onDemo === undefined) return;
    setDemoBusy(true);
    setDemoError(null);
    try {
      await onDemo();
      close();
    } catch (failure) {
      setDemoError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <div className="tour" data-testid="tour">
      {box !== null ? (
        <div
          className="tour__spotlight"
          style={{ top: box.top, left: box.left, width: box.width, height: box.height }}
          aria-hidden="true"
        />
      ) : (
        <div className="tour__veil" aria-hidden="true" />
      )}
      <div
        className={`tour__card${position === null ? " tour__card--centred" : ""}`}
        style={position === null ? undefined : { top: position.top, left: position.left, width: Math.min(CARD_WIDTH, viewport.width - 32) }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        data-testid="tour-card"
      >
        <p className="tour__count">
          {index + 1} of {TOUR_STEPS.length}
        </p>
        <h2 id="tour-title" className="tour__title">
          {step.title}
        </h2>
        <p className="tour__body">{step.body}</p>
        {demoError !== null && (
          <p className="field-error" role="alert">
            {demoError}
          </p>
        )}
        <div className="tour__actions">
          <button type="button" className="tour__skip" onClick={close}>
            {last ? "Finish" : "Skip the tour"}
          </button>
          <span className="tour__spacer" />
          {index > 0 && (
            <button
              type="button"
              className="button button--small"
              onClick={() => {
                setIndex(index - 1);
              }}
            >
              Back
            </button>
          )}
          {last ? (
            onDemo !== undefined && (
              <button
                ref={nextButton}
                type="button"
                className="button button--small button--primary"
                disabled={demoBusy}
                onClick={() => void demo()}
              >
                {demoBusy ? "Starting…" : "Try a demo run"}
              </button>
            )
          ) : (
            <button
              ref={nextButton}
              type="button"
              className="button button--small button--primary"
              onClick={() => {
                setIndex(index + 1);
              }}
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
