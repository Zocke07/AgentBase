import { useEffect } from "react";


import { baseUrl, getRunHistory } from "../lib/api";
import { streamRun } from "../lib/events";

import { useRunStore } from "./runStore";

/**
 * Attach the run store to one run's SSE stream.
 *
 * The whole hook is a pipe: events go from the stream into `appendEvent` and
 * nowhere else. Nothing here interprets an event, and nothing here writes run
 * state directly — that is the reducer's job, and a second writer would be the
 * ad-hoc message §2 forbids.
 *
 * **History is fetched first, then the stream attaches.** The subscription
 * replays the whole log anyway, so this is not about completeness; it is about a
 * finished run rendering immediately instead of after a round trip that ends in
 * an instant close. The store's duplicate handling makes the overlap free.
 */
export function useRunStream(runId: string | null): void {
  const open = useRunStore((state) => state.open);
  const loadHistory = useRunStore((state) => state.loadHistory);
  const appendEvent = useRunStore((state) => state.appendEvent);
  const setConnection = useRunStore((state) => state.setConnection);

  useEffect(() => {
    if (runId === null) return;

    let cancelled = false;
    open(runId);

    const attach = async () => {
      const origin = await baseUrl();

      try {
        const history = await getRunHistory(runId);
        if (cancelled) return;
        if (history.length > 0) loadHistory(history);
      } catch {
        // A history fetch that fails is not fatal: the stream carries the same
        // events. Reporting it would put an error on screen for a run that is
        // about to render correctly anyway.
      }

      if (cancelled) return null;

      return streamRun(origin, runId, {
        onEvent: (event) => {
          if (!cancelled) appendEvent(event);
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
          // Loud, but not on the connection indicator: the stream is fine and
          // the next frame will be read. The reducer's `unrecognised` list is
          // for a *type* this build does not know; this is a frame that is not
          // an event at all, which nothing downstream can render.
          console.warn("agentspace: dropped a frame that was not an event", raw);
        },
      });
    };

    const pending = attach();

    return () => {
      cancelled = true;
      void pending.then((handle) => handle?.close());
    };
  }, [runId, open, loadHistory, appendEvent, setConnection]);
}
