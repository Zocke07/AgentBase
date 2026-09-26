import type {
  ApprovalResponse,
  BudgetResponse,
  SettingsResponse,
  VerifyResponse,
} from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentsView } from "./components/AgentsView";
import { BudgetMeter } from "./components/BudgetMeter";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { HomeView } from "./components/HomeView";
import { KnowledgeView } from "./components/KnowledgeView";
import { Rail, type Section } from "./components/Rail";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { SpaceSettingsView } from "./components/SpaceSettingsView";
import { Tour } from "./components/Tour";
import { UsageView } from "./components/UsageView";
import { VisualizationView } from "./components/VisualizationView";
import * as api from "./lib/api";
import { modelLabel, providerLabel } from "./lib/format";
import { SECTION_ORDER } from "./lib/sections";
import { connectWithRetry, type SidecarStatus } from "./lib/sidecar";
import { useTheme } from "./lib/theme";
import { useRoster } from "./state/roster";
import { unfinished, useRunList } from "./state/runList";
import { useRunStore } from "./state/runStore";
import { currentSpace, useSpaces } from "./state/spaces";
import { useMediaQuery } from "./state/useMediaQuery";
import { useStoredFlag } from "./state/useStoredFlag";

/**
 * The shell: a rail of sections on the left, the section on the right, and a
 * header for what is true of the whole workspace (the month's spend, the
 * provider and model in use, any approval waiting anywhere).
 *
 * It establishes that the sidecar is reachable, then hands over. It owns
 * which space the window is looking at, the lists that follow from it, and
 * when they are re-read: a light poll while any listed run is unfinished, the
 * window becoming visible again, and a run starting or finishing.
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
  // Which run is open: held here so it survives a section switch and can be
  // opened from the header badge or the Home cards.
  const [runId, setRunId] = useState<string | null>(null);
  // A note another section asked the vault to open; the nonce makes a repeat
  // of the same path a new request.
  const [noteRequest, setNoteRequest] = useState<{
    path: string;
    heading: string | null;
    nonce: number;
    inbox?: boolean;
  } | null>(null);
  // Bumped when a run changes a memory's status, so the vault reloads its inbox.
  const [memoryNonce, setMemoryNonce] = useState(0);
  // The first-run tour. Null defers to the sidecar's flag, so it opens once
  // on the sidecar's word and only a settings document that carries the flag
  // (not an older sidecar, not a bare test fixture) can open it.
  const [tourOpen, setTourOpen] = useState<boolean | null>(null);
  // Memories waiting in the inbox, reported by the vault for the rail's badge.
  const [inboxCount, setInboxCount] = useState(0);
  // Set when a request failed to reach the sidecar after startup; the window
  // stays where it was underneath.
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

  // A failed connection after startup re-enters the reconnect loop, reported
  // in a banner; when `/health` answers again everything is re-read.
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
    // The meter and the pre-flight are about the space on screen.
    void api.getBudget(spaceId ?? undefined).then(setBudget).catch(() => undefined);
    void api.getSettings().then(setSettings).catch(() => undefined);
    void api.verifySettings(spaceId ?? undefined).then(setVerified).catch(() => undefined);
    // Every question waiting anywhere, including on runs not being looked at.
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

  // A run started from Discord or left going in the background only reaches
  // the list if something re-reads the table: a light poll while any listed
  // run is unfinished, and nothing once they all are.
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

  // And when the window comes back into view.
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

  // The open run's status as its log reports it; the table's row lags.
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

  // A run named from outside the space on screen is opened in its own space,
  // since the picker lists one space's runs.
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
      // The open run belongs to the space it was started in.
      setRunId(null);
      setInboxCount(0);
    },
    [spaceId, selectSpace],
  );

  const openNote = useCallback((path: string, heading: string | null) => {
    setNoteRequest((current) => ({ path, heading, nonce: (current?.nonce ?? 0) + 1 }));
    setSection("knowledge");
  }, []);

  const openMemory = useCallback((path: string) => {
    setNoteRequest((current) => ({ path, heading: null, nonce: (current?.nonce ?? 0) + 1, inbox: true }));
    setSection("knowledge");
  }, []);

  const memoryChanged = useCallback(() => {
    setMemoryNonce((current) => current + 1);
  }, []);

  const tourShowing = tourOpen ?? settings?.settings.onboarding_completed === false;

  const closeTour = useCallback(() => {
    setTourOpen(false);
    if (settings?.settings.onboarding_completed === true) return;
    void api
      .updateSettings({ onboarding_completed: true })
      .then(setSettings)
      .catch(() => undefined);
  }, [settings]);

  const demoRun = useCallback(async () => {
    const run = await api.startDebugRun();
    openRun(run.id);
  }, [openRun]);

  // The sidebar folds to icons on request, remembered in this browser. In a
  // narrow window it is folded regardless, and opens as a drawer over the
  // page rather than squeezing the section beside it.
  const [railFolded, setRailFolded] = useStoredFlag("rail.collapsed");
  const narrow = useMediaQuery("(max-width: 1100px)");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawer = narrow && drawerOpen;
  const railCollapsed = narrow ? !drawerOpen : railFolded;
  const toggleRail = useCallback(() => {
    if (narrow) setDrawerOpen((open) => !open);
    else setRailFolded(!railFolded);
  }, [narrow, railFolded, setRailFolded]);
  const choose = useCallback((next: Section) => {
    setSection(next);
    setDrawerOpen(false);
  }, []);

  // Ctrl/Cmd and a digit jumps to a section, in rail order; Ctrl/Cmd+B folds
  // the sidebar; Escape closes the drawer.
  useEffect(() => {
    if (status.kind !== "ready") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && drawer) {
        setDrawerOpen(false);
        return;
      }
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.key === "b" || event.key === "B") {
        event.preventDefault();
        toggleRail();
        return;
      }
      const digit = Number.parseInt(event.key, 10);
      if (Number.isNaN(digit)) return;
      const target = SECTION_ORDER[digit - 1];
      if (target === undefined) return;
      event.preventDefault();
      setSection(target);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [status.kind, drawer, toggleRail]);

  // The provider and model a run in this space would use.
  const effectiveProvider = space?.provider ?? settings?.settings.provider ?? null;
  const effectiveModel = space?.model ?? settings?.settings.model ?? null;

  // Why a run started now would be refused, or null. Shown on Home and disables Start.
  const blocker =
    verified !== null && !verified.ok
      ? (verified.reason ?? "The current settings cannot build a provider.")
      : budget !== null && budget.percent_used >= 100
        ? `This month's cap of ${budget.cap_display} is reached, so further runs are refused.`
        : null;

  if (status.kind !== "ready") {
    return (
      <main className="shell shell--waiting">
        <span className="shell__logo" aria-hidden="true" />
        <h1 className="shell__title">AgentBase</h1>

        {status.kind === "connecting" && (
          <p className="shell__status" role="status">
            <span className="spinner" aria-hidden="true" /> Starting up
            {status.attempt > 1 && ` (try ${String(status.attempt)})`}…
          </p>
        )}

        {status.kind === "failed" && (
          <>
            <p className="shell__status" role="alert">
              <span className="dot dot--bad" /> AgentBase could not start its engine.
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
            <button className="button button--primary" type="button" onClick={connect}>
              Try again
            </button>
          </>
        )}
      </main>
    );
  }

  return (
    <div className={`app${railCollapsed || drawer ? " app--rail-collapsed" : ""}${drawer ? " app--drawer" : ""}`}>
      {/* The first stop for Tab: past the sidebar, straight to the section. */}
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {drawer && (
        <div
          className="app__scrim"
          aria-hidden="true"
          onClick={() => {
            setDrawerOpen(false);
          }}
        />
      )}
      <Rail
        section={section}
        onSelect={choose}
        collapsed={railCollapsed}
        drawer={drawer}
        onToggleCollapsed={toggleRail}
        spaces={spaces}
        currentSpaceId={spaceId}
        onSelectSpace={switchSpace}
        onSpaceCreated={(created) => {
          void loadSpaces().then(() => {
            switchSpace(created.id);
            setSection("home");
          });
        }}
        badges={{ runs: pendingApprovals.length, knowledge: inboxCount }}
      />

      <div className="app__main">
        {lost !== null && (
          <div className="app__lost" role="alert" data-testid="sidecar-lost">
            {lost.kind === "connecting" ? <span className="spinner" aria-hidden="true" /> : <span className="dot dot--bad" />}
            {lost.kind === "connecting" &&
              `Lost touch with AgentBase's engine. Reconnecting (attempt ${String(lost.attempt)})…`}
            {lost.kind === "failed" && `AgentBase's engine stopped answering (${lost.message}).`}
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
                Try again
              </button>
            )}
          </div>
        )}

        <header className="app__header">
          <h1 className="app__title">
            {section === "home" && (space?.name ?? "Home")}
            {section === "runs" && "Runs"}
            {section === "agents" && "Agents"}
            {section === "knowledge" && "Knowledge"}
            {section === "visualize" && "Visualize"}
            {section === "usage" && "Usage"}
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
            {verified !== null && !verified.ok && (
              // Not red text that says what is wrong, but the way to fix it.
              <button
                type="button"
                className="app__setup"
                title={verified.reason ?? "Tasks cannot start until setup is finished."}
                onClick={() => {
                  setSection("settings");
                }}
              >
                Finish setup
              </button>
            )}
            {effectiveProvider !== null && (
              <span
                className="app__provider"
                title={`Tasks in this space use ${providerLabel(effectiveProvider)}'s ${effectiveModel ?? "model"}. An agent can use a model of its own.`}
                data-testid="header-model"
              >
                <span className="app__provider-dot" aria-hidden="true" />
                {effectiveModel === null ? providerLabel(effectiveProvider) : modelLabel(effectiveModel)}
              </span>
            )}
            <BudgetMeter budget={budget} />
          </div>
        </header>

        <main className="app__body" id="main-content" tabIndex={-1}>
          {/* Every section stays mounted, so the runs section keeps its stream
              across a visit elsewhere; each has its own boundary so one failing
              to render does not take the rest down. */}
          <div className="app__view" hidden={section !== "home"}>
            <ErrorBoundary label="the Home screen">
              <HomeView
                space={space}
                blocker={blocker}
                pendingApprovals={pendingApprovals}
                liveStatus={liveStatus}
                modelLabel={
                  effectiveProvider === null
                    ? null
                    : effectiveModel === null
                      ? providerLabel(effectiveProvider)
                      : modelLabel(effectiveModel)
                }
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
                onOpenNote={openNote}
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
                onOpenNote={openNote}
                onOpenMemory={openMemory}
                onMemoryChanged={memoryChanged}
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
          <div className="app__view" hidden={section !== "knowledge"}>
            <ErrorBoundary label="the knowledge vault">
              {space === null ? (
                <p className="runs-view__placeholder">Loading the space…</p>
              ) : (
                <KnowledgeView
                  key={space.id}
                  space={space}
                  onOpenRun={openRun}
                  openRequest={noteRequest ?? undefined}
                  reloadNonce={memoryNonce}
                  onInboxCount={setInboxCount}
                />
              )}
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "visualize"}>
            <ErrorBoundary label="the visualization workspace">
              <VisualizationView key={space?.id ?? "loading"} space={space} active={section === "visualize"} />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "usage"}>
            <ErrorBoundary label="the usage section">
              <UsageView
                space={space}
                active={section === "usage"}
                onOpenRun={openRunWherever}
                onOpenSettings={() => {
                  setSection("settings");
                }}
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
                  onOpenRun={openRun}
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
                  // The reply is the whole settings document.
                  setSettings(reply);
                  refreshWorkspace();
                }}
                onReplayTour={() => {
                  setTourOpen(true);
                }}
              />
            </ErrorBoundary>
          </div>
        </main>
      </div>
      <Tour open={tourShowing} section={section} onSection={setSection} onClose={closeTour} onDemo={demoRun} />
    </div>
  );
}
