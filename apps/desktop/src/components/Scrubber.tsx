import type { Event } from "@agentbase/schemas";
import { useEffect, useEffectEvent, useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";

import { currentPlatform } from "../lib/platform";
import { matchesKeys, shortcut, withShortcut } from "../lib/shortcuts";
import { nextNotable, notableEvents, PLAYBACK_SPEEDS, playbackDelay, previousNotable, type MarkerKind, type PlaybackSpeed } from "../state/timeline";

import { Status } from "./ui/Status";
import { IconButton } from "./ui/controls";

/**
 * The run's timeline (brief 7.10): where the cursor stands in the log, and
 * the ways to move it. Transport, never projection: nothing here is in what
 * the identity test compares, and playback may use timers.
 *
 * Playing moves the cursor one event at a time, so a replay steps through
 * the same motion the room showed live (decision D1). It stops at the end,
 * when the window is hidden, and when the viewer moves the cursor some
 * other way.
 */

export interface ScrubberProps {
  events: readonly Event[];
  cursor: number;
  onCursorChange: (cursor: number) => void;
  /** The previous run stays on screen, and still, while the next one loads. */
  loading: boolean;
  /** The run is still going and the cursor is at its latest event. */
  live: boolean;
}

/** What each mark on the track is, said before its sentence. */
const MARKER_WORD: Readonly<Record<MarkerKind, string>> = {
  handoff: "Work handed on",
  question: "A question",
  denial: "A refusal",
  error: "An error",
  file: "A file written",
  end: "The end",
};

export function Scrubber({ events, cursor, onCursorChange, loading, live }: ScrubberProps) {
  const total = events.length;
  const scrubbed = cursor < total;
  const atEnd = cursor >= total;
  const markers = useMemo(() => notableEvents(events), [events]);
  const previous = previousNotable(markers, cursor);
  const next = nextNotable(markers, cursor);
  const platform = currentPlatform();
  // Reserve counter width so scrubber track does not shift.
  const counterWidth = `${String(String(total).length * 2 + 3)}ch`;

  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const running = playing && !atEnd && !loading;

  // One event at a time, at the speed chosen; the last step ends playback.
  // The timer is set again only when the cursor or the speed moves: events
  // arriving from a live run while it plays must not keep putting it off.
  const delay = useEffectEvent(() => playbackDelay(events[cursor], speed));
  const advance = useEffectEvent(() => {
    if (cursor + 1 >= total) setPlaying(false);
    onCursorChange(cursor + 1);
  });
  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setTimeout(() => {
      advance();
    }, delay());
    return () => {
      window.clearTimeout(timer);
    };
  }, [running, cursor, speed]);

  // Nothing plays in a window nobody can see.
  useEffect(() => {
    const stop = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", stop);
    return () => {
      document.removeEventListener("visibilitychange", stop);
    };
  }, []);

  /** Any move the viewer makes by hand ends playback. */
  const go = (target: number) => {
    setPlaying(false);
    onCursorChange(Math.max(0, Math.min(total, target)));
  };
  const togglePlay = () => {
    if (running) {
      setPlaying(false);
      return;
    }
    // From the end, play the run again from its start.
    if (atEnd) onCursorChange(0);
    setPlaying(true);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    // The slider steps with the plain arrows itself; anywhere else in the
    // bar they step as the buttons' tooltips say.
    const slider = target instanceof HTMLInputElement && target.type === "range";
    if (!slider && matchesKeys(event, shortcut("timeline-back").keys)) {
      event.preventDefault();
      if (cursor > 0) go(cursor - 1);
    } else if (!slider && matchesKeys(event, shortcut("timeline-forward").keys)) {
      event.preventDefault();
      if (!atEnd) go(cursor + 1);
    } else if (matchesKeys(event, shortcut("timeline-previous").keys)) {
      event.preventDefault();
      if (previous !== null) go(previous);
    } else if (matchesKeys(event, shortcut("timeline-next").keys)) {
      event.preventDefault();
      if (next !== null) go(next);
    } else if (matchesKeys(event, shortcut("timeline-play").keys) && target.tagName !== "BUTTON") {
      // A focused button's own Space presses it; anywhere else in the bar it plays.
      event.preventDefault();
      togglePlay();
    }
  };

  return (
    <div className="scrubber" data-testid="scrubber" onKeyDown={onKeyDown}>
      <div className="scrubber__transport" role="group" aria-label="Playback">
        <IconButton
          icon={running ? "pause" : "play"}
          label={running ? "Pause" : "Play"}
          title={withShortcut(running ? "Pause" : atEnd ? "Play from the start" : "Play", "timeline-play", platform)}
          size={16}
          disabled={loading || total === 0 || (live && atEnd)}
          testId="timeline-play"
          onClick={togglePlay}
        />
        <IconButton
          icon="skip-back"
          label="Previous notable event"
          title={withShortcut("Previous notable event", "timeline-previous", platform)}
          size={16}
          disabled={loading || previous === null}
          onClick={() => {
            if (previous !== null) go(previous);
          }}
        />
        <IconButton
          icon="step-back"
          label="Step back"
          title={withShortcut("Step back", "timeline-back", platform)}
          size={16}
          disabled={loading || cursor === 0}
          onClick={() => {
            go(cursor - 1);
          }}
        />
        <IconButton
          icon="step-forward"
          label="Step forward"
          title={withShortcut("Step forward", "timeline-forward", platform)}
          size={16}
          disabled={loading || atEnd}
          onClick={() => {
            go(cursor + 1);
          }}
        />
        <IconButton
          icon="skip-forward"
          label="Next notable event"
          title={withShortcut("Next notable event", "timeline-next", platform)}
          size={16}
          disabled={loading || next === null}
          onClick={() => {
            if (next !== null) go(next);
          }}
        />
        <button
          type="button"
          className="scrubber__speed num"
          aria-label={`Playback speed ${String(speed)} times`}
          title="Playback speed: press for the next"
          data-testid="timeline-speed"
          disabled={loading}
          onClick={() => {
            const index = PLAYBACK_SPEEDS.indexOf(speed);
            setSpeed(PLAYBACK_SPEEDS[(index + 1) % PLAYBACK_SPEEDS.length] ?? 1);
          }}
        >
          {speed}×
        </button>
      </div>
      <label className="scrubber__control">
        <span className="scrubber__label">Replay</span>
        <span className="scrubber__track">
          <input
            type="range"
            min={0}
            max={total}
            value={cursor}
            disabled={loading}
            aria-label="Position in the event log"
            aria-valuetext={`Event ${String(cursor)} of ${String(total)}. ${scrubbed ? "Earlier point in this run." : "Latest event."}`}
            onChange={(changed) => {
              go(Number(changed.target.value));
            }}
          />
          {/* The notable events, each a mark that jumps there, for the
              pointer. The keyboard reaches them one by one with the buttons
              above, and a screen reader hears them in the log; named here
              they would be heard twice. */}
          {total > 0 && (
            <span className="scrubber__marks" data-testid="timeline-marks" aria-hidden="true">
              {markers.map((marker) => (
                <button
                  key={marker.seq}
                  type="button"
                  tabIndex={-1}
                  className={`scrubber__mark scrubber__mark--${marker.kind}`}
                  style={{ "--at": marker.cursor / total } as CSSProperties}
                  title={`${MARKER_WORD[marker.kind]}: ${marker.label}`}
                  disabled={loading}
                  onClick={() => {
                    go(marker.cursor);
                  }}
                />
              ))}
            </span>
          )}
        </span>
      </label>
      <span className="scrubber__position num" data-testid="scrub-position" style={{ minWidth: counterWidth }}>
        {cursor} / {total}
      </span>
      {/* Always rendered, fixed width. The range input shares this flex row
          and takes what is left of it: a slot that came and went with the
          scrub state changed the track's length under the pointer mid-drag. */}
      <span className="scrubber__state" data-testid="scrub-state">
        {scrubbed ? (
          <>
            <span className="scrubber__notice" data-testid="scrub-notice">
              Showing an earlier point in this run.
            </span>
            <button
              type="button"
              className="button button--small"
              disabled={loading}
              onClick={() => {
                go(total);
              }}
            >
              Jump to end
            </button>
          </>
        ) : (
          <>
            {live && (
              <Status kind="running" testId="timeline-live">
                Live
              </Status>
            )}
            <span className="scrubber__latest">Showing the latest event.</span>
          </>
        )}
      </span>
    </div>
  );
}
