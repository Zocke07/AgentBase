import type { Event, EventType } from "@agentspace/schemas";

/**
 * The SSE client: one run's event stream, resumable.
 *
 * Three things about this endpoint are load-bearing and each has cost this
 * project time before:
 *
 * **Frames carry no `event:` name.** They arrive on `onmessage` and the type is
 * inside the JSON body. That is deliberate on the server (see
 * `api/stream.py`): a *named* SSE event never fires `onmessage` at all, and a
 * client that had not called `addEventListener` for that exact name would drop
 * it silently. Phase 2 shipped that bug and a webview probe received 0 of 20
 * events while every terminal test was green.
 *
 * **`Last-Event-ID` is the browser's job, not ours.** `EventSource` records the
 * `id:` of the last frame and sends it back on reconnect by itself, which is why
 * the server publishes the per-run `seq` as the frame id. There is no way to set
 * it on the initial connection — so a fresh subscription always replays the run
 * from the beginning, and the store's duplicate handling is what makes that a
 * non-event rather than a bug.
 *
 * **The server closes the stream when the run ends, and `EventSource` treats a
 * closed stream as a disconnect.** Left alone it would reconnect a second later,
 * receive the same finished log, and do it again forever. So this client closes
 * itself the moment a terminal event arrives. That is the one piece of
 * protocol knowledge the client cannot get from the frames alone.
 */

/**
 * `EventSource.CLOSED`, as a number rather than a read of the global.
 *
 * The value is fixed by the HTML specification, and reading it off the global
 * constructor would mean this module only works where that global exists —
 * which rules out injecting a different implementation, and made the error path
 * below untestable until it was written this way.
 */
const READY_STATE_CLOSED = 2;

/** Events after which no further event can appear for a run (§4). */
const TERMINAL: ReadonlySet<EventType> = new Set<EventType>([
  "run.completed",
  "run.failed",
  "run.cancelled",
]);

export interface RunStreamHandlers {
  onEvent: (event: Event) => void;
  /** Called when the stream attaches, drops, or ends because the run ended. */
  onOpen?: () => void;
  onClosed?: (reason: "run-finished" | "cancelled") => void;
  onError?: (message: string) => void;
}

export interface RunStreamHandle {
  close: () => void;
}

/**
 * `EventSource` is not in jsdom, and injecting the constructor is how the tests
 * drive this without a browser. Production passes nothing and gets the real one.
 */
export type EventSourceFactory = (url: string) => EventSource;

const defaultFactory: EventSourceFactory = (url) => new EventSource(url);

/** Parse one frame body, returning null rather than throwing on nonsense. */
export function parseFrame(data: string): Event | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (typeof parsed !== "object" || parsed === null) return null;

    const candidate = parsed as Partial<Event>;
    if (typeof candidate.seq !== "number" || typeof candidate.type !== "string") return null;

    return candidate as Event;
  } catch {
    return null;
  }
}

/**
 * Subscribe to a run's events.
 *
 * Returns a handle whose `close()` is idempotent — React effects call it on
 * unmount, and it also runs when the run finishes.
 */
export function streamRun(
  baseUrl: string,
  runId: string,
  handlers: RunStreamHandlers,
  factory: EventSourceFactory = defaultFactory,
): RunStreamHandle {
  const source = factory(`${baseUrl}/runs/${runId}/events`);
  let closed = false;

  const shutdown = (reason: "run-finished" | "cancelled") => {
    if (closed) return;
    closed = true;
    source.close();
    handlers.onClosed?.(reason);
  };

  source.onopen = () => {
    if (!closed) handlers.onOpen?.();
  };

  source.onmessage = (message: MessageEvent<string>) => {
    const event = parseFrame(message.data);
    if (event === null) {
      handlers.onError?.("received a frame that was not an event");
      return;
    }

    handlers.onEvent(event);

    if (TERMINAL.has(event.type)) {
      // The run is over and the server has already ended the response. Closing
      // here is what stops `EventSource` reconnecting to a finished run once a
      // second for as long as the window is open.
      shutdown("run-finished");
    }
  };

  source.onerror = () => {
    if (closed) return;

    // `EventSource` reports a dropped connection and a permanent failure through
    // the same handler; `readyState` is the only thing that separates them.
    // CONNECTING means it is already retrying with the last id, which is the
    // resume path Phase 2 built the server side of — there is nothing to do but
    // say so.
    if (source.readyState === READY_STATE_CLOSED) {
      closed = true;
      handlers.onError?.("the event stream closed and will not reconnect");
      handlers.onClosed?.("cancelled");
      return;
    }

    handlers.onError?.("reconnecting to the event stream");
  };

  return { close: () => { shutdown("cancelled"); } };
}
