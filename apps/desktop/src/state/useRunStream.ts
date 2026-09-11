import { useEffect } from "react";

import { baseUrl, getRunHistory } from "../lib/api";
import { streamRun } from "../lib/events";

import { useRunStore } from "./runStore";

/**
 * Attach the run store to one run's SSE stream.
 *
 * The whole hook is a pipe: events go from the stream into `appendEvents` and
 * nowhere else. Nothing here interprets an event, and nothing here writes run
 * state directly — that is the reducer's job, and a second writer would be the
 * ad-hoc message §2 forbids.
 *
 * **History is fetched first, then the stream attaches.** The subscription
 * replays the whole log anyway, so this is not about completeness; it is about a
 * finished run rendering immediately instead of after a round trip that ends in
 * an instant close. The store's duplicate handling makes the overlap free.
 *
 * **Frames are handed over once per animation frame, not once each.** Every
 * `llm.token` is its own SSE frame and its own task, and every store update is
 * a render — the summary, the graph and a full pass over the log. A model that
 * streams a few hundred tokens a second was a few hundred renders a second.
 * Buffering to the next paint makes a burst one update, and changes nothing
 * about the fold: `appendEvents` is `appendEvent` called less.
 */
export function useRunStream(runId: string | null): void {
  const open = useRunStore((state) => state.open);
  const loadHistory = useRunStore((state) => state.loadHistory);
  const appendEvents = useRunStore((state) => state.appendEvents);
  const setConnection = useRunStore((state) => state.setConnection);

  useEffect(() => {
    if (runId === null) return;

    let cancelled = false;
    open(runId);

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

      try {
        const history = await getRunHistory(runId);
        if (cancelled) return null;
        if (history.length > 0) loadHistory(history);
      } catch {
        // A history fetch that fails is not fatal: the stream carries the same
        // events. Reporting it would put an error on screen for a run that is
        // about to render correctly anyway.
      }

      if (cancelled) return null;

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
      if (scheduled !== null) cancelAnimationFrame(scheduled);
      buffered = [];
      void pending.then((handle) => handle?.close());
    };
  }, [runId, open, loadHistory, appendEvents, setConnection]);
}
