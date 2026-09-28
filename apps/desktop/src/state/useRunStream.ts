import type { Event } from "@agentbase/schemas";
import { useEffect } from "react";

import { baseUrl, getRunHistory } from "../lib/api";
import { isTerminal, streamRun } from "../lib/events";

import { useRunStore } from "./runStore";

/**
 * Pipe one SSE stream into `appendEvents`. Fetch history first, then request
 * later events; leave the prior run visible until history arrives. Batch frames
 * per animation frame so token bursts render once.
 */
export function useRunStream(runId: string | null): void {
  const open = useRunStore((state) => state.open);
  const appendEvents = useRunStore((state) => state.appendEvents);
  const setConnection = useRunStore((state) => state.setConnection);

  useEffect(() => {
    if (runId === null) return;

    let cancelled = false;

    // Frame buffer and pending animation frame.
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
        // Stream fallback supplies history from the start; do not surface an
        // error for a run that will render correctly.
      }

      if (cancelled) return null;
      open(runId, history);

      const afterSeq = history.reduce((head, event) => Math.max(head, event.seq), 0);
      // Terminal history needs no stream; an empty response makes EventSource
      // retry forever.
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
          // Report loudly without marking a healthy stream disconnected.
          console.warn("agentbase: dropped a frame that was not an event", raw);
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
