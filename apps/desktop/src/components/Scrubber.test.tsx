import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { nextNotable, notableEvents, PLAYBACK_STEP_MS, previousNotable } from "../state/timeline";
import { scenario } from "../test/scenarios";

import { Scrubber } from "./Scrubber";

const { events } = scenario("two-agents");

/** The scrubber with its cursor held as a run view holds it. */
function Harness({ start, live = false, onMove }: { start: number; live?: boolean; onMove?: (cursor: number) => void }) {
  const [cursor, setCursor] = useState(start);
  return (
    <Scrubber
      events={events}
      cursor={cursor}
      loading={false}
      live={live}
      onCursorChange={(next) => {
        onMove?.(next);
        setCursor(next);
      }}
    />
  );
}

const position = () => screen.getByTestId("scrub-position").textContent;

/** Let playback run for a while: each step's effect schedules the next, so one act per step. */
function wait(ms: number) {
  for (let spent = 0; spent < ms; spent += 50) {
    act(() => {
      vi.advanceTimersByTime(50);
    });
  }
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the timeline", () => {
  it("keeps the scrubber's labels, values and test ids", () => {
    render(<Harness start={events.length} />);
    expect(screen.getByRole("slider", { name: "Position in the event log" })).toBeDefined();
    expect(screen.getByText("Replay")).toBeDefined();
    expect(position()).toBe(`${String(events.length)} / ${String(events.length)}`);
    expect(screen.getByTestId("scrub-state").textContent).toContain("Showing the latest event.");
  });

  it("plays one event at a time and stops at the end; from the end it plays from the start", () => {
    vi.useFakeTimers();
    const moves: number[] = [];
    render(<Harness start={events.length - 3} onMove={(cursor) => moves.push(cursor)} />);
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(screen.getByRole("button", { name: "Pause" })).toBeDefined();
    wait(PLAYBACK_STEP_MS * 10);
    // Every event in turn, never a jump: the room shows each step's motion.
    expect(moves).toEqual([events.length - 2, events.length - 1, events.length]);
    expect(screen.getByRole("button", { name: "Play" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(position()).toBe(`0 / ${String(events.length)}`);
    wait(PLAYBACK_STEP_MS * 2 + 50);
    expect(position()).toBe(`2 / ${String(events.length)}`);
  });

  it("plays faster at a higher speed", () => {
    vi.useFakeTimers();
    render(<Harness start={0} />);
    fireEvent.click(screen.getByTestId("timeline-speed"));
    expect(screen.getByTestId("timeline-speed").textContent).toBe("2×");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    wait(PLAYBACK_STEP_MS * 2);
    // Twice the steps of 1x in the same time; streamed tokens go quicker still.
    expect(Number(position().split(" / ")[0])).toBeGreaterThanOrEqual(4);
  });

  it("stops playing when the viewer moves the cursor, or the window is hidden", () => {
    vi.useFakeTimers();
    render(<Harness start={0} />);
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    expect(screen.getByRole("button", { name: "Play" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const held = position();
    wait(PLAYBACK_STEP_MS * 5);
    expect(position()).toBe(held);
  });

  it("steps, and jumps to the previous and next notable event by button and with Shift and the arrows", () => {
    const markers = notableEvents(events);
    expect(markers.length).toBeGreaterThan(1);
    render(<Harness start={0} />);
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    expect(position()).toBe(`1 / ${String(events.length)}`);
    fireEvent.click(screen.getByRole("button", { name: "Step back" }));
    expect(position()).toBe(`0 / ${String(events.length)}`);

    const first = nextNotable(markers, 0);
    fireEvent.click(screen.getByRole("button", { name: "Next notable event" }));
    expect(position()).toBe(`${String(first)} / ${String(events.length)}`);
    const slider = screen.getByRole("slider");
    fireEvent.keyDown(slider, { key: "ArrowRight", shiftKey: true });
    expect(position()).toBe(`${String(nextNotable(markers, first ?? 0))} / ${String(events.length)}`);
    fireEvent.keyDown(slider, { key: "ArrowLeft", shiftKey: true });
    expect(position()).toBe(`${String(first)} / ${String(events.length)}`);
    expect(previousNotable(markers, first ?? 0)).toBeNull();
    expect(screen.getByRole("button", { name: "Previous notable event" }).hasAttribute("disabled")).toBe(true);
  });

  it("marks each notable event on the track, out of the reading order, and a mark jumps there", () => {
    const markers = notableEvents(events);
    render(<Harness start={0} />);
    const marks = screen.getByTestId("timeline-marks");
    expect(marks.getAttribute("aria-hidden")).toBe("true");
    const buttons = marks.querySelectorAll("button");
    expect(buttons).toHaveLength(markers.length);
    const last = buttons[buttons.length - 1];
    if (last === undefined) throw new Error("no marks");
    expect(last.tabIndex).toBe(-1);
    fireEvent.click(last);
    expect(position()).toBe(`${String(markers.at(-1)?.cursor)} / ${String(events.length)}`);
  });

  it("keeps playing while a live run's events keep arriving", () => {
    vi.useFakeTimers();
    let cursor = 0;
    const props = (log: typeof events) => ({ events: log, cursor, loading: false, live: false, onCursorChange: (next: number) => (cursor = next) });
    const { rerender } = render(<Scrubber {...props(events.slice(0, 20))} />);
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    // A new batch every 50 ms, quicker than playback's step: the step still comes.
    // Each batch is a new array, as the run's store gives one.
    for (let batch = 1; batch <= 30 && cursor === 0; batch += 1) {
      act(() => {
        vi.advanceTimersByTime(50);
      });
      rerender(<Scrubber {...props(events.slice(0, Math.min(events.length, 20 + batch)))} />);
    }
    expect(cursor).toBe(1);
  });

  it("steps with the plain arrows anywhere in the bar, as the step buttons say", () => {
    render(<Harness start={3} />);
    const play = screen.getByRole("button", { name: "Play" });
    fireEvent.keyDown(play, { key: "ArrowRight" });
    expect(position()).toBe(`4 / ${String(events.length)}`);
    fireEvent.keyDown(play, { key: "ArrowLeft" });
    fireEvent.keyDown(play, { key: "ArrowLeft" });
    expect(position()).toBe(`2 / ${String(events.length)}`);
  });

  it("says Live while a running run is followed, and cannot play past what has arrived", () => {
    render(<Harness start={events.length} live />);
    expect(screen.getByTestId("timeline-live").textContent).toBe("Live");
    expect(screen.getByRole("button", { name: "Play" }).hasAttribute("disabled")).toBe(true);
  });
});
