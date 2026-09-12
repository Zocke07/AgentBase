import type {
  ApprovalResponse,
  BudgetResponse,
  SettingsResponse,
  VerifyResponse,
} from "@agentspace/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentsView } from "./components/AgentsView";
import { BudgetMeter } from "./components/BudgetMeter";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { HomeView } from "./components/HomeView";
import { Rail, type Section } from "./components/Rail";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { SpaceSettingsView } from "./components/SpaceSettingsView";
import * as api from "./lib/api";
import { connectWithRetry, type SidecarStatus } from "./lib/sidecar";
import { useTheme } from "./lib/theme";
import { useRoster } from "./state/roster";
import { unfinished, useRunList } from "./state/runList";
import { useRunStore } from "./state/runStore";
import { currentSpace, useSpaces } from "./state/spaces";

/**
 * The shell: a rail of sections on the left, the section on the right, and a
 * header carrying what is true of the whole workspace rather than of one run:
 * the month's spend, the provider and model in use, and any approval
 * waiting anywhere.
 *
 * Its job is to establish that the sidecar is reachable, then hand over.
 * Nothing about a run is decided here: that is `RunsView` and, below it, the
 * reducer. What the shell does own is which space the window is looking at
 * (BUILD_SPEC §5 Phase 11) and the lists that follow from it (the space's
 * runs and its roster, in shared stores), and the moments they are re-read:
 * a light poll while any listed run is unfinished, the window becoming
 * visible again, and a run being started or finished. Switching spaces
 * re-keys both stores and closes the open run; the header's approval badge
 * opens the run it names in whatever space that run is in.
 *
 * The retry loop is inherited from the Phase 1 spike and still earns its place:
 * the webview is reliably ready before the frozen sidecar has finished unpacking
 * itself and binding a port, so the first request legitimately fails on almost
 * every cold start.
 */

/** How often to re-read the run list and the meter while some run is unfinished. */
const BACKGROUND_REFRESH_MS = 5_000;

export function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "connecting", attempt: 0 });
  const [section, setSection] = useState<Section>("home");
  const [budget, setBudget] = useState<BudgetResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [verified, setVerified] = useState<VerifyResponse | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalResponse[]>([]);
  // Which run is open. Held here rather than in the runs section so that it
  // survives a section switch, and so the header's "approval waiting" badge
  // and the Home screen's cards can open a run from anywhere.
  const [runId, setRunId] = useState<string | null>(null);
  // Set when a request failed to reach the sidecar after startup; cleared when
  // the reconnect loop gets an answer again. The window stays where it was
  // underneath: a run being watched is still worth watching.
  const [lost, setLost] = useState<Exclude<SidecarStatus, { kind: "ready" }> | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  // The theme is a fact about this window, applied to the document root and
  // remembered in this browser; the settings page offers the choice.
  useTheme();

  // Which space the window is looking at, also a fact about this window.
  const spaces = useSpaces((state) => state.spaces);
  const spaceId = useSpaces((state) => state.currentId);
  const loadSpaces = useSpaces((state) => state.load);
  const selectSpace = useSpaces((state) => state.select);
  const space = useSpaces(currentSpace);
  const setRunListSpace = useRunList((state) => state.setSpace);
  const setRosterSpace = useRoster((state) => state.setSpace);

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

  // Losing the sidecar after startup. Any request that fails to connect puts
  // the shell back into its reconnect loop, reported in a banner rather than
  // by replacing the window; when `/health` answers again everything is
  // re-read.
  const reconnecting = useRef(false);
  useEffect(
    () =>
      api.onTransportFailure(() => {
        if (reconnecting.current) return;
        reconnecting.current = true;
        inFlight.current?.abort();
        const controller = new AbortController();
        inFlight.current = controller;
        void connectWithRetry((next) => {
          if (next.kind === "ready") {
            reconnecting.current = false;
            setLost(null);
            setStatus(next);
          } else {
            setLost(next);
          }
        }, controller.signal);
      }),
    [],
  );

  const refreshWorkspace = useCallback(() => {
    // The meter and the pre-flight are about the space on screen: its share
    // of the month, and whether *its* effective settings can build a provider.
    void api.getBudget(spaceId ?? undefined).then(setBudget).catch(() => undefined);
    void api.getSettings().then(setSettings).catch(() => undefined);
    // The sidecar's own answer to "would a run be refused right now": the
    // same check a run fails on, without a model call.
    void api.verifySettings(spaceId ?? undefined).then(setVerified).catch(() => undefined);
    // Every question waiting anywhere. The run panel shows the selected
    // run's own; this is for the ones on runs the user is not looking at,
    // which used to sit unanswered until the deadline.
    void api
      .listApprovals()
      .then((all) => {
        setPendingApprovals(all.filter((approval) => approval.status === "pending"));
      })
      .catch(() => undefined);
  }, [spaceId]);

  useEffect(() => {
    if (status.kind === "ready") refreshWorkspace();
  }, [status.kind, refreshWorkspace]);

  // The spaces list, once the sidecar answers; then the two per-space lists
  // follow the chosen space, and follow it again on every switch.
  useEffect(() => {
    if (status.kind === "ready") void loadSpaces();
  }, [status.kind, loadSpaces]);
  useEffect(() => {
    if (spaceId === null) return;
    setRunListSpace(spaceId);
    setRosterSpace(spaceId);
  }, [spaceId, setRunListSpace, setRosterSpace]);

  // Runs that happen elsewhere. The stream covers the open run; a run started
  // from Discord, or left going in the background, only reaches the list -
  // and only moves the meter, if something re-reads the table. A light poll
  // while any listed run is unfinished, and nothing at all once they all are:
  // an idle window makes no requests.
  const runs = useRunList((state) => state.runs);
  const reloadRuns = useRunList((state) => state.load);
  const anyUnfinished = runs.some(unfinished);
  useEffect(() => {
    if (status.kind !== "ready" || !anyUnfinished) return;
    const timer = setInterval(() => {
      void reloadRuns();
      refreshWorkspace();
    }, BACKGROUND_REFRESH_MS);
    return () => {
      clearInterval(timer);
    };
  }, [status.kind, anyUnfinished, reloadRuns, refreshWorkspace]);

  // And when the window comes back into view: a setting changed from a browser
  // tab, or a run that ended while this window was behind something.
  useEffect(() => {
    if (status.kind !== "ready") return;
    const onVisible = () => {
      if (!document.hidden) {
        void reloadRuns();
        refreshWorkspace();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [status.kind, reloadRuns, refreshWorkspace]);

  // The open run's status as its log reports it, for the cards: the table's
  // row says "pending" for the whole of a live run.
  const loadedRunId = useRunStore((state) => state.runId);
  const headView = useRunStore((state) => state.headView);
  const liveStatus =
    runId !== null && loadedRunId === runId && headView.eventCount > 0
      ? { runId, status: headView.status }
      : null;

  const openRun = useCallback((id: string) => {
    setRunId(id);
    setSection("runs");
  }, []);

  // A run named from outside the space on screen (the header's approval
  // badge) is opened in its own space: the picker lists one space's runs,
  // and a panel showing a run the picker does not list would be a run with
  // no way back to it.
  const openRunWherever = useCallback(
    (id: string) => {
      const listed = useRunList.getState().runs.find((run) => run.id === id);
      if (listed !== undefined) {
        openRun(id);
        return;
      }
      void api
        .getRun(id)
        .then((run) => {
          selectSpace(run.space_id);
          openRun(id);
        })
        .catch(() => {
          openRun(id);
        });
    },
    [openRun, selectSpace],
  );

  const switchSpace = useCallback(
    (id: string) => {
      if (id === spaceId) return;
      selectSpace(id);
      // The open run belongs to the space it was started in; a switch
      // closes it rather than leaving a panel about somewhere else.
      setRunId(null);
    },
    [spaceId, selectSpace],
  );

  // The provider and model a run in this space would use: the space's own
  // choice where it made one, else the app-wide default.
  const effectiveProvider = space?.provider ?? settings?.settings.provider ?? null;
  const effectiveModel = space?.model ?? settings?.settings.model ?? null;

  // Why a run started now would be refused, or null. Shown on the Home screen
  // and disabling Start, the header already said "runs will be refused"
  // while the button stayed live, and every click added a dead `failed` row.
  const blocker =
    verified !== null && !verified.ok
      ? (verified.reason ?? "The current settings cannot build a provider.")
      : budget !== null && budget.percent_used >= 100
        ? `This month's cap of ${budget.cap_display} is reached, so further runs are refused.`
        : null;

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
      <Rail
        section={section}
        onSelect={setSection}
        spaces={spaces}
        currentSpaceId={spaceId}
        onSelectSpace={switchSpace}
        onSpaceCreated={(created) => {
          void loadSpaces().then(() => {
            switchSpace(created.id);
            setSection("home");
          });
        }}
      />

      <div className="app__main">
        {lost !== null && (
          <div className="app__lost" role="alert" data-testid="sidecar-lost">
            <span className="dot dot--bad" />
            {lost.kind === "connecting" && `Lost the sidecar: reconnecting (attempt ${String(lost.attempt)})`}
            {lost.kind === "failed" && `Lost the sidecar at ${lost.baseUrl}: ${lost.message}`}
            {lost.kind === "failed" && (
              <button
                type="button"
                className="button button--small"
                onClick={() => {
                  reconnecting.current = false;
                  setLost({ kind: "connecting", attempt: 0 });
                  api.onTransportFailure(() => undefined)();
                  connect();
                }}
              >
                Retry
              </button>
            )}
          </div>
        )}

        <header className="app__header">
          <h1 className="app__title">
            {section === "home" && (space?.name ?? "Home")}
            {section === "runs" && "Runs"}
            {section === "agents" && "Agents"}
            {section === "space" && "Space settings"}
            {section === "settings" && "Settings"}
          </h1>

          <div className="app__workspace">
            {pendingApprovals.length > 0 && (
              <button
                type="button"
                className="app__waiting"
                onClick={() => {
                  const first = pendingApprovals[0];
                  if (first === undefined) return;
                  openRunWherever(first.run_id);
                }}
              >
                {pendingApprovals.length} approval{pendingApprovals.length === 1 ? "" : "s"} waiting
              </button>
            )}
            {effectiveProvider !== null && (
              <span
                className="app__provider"
                title="What a run in this space uses; a definition may pin its own"
                data-testid="header-model"
              >
                {effectiveProvider} · {effectiveModel}
                {verified !== null && !verified.ok && (
                  <span className="app__unpriced" role="alert">
                    runs will be refused
                  </span>
                )}
              </span>
            )}
            <BudgetMeter budget={budget} />
          </div>
        </header>

        <div className="app__body">
          {/* Every section stays mounted. Unmounting the runs section closed
              its stream and forgot which run was open, so a visit to another
              meant re-picking the run and re-downloading its whole log, and
              any approval that arrived meanwhile went unseen until it
              expired. Each has its own boundary, because all four are
              mounted at once and one failing to render used to take the rest
              down. */}
          <div className="app__view" hidden={section !== "home"}>
            <ErrorBoundary label="the Home screen">
              <HomeView
                space={space}
                blocker={blocker}
                pendingApprovals={pendingApprovals}
                liveStatus={liveStatus}
                onOpenRun={openRun}
                onOpenRuns={() => {
                  setSection("runs");
                }}
                onOpenAgents={() => {
                  setSection("agents");
                }}
                onOpenSettings={() => {
                  setSection("settings");
                }}
                onWorkspaceChanged={refreshWorkspace}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "runs"}>
            <ErrorBoundary label="the runs section">
              <RunsView
                onRunChanged={refreshWorkspace}
                pendingApprovals={pendingApprovals}
                runId={runId}
                onSelectRun={setRunId}
                onNewRun={() => {
                  setSection("home");
                }}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "agents"}>
            <ErrorBoundary label="the agents section">
              <AgentsView
                workspaceProvider={effectiveProvider}
                spaceId={spaceId}
                spaces={spaces}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "space"}>
            <ErrorBoundary label="the space settings">
              {space === null ? (
                <p className="runs-view__placeholder">Loading the space…</p>
              ) : (
                <SpaceSettingsView
                  space={space}
                  settings={settings}
                  onChanged={(changed) => {
                    void loadSpaces().then(() => {
                      if (changed === null) setSection("home");
                      refreshWorkspace();
                    });
                  }}
                />
              )}
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "settings"}>
            <ErrorBoundary label="the settings page">
              <SettingsView
                spaces={spaces}
                onSaved={(reply) => {
                  // The reply is the whole settings document; the header and the
                  // pre-flight follow it without waiting for the next poll.
                  setSettings(reply);
                  refreshWorkspace();
                }}
              />
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </div>
  );
}
