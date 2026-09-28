import type { Event, EventType } from "@agentbase/schemas";

/**
 * Resumable SSE client for one run's event stream.
 *
 * Frames leave `event:` unnamed so `onmessage` fires; their type is JSON. The
 * browser sends `Last-Event-ID` on reconnect and initial `after_seq` resumes
 * history. Close on terminal events because `EventSource` otherwise reconnects
 * after the server ends a finished run.
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
  /** Called when the stream attaches, drops, or terminates with the run. */
  onOpen?: () => void;
  onClosed?: (reason: "run-finished" | "cancelled") => void;
  /** Connection trouble: retrying or permanently closed. */
  onError?: (message: string) => void;
  /** One unreadable frame; unlike `onError`, it does not break the connection. */
  onBadFrame?: (raw: string) => void;
}

export interface RunStreamHandle {
  close: () => void;
}

/** Injectable EventSource constructor for browser-free tests. */
export type EventSourceFactory = (url: string) => EventSource;

const defaultFactory: EventSourceFactory = (url) => new EventSource(url);

export interface RunStreamOptions {
  factory?: EventSourceFactory;
  /** Request only events after this history-head `seq`. */
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
      // Prevent `EventSource` reconnecting forever after server completion.
      shutdown("run-finished");
    }
  };

  source.onerror = () => {
    if (closed) return;

    // `readyState` separates retrying disconnections from permanent failures.
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
