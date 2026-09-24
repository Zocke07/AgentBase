import type { Event } from "@agentbase/schemas";
import { describe, expect, it, vi } from "vitest";

import { LogBuilder } from "../test/log";

import { parseFrame, streamRun, type EventSourceFactory } from "./events";



/**
 * The SSE client.
 *
 * The test that earns its place is the terminal-close one. The server ends the
 * response when a run ends, and `EventSource` treats every ended response as a
 * dropped connection, so a client that did not close itself would re-request a
 * finished run every second for as long as the window stayed open. Nothing
 * about that is visible from the server side, and nothing fails; it just
 * quietly polls forever.
 */

/** A stand-in for the browser's EventSource, driven by the test. */
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  onopen: (() => void) | null = null;
  onmessage: ((message: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = FakeEventSource.CONNECTING;
  closeCount = 0;

  constructor(readonly url: string) {}

  close() {
    this.closeCount += 1;
    this.readyState = FakeEventSource.CLOSED;
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  deliver(event: Event) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
  }

  deliverRaw(data: string) {
    this.onmessage?.({ data } as MessageEvent<string>);
  }

  fail(readyState: number) {
    this.readyState = readyState;
    this.onerror?.();
  }
}

function harness() {
  let source: FakeEventSource | undefined;
  const factory: EventSourceFactory = (url) => {
    source = new FakeEventSource(url);
    return source as unknown as EventSource;
  };
  return {
    factory,
    get source(): FakeEventSource {
      if (source === undefined) throw new Error("no EventSource was created");
      return source;
    },
  };
}

describe("streamRun", () => {
  it("subscribes to the run's event endpoint", () => {
    const stream = harness();

    streamRun("http://127.0.0.1:8787", "run-1", { onEvent: vi.fn() }, { factory: stream.factory });

    expect(stream.source.url).toBe("http://127.0.0.1:8787/runs/run-1/events");
  });

  it("asks the server to start after what it already holds", () => {
    /* `EventSource` cannot set `Last-Event-ID` on its first connection, so a
       client that has loaded the history used to receive the whole log a
       second time and drop every frame. The cursor goes in the URL instead;
       the server takes whichever of the two is further along. */
    const stream = harness();

    streamRun(
      "http://127.0.0.1:8787",
      "run-1",
      { onEvent: vi.fn() },
      { factory: stream.factory, afterSeq: 12 },
    );

    expect(stream.source.url).toBe("http://127.0.0.1:8787/runs/run-1/events?after_seq=12");
  });

  it("delivers every event that arrives on onmessage", () => {
    /* Unnamed frames, one handler. A client using addEventListener for named
       types would receive nothing here: Phase 2's bug, from the other side. */
    const stream = harness();
    const onEvent = vi.fn();
    const log = new LogBuilder();

    streamRun("http://x", "run-1", { onEvent }, { factory: stream.factory });
    stream.source.deliver(log.add("run.started", { goal: "g" }));
    stream.source.deliver(log.add("agent.spawned", { role: "r" }, "supervisor"));

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent.mock.calls[1]?.[0]).toMatchObject({ type: "agent.spawned" });
  });

  it("closes itself when the run finishes", () => {
    const stream = harness();
    const onClosed = vi.fn();
    const log = new LogBuilder();

    streamRun("http://x", "run-1", { onEvent: vi.fn(), onClosed }, { factory: stream.factory });
    stream.source.deliver(log.add("run.started", { goal: "g" }));
    expect(stream.source.closeCount).toBe(0);

    stream.source.deliver(log.add("run.completed", { summary: "done" }));

    expect(stream.source.closeCount).toBe(1);
    expect(onClosed).toHaveBeenCalledWith("run-finished");
  });

  it.each(["run.completed", "run.failed", "run.cancelled"] as const)(
    "treats %s as the end of the stream",
    (type) => {
      const stream = harness();
      const log = new LogBuilder();

      streamRun("http://x", "run-1", { onEvent: vi.fn() }, { factory: stream.factory });
      stream.source.deliver(log.add(type, {}));

      expect(stream.source.closeCount).toBe(1);
    },
  );

  it("does not close on a paused run", () => {
    /* `run.paused` is not terminal: more events follow it. */
    const stream = harness();
    const log = new LogBuilder();

    streamRun("http://x", "run-1", { onEvent: vi.fn() }, { factory: stream.factory });
    stream.source.deliver(log.add("run.paused", {}));

    expect(stream.source.closeCount).toBe(0);
  });

  it("reports a dropped connection as reconnecting, not as a failure", () => {
    /* The browser retries with `Last-Event-ID` by itself. Reporting this as an
       error would tell the user something is broken while it is being fixed. */
    const stream = harness();
    const onError = vi.fn();
    const onClosed = vi.fn();

    streamRun("http://x", "run-1", { onEvent: vi.fn(), onError, onClosed }, { factory: stream.factory });
    stream.source.fail(FakeEventSource.CONNECTING);

    expect(onError).toHaveBeenCalledWith("reconnecting to the event stream");
    expect(onClosed).not.toHaveBeenCalled();
  });

  it("reports a permanently closed stream as an error", () => {
    const stream = harness();
    const onError = vi.fn();
    const onClosed = vi.fn();

    streamRun("http://x", "run-1", { onEvent: vi.fn(), onError, onClosed }, { factory: stream.factory });
    stream.source.fail(FakeEventSource.CLOSED);

    expect(onError).toHaveBeenCalledWith("the event stream closed and will not reconnect");
    expect(onClosed).toHaveBeenCalledWith("cancelled");
  });

  it("ignores events that arrive after it closed", () => {
    const stream = harness();
    const onEvent = vi.fn();
    const log = new LogBuilder();

    const handle = streamRun("http://x", "run-1", { onEvent }, { factory: stream.factory });
    handle.close();
    stream.source.deliver(log.add("agent.thinking", { step: 1 }, "w"));

    expect(stream.source.closeCount).toBe(1);
  });

  it("closes at most once however many times it is asked", () => {
    /* React effects call `close()` on unmount, and the stream may already have
       closed itself when the run finished. */
    const stream = harness();
    const onClosed = vi.fn();

    const handle = streamRun("http://x", "run-1", { onEvent: vi.fn(), onClosed }, { factory: stream.factory });
    handle.close();
    handle.close();

    expect(stream.source.closeCount).toBe(1);
    expect(onClosed).toHaveBeenCalledTimes(1);
  });

  it("reports a malformed frame instead of throwing, and not as a connection error", () => {
    /* One bad frame used to go through `onError`, which the store renders as
       the connection's state, so the status line read "received a frame that
       was not an event" for the rest of the run while events kept arriving,
       because only a reconnect ever set it back to live. A bad frame is a fact
       about one frame; the stream is fine. */
    const stream = harness();
    const onEvent = vi.fn();
    const onError = vi.fn();
    const onBadFrame = vi.fn();

    streamRun("http://x", "run-1", { onEvent, onError, onBadFrame }, { factory: stream.factory });
    stream.source.deliverRaw("{not json");

    expect(onEvent).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(onBadFrame).toHaveBeenCalledWith("{not json");
  });

  it("signals the connection opening", () => {
    const stream = harness();
    const onOpen = vi.fn();

    streamRun("http://x", "run-1", { onEvent: vi.fn(), onOpen }, { factory: stream.factory });
    stream.source.open();

    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("parseFrame", () => {
  it("accepts a well-formed event", () => {
    const event = new LogBuilder().add("run.started", { goal: "g" });

    expect(parseFrame(JSON.stringify(event))).toEqual(event);
  });

  it.each([
    ["not json at all", "{oops"],
    ["a bare string", '"hello"'],
    ["null", "null"],
    ["an object with no seq", '{"type":"run.started"}'],
    ["an object with no type", '{"seq":1}'],
  ])("rejects %s", (_label, data) => {
    expect(parseFrame(data)).toBeNull();
  });
});
