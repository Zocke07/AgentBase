import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { Section } from "../lib/sections";
import { CARD_WIDTH, place, TOUR_STEPS, type Box } from "../lib/tour";
import { usePresence } from "../state/usePresence";

/**
 * First-run tour of real rail, goal, and key targets, ending on a no-key demo
 * canvas. Build spotlight from target rectangle; switch mounted `hidden`
 * sections before measuring.
 *
 * Shell owns sidecar `onboarding_completed`; component only reports finish/skip.
 */

export interface TourProps {
  open: boolean;
  section: Section;
  onSection: (section: Section) => void;
  /** Finish or skip; neither reopens automatically. */
  onClose: () => void;
  /** Start/open scripted demo; absent before sidecar readiness. */
  onDemo?: (() => Promise<void>) | undefined;
}

/** Room around the spotlight. */
const RING = 6;

function measure(target: string | null): Box | null {
  if (target === null) return null;
  const element = document.querySelector(`[data-tour="${target}"]`);
  if (!(element instanceof HTMLElement)) return null;
  if (element.closest("[hidden]") !== null) return null;
  // Center deep scroll targets before spotlighting, at once: a scroller
  // that eases (Settings does) would be measured halfway, and the card
  // placed where the target was, off the window.
  if (typeof element.scrollIntoView === "function") element.scrollIntoView({ block: "center", behavior: "instant" });
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return { top: rect.top - RING, left: rect.left - RING, width: rect.width + RING * 2, height: rect.height + RING * 2 };
}

export function Tour({ open, section, onSection, onClose, onDemo }: TourProps) {
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  // The card's height as drawn, so it is placed wholly inside the window.
  const [cardHeight, setCardHeight] = useState(240);
  const card = useRef<HTMLDivElement>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const nextButton = useRef<HTMLButtonElement>(null);
  const step = TOUR_STEPS[index] ?? TOUR_STEPS[0];
  const last = index === TOUR_STEPS.length - 1;
  // Retain current step through exit animation; re-open restarts tour.
  const { mounted, closing } = usePresence(open, 200);
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) setIndex(0);
  }

  // Switch section, then wait a frame for target render before measuring.
  useLayoutEffect(() => {
    if (!open || step === undefined) return undefined;
    if (step.section !== null && step.section !== section) onSection(step.section);
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        setBox(measure(step.target));
      });
    });
    // A resize, or a scroll anywhere, moves the target: follow it.
    const onResize = () => {
      setBox(measure(step.target));
    };
    window.addEventListener("resize", onResize);
    document.addEventListener("scroll", onResize, { capture: true, passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("scroll", onResize, { capture: true });
    };
  }, [open, step, section, onSection]);

  useEffect(() => {
    if (open) nextButton.current?.focus();
  }, [open, index]);

  // The tour moves the window between sections; a section's cross-fade
  // would draw over its card (lib/viewTransition.ts), so there is none.
  useEffect(() => {
    if (!mounted) return undefined;
    const root = document.documentElement;
    root.dataset.viewTransitions = "off";
    return () => {
      delete root.dataset.viewTransitions;
    };
  }, [mounted]);

  // Measure the card once drawn; a step's words change its height.
  useLayoutEffect(() => {
    const element = card.current;
    if (element === null) return undefined;
    const read = () => {
      setCardHeight(element.offsetHeight);
    };
    read();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(read);
    observer?.observe(element);
    return () => {
      observer?.disconnect();
    };
  }, [mounted, index]);

  const close = useCallback(() => {
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

  if (!mounted || step === undefined) return null;

  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const position = place(box, viewport, cardHeight);

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
    <div className={`tour${closing ? " tour--closing" : ""}`} data-testid="tour">
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
        ref={card}
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
