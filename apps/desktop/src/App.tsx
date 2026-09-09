import { useCallback, useEffect, useRef, useState } from "react";

import { connectWithRetry, type SidecarStatus } from "./lib/sidecar";

/**
 * Application shell.
 *
 * Phase 1 is the packaging spike, so this page exists to prove one thing: a
 * React view inside the Tauri webview can reach the PyInstaller sidecar that
 * the Rust shell spawned. The live run graph arrives in Phase 7.
 */
export function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "connecting", attempt: 0 });
  const inFlight = useRef<AbortController | null>(null);

  const connect = useCallback(() => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    void connectWithRetry(setStatus, controller.signal);
  }, []);

  useEffect(() => {
    connect();
    return () => {
      inFlight.current?.abort();
    };
  }, [connect]);

  return (
    <main className="shell">
      <h1 className="shell__title">AgentSpace</h1>
      <p className="shell__phase">Phase 1 — packaging spike</p>

      <section className="card" aria-live="polite">
        {status.kind === "connecting" && (
          <>
            <span className="dot dot--pending" />
            <span>
              Connecting to sidecar<span className="ellipsis" /> (attempt {status.attempt})
            </span>
          </>
        )}

        {status.kind === "ready" && (
          <>
            <span className="dot dot--ok" />
            <span>
              Sidecar responded <code>{JSON.stringify(status.health)}</code>
            </span>
          </>
        )}

        {status.kind === "failed" && (
          <>
            <span className="dot dot--bad" />
            <span>
              Sidecar unreachable at <code>{status.baseUrl}</code>
              <br />
              <small>{status.message}</small>
            </span>
          </>
        )}
      </section>

      {status.kind === "ready" && <p className="shell__origin">{status.baseUrl}</p>}

      {status.kind === "failed" && (
        <button className="retry" type="button" onClick={connect}>
          Retry
        </button>
      )}
    </main>
  );
}
