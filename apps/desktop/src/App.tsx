import type { BudgetResponse, SettingsResponse } from "@agentspace/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentsView } from "./components/AgentsView";
import { BudgetMeter } from "./components/BudgetMeter";
import { RunsView } from "./components/RunsView";
import * as api from "./lib/api";
import { connectWithRetry, type SidecarStatus } from "./lib/sidecar";


/**
 * The dashboard shell.
 *
 * Its whole job is to establish that the sidecar is reachable, then hand over to
 * one of two tabs. Nothing about a run is decided here — that is `RunsView` and,
 * below it, the reducer.
 *
 * The retry loop is inherited from the Phase 1 spike and still earns its place:
 * the webview is reliably ready before the frozen sidecar has finished unpacking
 * itself and binding a port, so the first request legitimately fails on almost
 * every cold start.
 */

type Tab = "runs" | "agents";

export function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "connecting", attempt: 0 });
  const [tab, setTab] = useState<Tab>("runs");
  const [budget, setBudget] = useState<BudgetResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
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

  const refreshWorkspace = useCallback(() => {
    void api.getBudget().then(setBudget).catch(() => undefined);
    void api.getSettings().then(setSettings).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (status.kind === "ready") refreshWorkspace();
  }, [status.kind, refreshWorkspace]);

  if (status.kind !== "ready") {
    return (
      <main className="shell shell--waiting">
        <h1 className="shell__title">AgentSpace</h1>

        {status.kind === "connecting" && (
          <p className="shell__status">
            <span className="dot dot--pending" /> Connecting to the sidecar (attempt{" "}
            {status.attempt})
          </p>
        )}

        {status.kind === "failed" && (
          <>
            <p className="shell__status">
              <span className="dot dot--bad" /> Sidecar unreachable at <code>{status.baseUrl}</code>
            </p>
            <p className="shell__detail">{status.message}</p>
            <button className="button" type="button" onClick={connect}>
              Retry
            </button>
          </>
        )}
      </main>
    );
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">AgentSpace</h1>

        <nav className="tabs" aria-label="Sections">
          <button
            type="button"
            className={`tab${tab === "runs" ? " tab--active" : ""}`}
            aria-current={tab === "runs" ? "page" : undefined}
            onClick={() => {
              setTab("runs");
            }}
          >
            Runs
          </button>
          <button
            type="button"
            className={`tab${tab === "agents" ? " tab--active" : ""}`}
            aria-current={tab === "agents" ? "page" : undefined}
            onClick={() => {
              setTab("agents");
            }}
          >
            Agents
          </button>
        </nav>

        <div className="app__workspace">
          {settings !== null && (
            <span className="app__provider" title="The workspace default; a definition may pin its own">
              {settings.settings.provider} · {settings.settings.model}
              {!settings.model_is_priced && (
                <span className="app__unpriced" role="alert">
                  unpriced — runs will be refused
                </span>
              )}
            </span>
          )}
          <BudgetMeter budget={budget} />
        </div>
      </header>

      <div className="app__body">
        {/* Both tabs stay mounted. Unmounting the runs tab closed its stream
            and forgot which run was open, so a visit to the agents tab meant
            re-picking the run and re-downloading its whole log — and any
            approval that arrived meanwhile went unseen until it expired. */}
        <div className="app__view" hidden={tab !== "runs"}>
          <RunsView onRunChanged={refreshWorkspace} />
        </div>
        <div className="app__view" hidden={tab !== "agents"}>
          <AgentsView />
        </div>
      </div>
    </div>
  );
}
