import { useEffect, useMemo, useState } from "react";

import { RunPanel } from "../components/RunPanel";
import { reduceAll } from "../state/reducer";
import type { Scenario } from "../test/scenarios";

/**
 * One scenario's run view, with the two ways a run reaches the screen:
 *
 * - **Replay**: the whole log is there and the cursor stands somewhere in it,
 *   as when a finished run is opened and scrubbed.
 * - **Live**: only the events up to the cursor exist yet, and the view is at
 *   their end, as when a run is watched while it happens.
 *
 * At the same cursor the run projection is the same either way; that is the
 * guarantee `replayIdentity.test.tsx` holds. Playback steps the cursor one
 * event at a time on a timer, which is transport: nothing inside the run
 * view reads a clock.
 */

export type PlayerMode = "replay" | "live";

const SPEEDS = [1, 2, 4, 8] as const;
/** One event every 600 ms at 1x: slow enough to read each step. */
const STEP_MS = 600;

export interface ScenarioPlayerProps {
  scenario: Scenario;
  /** Where to stand at first; the end of the log when omitted. */
  cursor?: number;
  mode?: PlayerMode;
  /** Told where the cursor stands whenever it moves, so a link can hold it. */
  onCursor?: (cursor: number) => void;
  /** Which drawing of the run the page is about; the diagram when omitted. */
  canvas?: "office" | "diagram";
}

export function ScenarioPlayer({
  scenario,
  cursor: startCursor,
  mode: startMode = "replay",
  onCursor,
  canvas = "diagram",
}: ScenarioPlayerProps) {
  const { events } = scenario;
  const clamp = (value: number) => Math.min(events.length, Math.max(0, Math.round(value)));

  const [cursor, setCursor] = useState(() => clamp(startCursor ?? events.length));
  const [mode, setMode] = useState<PlayerMode>(startMode);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const atEnd = cursor >= events.length;
  useEffect(() => {
    if (!playing || atEnd) return undefined;
    const timer = window.setInterval(() => {
      setCursor((current) => Math.min(events.length, current + 1));
    }, STEP_MS / speed);
    return () => {
      window.clearInterval(timer);
    };
  }, [playing, atEnd, speed, events.length]);

  useEffect(() => {
    onCursor?.(cursor);
  }, [cursor, onCursor]);

  const prefix = useMemo(() => events.slice(0, cursor), [events, cursor]);
  const view = useMemo(() => reduceAll(prefix), [prefix]);
  const finished = view.status === "completed" || view.status === "failed" || view.status === "cancelled";

  return (
    <div className="wb-player">
      <div className="wb-player__bar" role="group" aria-label="Playback">
        <button
          type="button"
          className="button button--small"
          onClick={() => {
            // Play from the start when the log has already run out.
            if (atEnd) setCursor(0);
            setPlaying(!playing || atEnd);
          }}
        >
          {playing && !atEnd ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          className="button button--small"
          disabled={cursor === 0}
          onClick={() => {
            setPlaying(false);
            setCursor(clamp(cursor - 1));
          }}
        >
          Step back
        </button>
        <button
          type="button"
          className="button button--small"
          disabled={atEnd}
          onClick={() => {
            setPlaying(false);
            setCursor(clamp(cursor + 1));
          }}
        >
          Step
        </button>
        <label className="wb-player__field">
          <span>Speed</span>
          <select
            value={speed}
            onChange={(event) => {
              setSpeed(SPEEDS.find((candidate) => candidate === Number(event.target.value)) ?? 1);
            }}
          >
            {SPEEDS.map((candidate) => (
              <option key={candidate} value={candidate}>
                {candidate}x
              </option>
            ))}
          </select>
        </label>
        <label className="wb-player__field wb-player__field--wide">
          <span>Cursor</span>
          <input
            type="range"
            min={0}
            max={events.length}
            value={cursor}
            aria-valuetext={`Event ${String(cursor)} of ${String(events.length)}`}
            onChange={(event) => {
              setPlaying(false);
              setCursor(clamp(Number(event.target.value)));
            }}
          />
          <output className="wb-player__count">
            {cursor} / {events.length}
          </output>
        </label>
        <label className="wb-player__field">
          <span>Arrives as</span>
          <select
            value={mode}
            onChange={(event) => {
              setMode(event.target.value === "live" ? "live" : "replay");
            }}
          >
            <option value="replay">Replay</option>
            <option value="live">Live</option>
          </select>
        </label>
      </div>

      <div className="wb-player__stage" data-testid="wb-stage">
        <RunPanel
          view={view}
          events={mode === "live" ? prefix : events}
          cursor={cursor}
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
          onCursorChange={(next) => {
            setPlaying(false);
            setCursor(clamp(next));
          }}
          // As the runs view decides it: a question can be answered only at
          // the head of a run that is still going.
          approvalReadOnly={finished ? "finished" : mode === "live" || atEnd ? null : "replay"}
          // The workbench has no sidecar: an answer goes nowhere.
          onResolveApproval={() => Promise.resolve()}
          canvas={canvas}
        />
      </div>
    </div>
  );
}
