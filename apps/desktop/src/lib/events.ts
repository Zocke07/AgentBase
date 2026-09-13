import type { Event, EventType } from "@agentspace/schemas";

/**
 * The SSE client: one run's event stream, resumable.
 *
 * Frames carry no `event:` name (a named event never fires `onmessage`); the
 * type is in the JSON body. `Last-Event-ID` is the browser's job on a
 * reconnect, and `after_seq` in the URL covers the initial connection, which
 * cannot carry the header. The server closes the stream when the run ends
 * and `EventSource` treats that as a disconnect, so this client closes itself
 * on a terminal event rather than reconnecting to a finished run forever.
 */

/** `EventSource.CLOSED`, as a number so the module works without the global. */
const READY_STATE_CLOSED = 2;

/** Events after which no further event can appear for a run (§4). */
const TERMINAL: ReadonlySet<EventType> = new Set<EventType>([
  "run.completed",
  "run.failed",
  "run.cancelled",
]);

/** Whether an event ends its run: after it, there is nothing to stream. */
export function isTerminal(type: EventType): boolean {
  return TERMINAL.has(type);
}

export interface RunStreamHandlers {
  onEvent: (event: Event) => void;
  /** Called when the stream attaches, drops, or ends because the run ended. */
  onOpen?: () => void;
  onClosed?: (reason: "run-finished" | "cancelled") => void;
  /** The *connection* is in trouble: reconnecting, or gone for good. */
  onError?: (message: string) => void;
  /** One frame could not be read. Not `onError`: a bad frame is not a broken connection. */
  onBadFrame?: (raw: string) => void;
}

export interface RunStreamHandle {
  close: () => void;
}

/** Injectable so tests can drive this without a browser; production gets the real one. */
export type EventSourceFactory = (url: string) => EventSource;

const defaultFactory: EventSourceFactory = (url) => new EventSource(url);

export interface RunStreamOptions {
  factory?: EventSourceFactory;
  /** Ask for events after this `seq` only: the head of an already-loaded history. */
  afterSeq?: number;
}

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

/** Subscribe to a run's events. The handle's `close()` is idempotent. */
export function streamRun(
  baseUrl: string,
  runId: string,
  handlers: RunStreamHandlers,
  options: RunStreamOptions = {},
): RunStreamHandle {
  const factory = options.factory ?? defaultFactory;
  const resume =
    options.afterSeq !== undefined && options.afterSeq > 0
      ? `?after_seq=${String(options.afterSeq)}`
      : "";
  const source = factory(`${baseUrl}/runs/${runId}/events${resume}`);
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
      handlers.onBadFrame?.(message.data);
      return;
    }

    handlers.onEvent(event);

    if (TERMINAL.has(event.type)) {
      // The server has ended the response; without this `EventSource` would reconnect forever.
      shutdown("run-finished");
    }
  };

  source.onerror = () => {
    if (closed) return;

    // A dropped connection and a permanent failure share this handler;
    // `readyState` separates them. CONNECTING means it is already retrying.
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
