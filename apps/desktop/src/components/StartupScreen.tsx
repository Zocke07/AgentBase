import { useEffect, useState } from "react";

import type { SidecarStatus } from "../lib/sidecar";

/**
 * The window before the app can show anything, as named stages rather than a
 * retry count. Every stage is something the window really waits on: the
 * engine answering `/health`, then the settings and the spaces the first
 * screen is drawn from. None is a timer dressed up as progress.
 */

export interface StartupScreenProps {
  status: SidecarStatus;
  /** First settings read settled, well or not. */
  settingsLoaded: boolean;
  /** First spaces read settled, well or not. */
  spacesLoaded: boolean;
  onRetry: () => void;
}

type StageState = "done" | "active" | "waiting" | "failed";

interface Stage {
  label: string;
  state: StageState;
  /** A second line under an active stage, when there is something to say. */
  detail: string | null;
}

/** How long the engine may take before the screen says a slow start is normal. */
const SLOW_START_MS = 6_000;

/** Words a screen reader says after each stage's label. */
const STATE_WORD: Record<StageState, string> = {
  done: "done",
  active: "in progress",
  waiting: "not started",
  failed: "failed",
};

export function StartupScreen({ status, settingsLoaded, spacesLoaded, onRetry }: StartupScreenProps) {
  const [slow, setSlow] = useState(false);
  const connecting = status.kind === "connecting";
  useEffect(() => {
    if (!connecting) return undefined;
    const timer = window.setTimeout(() => {
      setSlow(true);
    }, SLOW_START_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [connecting]);

  const engineUp = status.kind === "ready";
  const after = (loaded: boolean): StageState => (!engineUp ? "waiting" : loaded ? "done" : "active");
  const stages: Stage[] = [
    {
      label: "Starting the engine",
      state: engineUp ? "done" : status.kind === "failed" ? "failed" : "active",
      detail:
        status.kind === "connecting" && status.blocked === true
          ? "Waiting for an earlier AgentBase to finish closing."
          : status.kind === "connecting" && slow
            ? "The first start after installing or updating can take a minute or two."
            : null,
    },
    { label: "Checking your settings", state: after(settingsLoaded), detail: null },
    { label: "Loading your spaces", state: after(spacesLoaded), detail: null },
  ];
  const done = stages.filter((stage) => stage.state === "done").length;
  const current = stages.find((stage) => stage.state === "active" || stage.state === "failed");

  return (
    <main className="shell shell--waiting">
      <span className="shell__logo" aria-hidden="true" />
      <h1 className="shell__title">AgentBase</h1>

      <div
        className={`startup__bar${status.kind === "failed" ? " startup__bar--failed" : ""}`}
        role="progressbar"
        aria-label="Starting AgentBase"
        aria-valuemin={0}
        aria-valuemax={stages.length}
        aria-valuenow={done}
        aria-valuetext={current === undefined ? "Ready" : `${current.label}, ${String(done)} of ${String(stages.length)} done`}
      >
        <span className="startup__fill" style={{ width: `${String(((done + (current?.state === "active" ? 0.5 : 0)) / stages.length) * 100)}%` }} />
      </div>

      <ol className="startup__stages" data-testid="startup-stages">
        {stages.map((stage) => (
          <li key={stage.label} className={`startup__stage startup__stage--${stage.state}`}>
            <span className="startup__mark" aria-hidden="true">
              {stage.state === "active" ? <span className="spinner" /> : stage.state === "done" ? "✓" : stage.state === "failed" ? "✕" : ""}
            </span>
            <span className="startup__text">
              <span className="startup__label">
                {stage.label}
                <span className="sr-only">: {STATE_WORD[stage.state]}</span>
              </span>
              {stage.state === "active" && stage.detail !== null && (
                <span className="startup__detail">{stage.detail}</span>
              )}
            </span>
          </li>
        ))}
      </ol>

      {/* One polite announcement per stage, not per change in the list. */}
      <p className="sr-only" role="status">
        {current?.state === "active" ? `${current.label}…` : ""}
      </p>

      {status.kind === "failed" && (
        <>
          <p className="shell__status" role="alert">
            AgentBase could not start its engine.
          </p>
          <p className="shell__detail">
            Try again in a moment. If this keeps happening, quit AgentBase and open it again.
          </p>
          <details className="shell__technical">
            <summary>Technical details</summary>
            <p>
              No answer from <code>{status.baseUrl}</code>: {status.message}
            </p>
          </details>
          <button className="button button--primary" type="button" onClick={onRetry}>
            Try again
          </button>
        </>
      )}
    </main>
  );
}
