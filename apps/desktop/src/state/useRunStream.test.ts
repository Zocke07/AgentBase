import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { RunStreamHandlers } from "../lib/events";
import * as events from "../lib/events";
import { twoAgentRun } from "../test/log";

import { useRunStore } from "./runStore";
import { useRunStream } from "./useRunStream";

/**
 * The pipe from the SSE client into the store.
 *
 * It is a pipe with one buffer in it: frames are collected and handed to the
 * store once per animation frame, so a burst of `llm.token`s — which arrive
 * one per SSE frame, each its own task — is one render rather than one each.
 * Everything else about it (history first, then stream; nothing after
 * unmount) is what these tests pin.
 */

vi.mock("../lib/api", () => ({
  getRunHistory: vi.fn(),
  baseUrl: vi.fn(() => Promise.resolve("http://x")),
}));

// Only the transport is replaced; the module's pure helpers stay real.
vi.mock("../lib/events", async (importOriginal) => ({
  ...(await importOriginal<typeof events>()),
  streamRun: vi.fn(),
}));

let handlers: RunStreamHandlers | null = null;
const close = vi.fn();
let frame: FrameRequestCallback | null = null;

beforeEach(() => {
  useRunStore.getState().reset();
  handlers = null;
  frame = null;
  close.mockReset();
  vi.mocked(events.streamRun).mockImplementation((_origin, _runId, attached) => {
    handlers = attached;
    return { close };
  });
  vi.mocked(api.getRunHistory).mockResolvedValue([]);
  // Animation frames are driven by hand so the test decides when a batch lands.
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frame = callback;
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {
    frame = null;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function attached(runId = "run-1") {
  const rendered = renderHook(({ id }: { id: string | null }) => { useRunStream(id); }, {
    initialProps: { id: runId },
  });
  await waitFor(() => {
    expect(handlers).not.toBeNull();
  });
  return rendered;
}

function paint() {
  act(() => {
    const pending = frame;
    frame = null;
    pending?.(0);
  });
}

describe("useRunStream", () => {
  it("hands a burst of frames to the store as one batch, on the next paint", async () => {
    await attached();
    const burst = twoAgentRun().slice(0, 6);
    let updates = 0;
    const unsubscribe = useRunStore.subscribe(() => {
      updates += 1;
    });

    act(() => {
      for (const event of burst) handlers?.onEvent(event);
    });
    expect(useRunStore.getState().events).toHaveLength(0);

    paint();
    unsubscribe();

    expect(useRunStore.getState().events).toHaveLength(6);
    expect(updates).toBe(1);
  });

  it("loads history first, then asks the stream for what came after it", async () => {
    const log = twoAgentRun();
    vi.mocked(api.getRunHistory).mockResolvedValue(log.slice(0, 10));

    await attached();

    expect(useRunStore.getState().events).toHaveLength(10);
    expect(vi.mocked(events.streamRun)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(events.streamRun).mock.calls[0]?.[3]).toEqual({ afterSeq: 10 });
  });

  it("does not open a stream for a run whose history already ended it", async () => {
    /* With `after_seq` at the terminal event the server would send nothing and
       close, and `EventSource` treats every ended response as a drop: a
       finished run would be re-requested once a second for as long as it was
       open. The history says the run is over; the connection says so too. */
    vi.mocked(api.getRunHistory).mockResolvedValue(twoAgentRun());

    renderHook(() => { useRunStream("run-1"); });
    await waitFor(() => {
      expect(useRunStore.getState().connection).toEqual({ kind: "closed", reason: "run-finished" });
    });

    expect(vi.mocked(events.streamRun)).not.toHaveBeenCalled();
    expect(useRunStore.getState().view.status).toBe("completed");
  });

  it("delivers nothing, and closes the stream, once the run is switched away from", async () => {
    const rendered = await attached();
    const first = handlers;

    rendered.rerender({ id: "run-2" });
    await waitFor(() => {
      expect(handlers).not.toBe(first);
    });

    const [firstEvent] = twoAgentRun();
    if (firstEvent === undefined) throw new Error("fixture");
    act(() => {
      first?.onEvent(firstEvent);
    });
    paint();

    expect(close).toHaveBeenCalled();
    expect(useRunStore.getState().events).toHaveLength(0);
  });
});
