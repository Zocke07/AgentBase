import { beforeEach, describe, expect, it } from "vitest";

import { twoAgentRun } from "../test/log";

import { useRunStore } from "./runStore";


/**
 * The store's job is to be the single path to a rendered run.
 *
 * The tests that matter are the two-path ones: feeding events in one at a time
 * (what SSE does) and loading a whole history at once (what replay does) must
 * land on the same `view`. If they ever diverge, §5 Phase 7's acceptance
 * criterion is false however careful the components are.
 */

const store = () => useRunStore.getState();

beforeEach(() => {
  useRunStore.getState().reset();
});

describe("live and replay are the same fold", () => {
  it("reaches the same view whether events stream in or arrive as history", () => {
    const events = twoAgentRun();

    store().open("run-1");
    for (const event of events) store().appendEvent(event);
    const live = store().view;

    useRunStore.getState().reset();
    store().open("run-1", events);
    const replayed = store().view;

    expect(replayed).toEqual(live);
  });

  it("scrubbing to a position shows what that position showed live", () => {
    const events = twoAgentRun();

    // What the user saw when event 12 arrived, live.
    store().open("run-1");
    for (const event of events.slice(0, 12)) store().appendEvent(event);
    const liveAtTwelve = store().view;

    // The same position, reached by loading the whole run and scrubbing back.
    useRunStore.getState().reset();
    store().open("run-1", events);
    store().setCursor(12);

    expect(store().view).toEqual(liveAtTwelve);
  });

  it("scrubbing backwards and forwards again returns to the same view", () => {
    const events = twoAgentRun();
    store().open("run-1", events);
    const atHead = store().view;

    store().setCursor(5);
    store().setCursor(events.length);

    expect(store().view).toEqual(atHead);
  });

  it("reaches the same view by scrubbing forward one step at a time", () => {
    /* The incremental path through `setCursor` is not the same code as the
       incremental path through `appendEvent`, and both have to agree with the
       bulk fold or the scrubber drifts from the stream. */
    const events = twoAgentRun();
    store().open("run-1", events);
    const atHead = store().view;

    store().setCursor(0);
    for (let n = 1; n <= events.length; n += 1) store().setCursor(n);

    expect(store().view).toEqual(atHead);
  });
});

describe("the cursor", () => {
  it("follows the head while live", () => {
    const events = twoAgentRun();
    store().open("run-1");

    for (const event of events) store().appendEvent(event);

    expect(store().cursor).toBe(events.length);
    expect(store().following).toBe(true);
  });

  it("stops following once the user scrubs back", () => {
    const events = twoAgentRun();
    store().open("run-1", events);

    store().setCursor(3);

    expect(store().following).toBe(false);
  });

  it("does not jump to the head when an event arrives mid-scrub", () => {
    /* Otherwise inspecting a live run is impossible: every arriving event would
       yank the view out from under the person reading it. */
    const events = twoAgentRun();
    store().open("run-1");
    for (const event of events.slice(0, 10)) store().appendEvent(event);
    store().setCursor(4);
    const whileScrubbed = store().view;

    for (const event of events.slice(10)) store().appendEvent(event);

    expect(store().cursor).toBe(4);
    expect(store().view).toEqual(whileScrubbed);
    // The events are still collected, so releasing the scrub shows everything.
    expect(store().events).toHaveLength(events.length);
  });

  it("catches up to everything that arrived while scrubbed when following resumes", () => {
    const events = twoAgentRun();
    store().open("run-1", events.slice(0, 10));
    store().setCursor(4);
    for (const event of events.slice(10)) store().appendEvent(event);

    store().follow();

    expect(store().cursor).toBe(events.length);
    expect(store().following).toBe(true);
    expect(store().view.status).toBe("completed");
  });

  it("keeps folding the head while the view is scrubbed back", () => {
    /* The picker's badge and the "did this run finish while I watched" check
       need the state at the head, whatever the scrubber shows. Folding it
       alongside costs one `reduce` per event and is the same fold. */
    const events = twoAgentRun();
    store().open("run-1");
    for (const event of events.slice(0, 10)) store().appendEvent(event);
    store().setCursor(4);

    for (const event of events.slice(10)) store().appendEvent(event);

    expect(store().view.status).toBe("running");
    expect(store().headView.status).toBe("completed");
    expect(store().headView.eventCount).toBe(events.length);

    store().follow();
    expect(store().view).toBe(store().headView);
  });

  it("clamps a cursor outside the log", () => {
    const events = twoAgentRun();
    store().open("run-1", events);

    store().setCursor(-5);
    expect(store().cursor).toBe(0);

    store().setCursor(9999);
    expect(store().cursor).toBe(events.length);
  });

  it("shows an empty run at cursor zero", () => {
    store().open("run-1", twoAgentRun());

    store().setCursor(0);

    expect(store().view.agentOrder).toEqual([]);
    expect(store().view.status).toBe("pending");
  });
});

describe("batched delivery", () => {
  it("reaches the same state as one event at a time, in one update", () => {
    /* The SSE client hands the store a frame's worth of events at once so a
       burst of `llm.token`s is one render, not fifty. The batch must fold to
       exactly what the singles fold to — it is the same path, called less. */
    const events = twoAgentRun();
    store().open("run-1");
    for (const event of events) store().appendEvent(event);
    const singly = store();

    useRunStore.getState().reset();
    store().open("run-1");
    let updates = 0;
    const unsubscribe = useRunStore.subscribe(() => {
      updates += 1;
    });
    store().appendEvents(events);
    unsubscribe();

    expect(store().view).toEqual(singly.view);
    expect(store().cursor).toBe(singly.cursor);
    expect(store().events).toEqual(singly.events);
    expect(updates).toBe(1);
  });

  it("drops duplicates inside a batch and against what it already holds", () => {
    const events = twoAgentRun();
    store().open("run-1");
    store().appendEvents(events.slice(0, 5));

    store().appendEvents([...events.slice(3, 8), ...events.slice(6, 8)]);

    expect(store().events.map((event) => event.seq)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("collects a batch without moving a scrubbed view", () => {
    const events = twoAgentRun();
    store().open("run-1");
    store().appendEvents(events.slice(0, 10));
    store().setCursor(4);
    const whileScrubbed = store().view;

    store().appendEvents(events.slice(10));

    expect(store().view).toBe(whileScrubbed);
    expect(store().headView.status).toBe("completed");
  });
});

describe("duplicate and repeated delivery", () => {
  it("ignores an event it already holds", () => {
    /* A reconnect re-reads from the client's cursor and a fresh EventSource
       re-reads from the start, so the same event arriving twice is ordinary
       rather than exceptional. */
    const events = twoAgentRun();
    store().open("run-1");
    for (const event of events) store().appendEvent(event);
    const once = store().view;

    for (const event of events) store().appendEvent(event);

    expect(store().events).toHaveLength(events.length);
    expect(store().view).toEqual(once);
  });

  it("survives the whole log being re-delivered after a partial one", () => {
    const events = twoAgentRun();
    store().open("run-1");
    for (const event of events.slice(0, 8)) store().appendEvent(event);

    for (const event of events) store().appendEvent(event);

    expect(store().events.map((event) => event.seq)).toEqual(events.map((event) => event.seq));
  });

  it("counts a gap in the sequence rather than hiding it", () => {
    /* The server re-reads from SQLite on any anomaly precisely so the client
       never sees a gap, and the store's contract says "no gaps". A contract
       that is asserted in a comment and checked nowhere is the kind Phase 2's
       named-event bug hid behind. The event is kept — dropping it would lose
       more — and the gap is counted where the connection label can say so. */
    const [first, , third, fourth] = twoAgentRun();
    if (first === undefined || third === undefined || fourth === undefined) throw new Error("fixture");
    store().open("run-1");
    store().appendEvent(first);
    store().appendEvent(third);

    expect(store().events.map((event) => event.seq)).toEqual([1, 3]);
    expect(store().gaps).toBe(1);

    store().appendEvent(fourth);
    expect(store().gaps).toBe(1);
  });

  it("orders a history that arrives unsorted", () => {
    const events = twoAgentRun();

    store().open("run-1", [...events].reverse());

    expect(store().events.map((event) => event.seq)).toEqual(events.map((event) => event.seq));
    expect(store().view.status).toBe("completed");
  });
});

describe("opening a run", () => {
  it("clears the previous run entirely", () => {
    store().open("run-1", twoAgentRun());

    store().open("run-2");

    expect(store().runId).toBe("run-2");
    expect(store().events).toEqual([]);
    expect(store().view.agentOrder).toEqual([]);
    expect(store().view.claim).toBeNull();
  });
});
