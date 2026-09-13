import type { Event } from "@agentspace/schemas";
import { useEffect } from "react";

import { baseUrl, getRunHistory } from "../lib/api";
import { isTerminal, streamRun } from "../lib/events";

import { useRunStore } from "./runStore";

/**
 * Attach the run store to one run's SSE stream: a pipe from the stream into
 * `appendEvents` and nowhere else. History is fetched first and the stream
 * asked only for what came after it; the store is not touched until the
 * history is in, so the previous run stays on screen; and frames are handed
 * over once per animation frame, so a burst of tokens is one render.
 */
export function useRunStream(runId: string | null): void {
  const open = useRunStore((state) => state.open);
  const appendEvents = useRunStore((state) => state.appendEvents);
  const setConnection = useRunStore((state) => state.setConnection);

  useEffect(() => {
    if (runId === null) return;

    let cancelled = false;

    // The frame buffer. `scheduled` is the pending animation frame, if any.
    let buffered: Parameters<typeof appendEvents>[0] = [];
    let scheduled: number | null = null;

    const flush = () => {
      scheduled = null;
      if (cancelled || buffered.length === 0) return;
      const batch = buffered;
      buffered = [];
      appendEvents(batch);
    };

    const attach = async () => {
      const origin = await baseUrl();
      let history: readonly Event[] = [];

      try {
        history = await getRunHistory(runId);
      } catch {
        // A history fetch that fails is not fatal: the stream carries the same
        // events, from the beginning. Reporting it would put an error on screen
        // for a run that is about to render correctly anyway.
      }

      if (cancelled) return null;
      open(runId, history);

      const afterSeq = history.reduce((head, event) => Math.max(head, event.seq), 0);
      // The history ends the run: there is nothing to stream, and asking
      // would get an empty response that `EventSource` treats as a drop
      // and retries once a second for as long as the run stays open.
      const last = history.find((event) => event.seq === afterSeq);
      if (last !== undefined && isTerminal(last.type)) {
        setConnection({ kind: "closed", reason: "run-finished" });
        return null;
      }

      return streamRun(origin, runId, {
        onEvent: (event) => {
          if (cancelled) return;
          buffered = [...buffered, event];
          scheduled ??= requestAnimationFrame(flush);
        },
        onOpen: () => {
          if (!cancelled) setConnection({ kind: "live" });
        },
        onClosed: (reason) => {
          if (!cancelled && reason === "run-finished") {
            setConnection({ kind: "closed", reason: "run-finished" });
          }
        },
        onError: (message) => {
          if (!cancelled) setConnection({ kind: "error", message });
        },
        onBadFrame: (raw) => {
          // Loud, but not on the connection indicator: the stream is fine.
          console.warn("agentspace: dropped a frame that was not an event", raw);
        },
      }, { afterSeq });
    };

    const pending = attach();

    return () => {
      cancelled = true;
      if (scheduled !== null) cancelAnimationFrame(scheduled);
      buffered = [];
      void pending.then((handle) => handle?.close());
    };
  }, [runId, open, appendEvents, setConnection]);
}
