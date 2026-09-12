import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";


import { useRunStore } from "../state/runStore";
import { twoAgentRun } from "../test/log";

import { RunPanel } from "./RunPanel";

/**
 * BUILD_SPEC §5 Phase 7's acceptance criterion, as a test.
 *
 * > replaying a completed run produces pixel-identical UI state to what was
 * > shown live
 *
 * Pixels are not directly comparable in jsdom, and chasing them would be the
 * wrong target anyway: what the criterion is really asserting is that no state
 * reaches the screen except through the event log. Identical DOM under
 * identical CSS *is* identical pixels, and the DOM is checkable.
 *
 * The test is only worth anything because the two sides are genuinely different
 * code paths in `runStore`:
 *
 *  - **live**: `open()` then `appendEvent()` per event, folding forward one step
 *    at a time, exactly as the SSE client drives it.
 *  - **replay**: `open()` with the whole array, folding in bulk, exactly as
 *    opening a past run drives it.
 *
 * A component that read a clock, fetched anything, or kept run state of its own
 * would break this, and that is the point — the criterion is a constraint on
 * the components, not a property of the reducer alone.
 */

const store = () => useRunStore.getState();

/** Drive the store the way the live SSE client does. */
function live(events: ReturnType<typeof twoAgentRun>, upto = events.length) {
  store().open("run-1");
  for (const event of events.slice(0, upto)) store().appendEvent(event);
  return store();
}

/** Drive the store the way opening a finished run does. */
function replay(events: ReturnType<typeof twoAgentRun>, cursor?: number) {
  store().open("run-1", events);
  if (cursor !== undefined) store().setCursor(cursor);
  return store();
}

/** A finished run, as `RunsView` decides it: from the folded status. */
function finished(snapshot: ReturnType<typeof store>): boolean {
  const { status } = snapshot.view;
  return status === "completed" || status === "failed" || status === "cancelled";
}

/**
 * Render the run panel from a store snapshot, deciding the approval panel's
 * read-only state exactly as `RunsView` does — from the *transport* (`following`)
 * and the terminal status, never from the folded approval alone.
 */
function panel(snapshot: ReturnType<typeof store>) {
  return render(
    <RunPanel
      view={snapshot.view}
      events={snapshot.events}
      cursor={snapshot.cursor}
      selectedAgent={null}
      onSelectAgent={() => undefined}
      onCursorChange={() => undefined}
      approvalReadOnly={finished(snapshot) ? "finished" : snapshot.following ? null : "replay"}
      onResolveApproval={() => Promise.resolve()}
    />,
  );
}

/**
 * The markup of the run *projection* — the part that is a pure function of the
 * log. The scrubber is excluded on purpose and the exclusion is the honest one:
 * live at event 12 the log holds 12 events, replayed at 12 it holds 28 and you
 * are standing at 12 of them. See `RunPanel`.
 *
 * The approval panel's *question* is included for the same reason the summary
 * is: it is a fold of the log. Its action row is not — live at the head there
 * are buttons, replayed to the same position there are none — so it sits
 * beside the scrubber on the transport side of the line.
 */
function markup(snapshot: ReturnType<typeof store>): string {
  const rendered = panel(snapshot).container;
  const projection = rendered.querySelector('[data-testid="run-projection"]');
  if (projection === null) throw new Error("no run-projection was rendered");
  const question = rendered.querySelector('[data-testid="approval-question"]');
  return `${question?.innerHTML ?? ""}\n${projection.innerHTML}`;
}

/** The whole panel, transport included. Identical only at the head of a run. */
function wholePanel(snapshot: ReturnType<typeof store>): string {
  return region(snapshot, "run-panel");
}

/**
 * Render, then read one region's markup out of *that render's* container.
 *
 * Scoped to the container rather than the document because these tests render
 * twice inside one test — once per path — and a document-wide query would find
 * both copies and refuse to choose.
 */
function region(snapshot: ReturnType<typeof store>, testId: string): string {
  const found = panel(snapshot).container.querySelector(`[data-testid="${testId}"]`);
  if (found === null) throw new Error(`no ${testId} was rendered`);
  return found.innerHTML;
}

beforeEach(() => {
  useRunStore.getState().reset();
});

describe("replay renders identically to live", () => {
  it("produces the same DOM for a finished run watched live and replayed", () => {
    /* The acceptance criterion in its literal form, and the one case where even
       the transport control matches: a completed run replayed to its end is at
       the same position in the same log the live watcher ended at. */
    const events = twoAgentRun();

    const watchedLive = wholePanel(live(events));
    useRunStore.getState().reset();
    const replayed = wholePanel(replay(events));

    expect(replayed).toBe(watchedLive);
  });

  it("produces the same DOM at every intermediate position", () => {
    /* The scrubber's whole promise. Position N replayed must equal what the
       screen held when event N arrived — for every N, not just the last. */
    const events = twoAgentRun();

    for (let position = 0; position <= events.length; position += 1) {
      useRunStore.getState().reset();
      const watchedLive = markup(live(events, position));

      useRunStore.getState().reset();
      const replayed = markup(replay(events, position));

      expect(replayed, `position ${String(position)}`).toBe(watchedLive);
    }
  });

  it("produces the same DOM when the same log is delivered in different batches", () => {
    /* A reconnect re-reads a range, so the client legitimately sees the same
       run split at different points. */
    const events = twoAgentRun();
    const reference = markup(replay(events));

    for (const size of [1, 3, 7]) {
      useRunStore.getState().reset();
      store().open("run-1");
      for (let index = 0; index < events.length; index += size) {
        store().appendEvents(events.slice(index, index + size));
      }
      expect(markup(store()), `batch size ${String(size)}`).toBe(reference);
    }
  });

  it("produces the same DOM after a duplicate re-delivery of the whole log", () => {
    /* A fresh EventSource replays from the beginning because there is no way to
       set the initial Last-Event-ID. The screen must not change. */
    const events = twoAgentRun();
    const once = markup(live(events));

    for (const event of events) store().appendEvent(event);

    expect(markup(store())).toBe(once);
  });

  it("shows the question, and no way to answer it, when scrubbed into an approval span", () => {
    /* The bug this pins: `readOnly` used to come from the folded status, which
       at this position says "running", so a finished run scrubbed back here
       rendered live Allow/Deny buttons under a backdrop that covered the
       scrubber. The fold is right that the question was open at this moment;
       the transport is right that it cannot be answered from here. */
    const events = twoAgentRun();
    const asked = events.findIndex((event) => event.type === "approval.requested") + 1;
    const { getByTestId, queryByRole } = panel(replay(events, asked));

    expect(getByTestId("approval-question").textContent).toContain("wants to create notes.txt");
    expect(queryByRole("button", { name: "Allow" })).toBeNull();
    expect(getByTestId("approval-actions").textContent).toContain("earlier point");
  });

  it("offers the answer only at the head of a live run", () => {
    const events = twoAgentRun();
    const asked = events.findIndex((event) => event.type === "approval.requested") + 1;
    const { getByRole } = panel(live(events, asked));

    expect(getByRole("button", { name: "Allow" })).toBeDefined();
  });

  it("renders nothing run-specific before any event arrives", () => {
    const empty = markup(live(twoAgentRun(), 0));

    useRunStore.getState().reset();
    const replayedEmpty = markup(replay(twoAgentRun(), 0));

    expect(replayedEmpty).toBe(empty);
  });
});

describe("what the panel refuses to do", () => {
  it("renders the same markup twice in a row from the same state", () => {
    /* The blunt instrument that catches a `Date.now()`, a `Math.random()`, or a
       `useId` leaking into the run view. Everything else in this file compares
       two paths; this one compares one path to itself. */
    const snapshot = replay(twoAgentRun());

    expect(wholePanel(snapshot)).toBe(wholePanel(snapshot));
  });

  it("does not show the terminal summary as a statement of what happened", () => {
    /* CLAUDE.md's first warning for this phase. The fixture's summary claims a
       file was saved; the log contains a `write_file` call, but the panel must
       label the sentence as a claim either way rather than presenting it as the
       run's outcome. */
    const snapshot = replay(twoAgentRun());
    const { getByTestId } = panel(snapshot);

    const claim = getByTestId("run-claim");
    expect(claim.textContent).toContain("The supervisor's account of the run");
    expect(claim.textContent).toContain("This is what the agent said it did");
  });

  it("shows what actually executed beside the claim", () => {
    const snapshot = replay(twoAgentRun());
    const { getByTestId } = panel(snapshot);

    expect(getByTestId("fact-tool-calls").textContent).toBe("2");
    expect(getByTestId("fact-denied").textContent).toContain("1");
  });

  it("distinguishes a sandbox refusal from an ordinary denial", () => {
    /* CLAUDE.md's third warning: "The user said no" and "the agent tried to
       leave the workspace" are the same event type and must not read alike. */
    const snapshot = replay(twoAgentRun());
    const { getByTestId } = panel(snapshot);

    expect(getByTestId("fact-denied").textContent).toContain("sandbox");
    expect(getByTestId("event-log").textContent).toContain("The sandbox stopped researcher");
  });
});
