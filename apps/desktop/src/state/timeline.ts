import type { Event } from "@agentbase/schemas";

import { flag, text, type Payload } from "../lib/payload";
import { toolInfo } from "../lib/tools";

import { sentenceFor } from "./describe";

/**
 * The run's timeline (Phase 20, brief 7.8 and 7.10): which events are worth
 * a mark on the scrubber's track, where the next one is, and whether a move
 * of the cursor is one step to animate or a jump to settle. Pure functions
 * of the event list and cursor positions; playback timers live with the
 * transport that calls them.
 *
 * A cursor is a count of events: at cursor N the room shows events 1 to N.
 */

export type MarkerKind = "handoff" | "question" | "denial" | "error" | "file" | "end";

export interface Marker {
  /** The cursor at which this event has just happened. */
  readonly cursor: number;
  readonly seq: number;
  readonly kind: MarkerKind;
  /** The event in one sentence, as the log says it. */
  readonly label: string;
}

function kindOf(event: Event): MarkerKind | null {
  const payload = (event.payload ?? {}) as Payload;
  switch (event.type) {
    case "agent.handoff":
      return "handoff";
    case "approval.requested":
      // A question a person had to answer; a policy's own answer is not one.
      return flag(payload, "automatic") ? null : "question";
    case "tool.denied":
      return "denial";
    case "tool.error":
    case "run.failed":
      return "error";
    case "llm.error":
      // A call that is about to be tried again has not failed yet.
      return flag(payload, "will_retry") ? null : "error";
    case "tool.result": {
      const tool = text(payload, "tool") ?? "";
      return tool === "write_file" || toolInfo(tool).reportsWritten ? "file" : null;
    }
    case "run.completed":
    case "run.cancelled":
      return "end";
    default:
      return null;
  }
}

/**
 * Each event's mark, worked out once: a live run hands over a new list with
 * every batch, and its earlier events are the same objects, so the track is
 * rebuilt by looking them up rather than saying each one again.
 */
const marks = new WeakMap<Event, { readonly kind: MarkerKind; readonly label: string } | null>();

function markOf(event: Event): { readonly kind: MarkerKind; readonly label: string } | null {
  if (marks.has(event)) return marks.get(event) ?? null;
  const kind = kindOf(event);
  const mark = kind === null ? null : { kind, label: sentenceFor(event) };
  marks.set(event, mark);
  return mark;
}

/** The events worth a mark on the track, in order. */
export function notableEvents(events: readonly Event[]): Marker[] {
  return events.flatMap((event, index): Marker[] => {
    const mark = markOf(event);
    return mark === null ? [] : [{ cursor: index + 1, seq: event.seq, ...mark }];
  });
}

/** The cursor of the next notable event after `cursor`, if there is one. */
export function nextNotable(markers: readonly Marker[], cursor: number): number | null {
  return markers.find((marker) => marker.cursor > cursor)?.cursor ?? null;
}

/** The cursor of the notable event before `cursor`, if there is one. */
export function previousNotable(markers: readonly Marker[], cursor: number): number | null {
  return markers.findLast((marker) => marker.cursor < cursor)?.cursor ?? null;
}

// --- motion ---------------------------------------------------------------------

/**
 * Whether a move of the cursor is a step, which the office may animate, or
 * anything else, which it settles at once: a jump, a step back, opening a
 * run. This is transport: the room at rest is the same either way, so it
 * goes on a wrapper outside what replay identity compares (decision D1).
 */
export type MotionMode = "step" | "settle";

/** A move of at most this many events, token bursts aside, is a step. */
export const STEP_EVENTS = 3;

export function motionMode(events: readonly Event[], from: number, to: number): MotionMode {
  if (to <= from) return "settle";
  // A burst of streamed tokens is one thing happening, however many events.
  let counted = 0;
  let inBurst = false;
  for (const event of events.slice(from, to)) {
    const token = event.type === "llm.token";
    if (!token || !inBurst) counted += 1;
    inBurst = token;
  }
  return counted <= STEP_EVENTS ? "step" : "settle";
}

// --- playback -------------------------------------------------------------------

export const PLAYBACK_SPEEDS = [1, 2, 4, 8] as const;
export type PlaybackSpeed = (typeof PLAYBACK_SPEEDS)[number];

/** How long playback rests on an event at 1x: long enough to see its motion. */
export const PLAYBACK_STEP_MS = 600;

/** How long to wait before the next event, at a speed. Streamed tokens run quicker. */
export function playbackDelay(next: Event | undefined, speed: PlaybackSpeed): number {
  const base = next?.type === "llm.token" ? PLAYBACK_STEP_MS / 6 : PLAYBACK_STEP_MS;
  return Math.round(base / speed);
}
