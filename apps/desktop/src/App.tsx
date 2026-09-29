import type {
  ApprovalResponse,
  BudgetResponse,
  SettingsResponse,
  VerifyResponse,
} from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentsView } from "./components/AgentsView";
import { AutomationsView } from "./components/AutomationsView";
import { BudgetMeter } from "./components/BudgetMeter";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { type BlockerKind, HomeView } from "./components/HomeView";
import { KnowledgeView } from "./components/KnowledgeView";
import { Rail, type Section } from "./components/Rail";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { SpaceSettingsView } from "./components/SpaceSettingsView";
import { StartupScreen } from "./components/StartupScreen";
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
 * Application shell: left rail, current section, and workspace-wide header for
 * monthly spend, selected provider/model, and pending approvals.
 *
 * Verify sidecar reachability, own window-selected space and related lists, and
 * refresh on unfinished runs, visibility return, or run start/finish.
 */

/** Refresh interval while listed runs remain unfinished. */
const BACKGROUND_REFRESH_MS = 5_000;

/** Slower check while nothing listed is going: a scheduled run can start, or
    ask a question, with nobody touching the window. */
const IDLE_REFRESH_MS = 30_000;

/** How long the start screen waits on the first settings and spaces reads
    once the engine answers; past it the window opens and they finish there. */
const FIRST_LOAD_PATIENCE_MS = 10_000;

export function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "connecting", attempt: 0 });
  const [section, setSection] = useState<Section>("home");
  const [budget, setBudget] = useState<BudgetResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  // The start screen's middle stage: the first settings read has settled.
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [verified, setVerified] = useState<VerifyResponse | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalResponse[]>([]);
  // Retain open run across section changes and external open requests.
  const [runId, setRunId] = useState<string | null>(null);
  // Vault-open request; nonce distinguishes repeated paths.
  const [noteRequest, setNoteRequest] = useState<{
    path: string;
    heading: string | null;
    nonce: number;
    inbox?: boolean;
  } | null>(null);
  // Bump after a run changes memory status to reload vault inbox.
  const [memoryNonce, setMemoryNonce] = useState(0);
  // A goal Home asked Automations to repeat; the nonce reopens the editor.
  const [scheduleDraft, setScheduleDraft] = useState<{ goal: string; nonce: number } | null>(null);
  // Schedules changed in Home or Automations. Every section stays mounted, so
  // both reread their lists when it moves rather than showing a stale one.
  const [schedulesNonce, setSchedulesNonce] = useState(0);
  const schedulesChanged = useCallback(() => {
    setSchedulesNonce((current) => current + 1);
  }, []);
  // First-run tour follows the sidecar flag only when settings provides it.
  const [tourOpen, setTourOpen] = useState<boolean | null>(null);
  // Vault-reported inbox count for the rail badge.
  const [inboxCount, setInboxCount] = useState(0);
  // Post-startup transport failure leaves current window content underneath.
  const [lost, setLost] = useState<Exclude<SidecarStatus, { kind: "ready" }> | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  // Per-window, browser-persisted theme applied to the document root.
  useTheme();

  // Window-selected space.
  const spaces = useSpaces((state) => state.spaces);
  const spacesLoaded = useSpaces((state) => state.loaded);
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

  // Reconnect after post-startup failure; refresh all when `/health` recovers.
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

  // Include questions for runs outside the current view.
  const refreshApprovals = useCallback(() => {
    void api
      .listApprovals()
      .then((all) => {
        setPendingApprovals(all.filter((approval) => approval.status === "pending"));
      })
      .catch(() => undefined);
  }, []);

  const refreshWorkspace = useCallback(() => {
    // Meter and preflight follow the selected space.
    void api.getBudget(spaceId ?? undefined).then(setBudget).catch(() => undefined);
    void api
      .getSettings()
      .then(setSettings)
      .catch(() => undefined)
      .finally(() => {
        setSettingsLoaded(true);
      });
    void api.verifySettings(spaceId ?? undefined).then(setVerified).catch(() => undefined);
    refreshApprovals();
  }, [spaceId, refreshApprovals]);

  useEffect(() => {
    if (status.kind === "ready") refreshWorkspace();
  }, [status.kind, refreshWorkspace]);

  // Load spaces, then selected-space lists on every switch.
  useEffect(() => {
    if (status.kind === "ready") void loadSpaces();
  }, [status.kind, loadSpaces]);
  useEffect(() => {
    if (spaceId === null) return;
    setRunListSpace(spaceId);
    setRosterSpace(spaceId);
  }, [spaceId, setRunListSpace, setRosterSpace]);

  // Poll so background, scheduled or Discord runs appear: often while a listed
  // run is going, and slowly otherwise, reading only runs and questions.
  const runs = useRunList((state) => state.runs);
  const reloadRuns = useRunList((state) => state.load);
  const anyUnfinished = runs.some(unfinished);
  useEffect(() => {
    if (status.kind !== "ready") return;
    const timer = setInterval(
      () => {
        void reloadRuns();
        if (anyUnfinished) refreshWorkspace();
        else refreshApprovals();
        // A scheduled stage may have fired: its next time and outcome moved.
        schedulesChanged();
      },
      anyUnfinished ? BACKGROUND_REFRESH_MS : IDLE_REFRESH_MS,
    );
    return () => {
      clearInterval(timer);
    };
  }, [status.kind, anyUnfinished, reloadRuns, refreshWorkspace, refreshApprovals, schedulesChanged]);

  // A question waiting on someone is counted in the document title. That
  // shows in a browser tab; the packaged Tauri window keeps its configured
  // title unless the shell forwards title changes, which it does not yet.
  const waitingCount = pendingApprovals.length;
  useEffect(() => {
    document.title = waitingCount > 0 ? `(${String(waitingCount)}) AgentBase` : "AgentBase";
  }, [waitingCount]);

  // Refresh when the window regains visibility.
  useEffect(() => {
    if (status.kind !== "ready") return;
    const onVisible = () => {
      if (!document.hidden) {
        void reloadRuns();
        refreshWorkspace();
        schedulesChanged();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [status.kind, reloadRuns, refreshWorkspace, schedulesChanged]);

  // Prefer open-run log status over lagging table row.
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

  // Switch to a run's space before opening it because pickers are space-scoped.
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
      // Open run belongs to its start space, and so does a goal to repeat.
      setRunId(null);
      setInboxCount(0);
      setScheduleDraft(null);
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

  const automate = useCallback((goal: string) => {
    setScheduleDraft((current) => ({ goal, nonce: (current?.nonce ?? 0) + 1 }));
    setSection("automations");
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

  // Persist icon-only rail; narrow windows force a drawer over content.
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

  // Ctrl/Cmd+digit selects rail section; Ctrl/Cmd+B folds; Escape closes drawer.
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

  // Selected space's effective provider and model.
  const effectiveProvider = space?.provider ?? settings?.settings.provider ?? null;
  const effectiveModel = space?.model ?? settings?.settings.model ?? null;

  // Current start refusal or null; Home displays it and disables Start.
  const blocker =
    verified !== null && !verified.ok
      ? (verified.reason ?? "The current settings cannot build a provider.")
      : budget !== null && budget.percent_used >= 100
        ? `This month's cap of ${budget.cap_display} is reached, so further runs are refused.`
        : null;
  // A model the account cannot use is fixed in Space settings, where the
  // space's model is chosen; everything else in app Settings.
  const blockerKind: BlockerKind =
    verified !== null && !verified.ok
      ? (verified.suggested_model ?? null) !== null
        ? "space"
        : "setup"
      : "cap";

  // The start screen stays until the first screen has what it is drawn from,
  // so the window does not open half-filled; then it never comes back.
  const [opened, setOpened] = useState(false);
  const [impatient, setImpatient] = useState(false);
  useEffect(() => {
    if (status.kind !== "ready") return undefined;
    const timer = window.setTimeout(() => {
      setImpatient(true);
    }, FIRST_LOAD_PATIENCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [status.kind]);
  if (!opened && status.kind === "ready" && ((settingsLoaded && spacesLoaded) || impatient)) {
    setOpened(true);
  }

  if (status.kind !== "ready" || !opened) {
    return (
      <StartupScreen status={status} settingsLoaded={settingsLoaded} spacesLoaded={spacesLoaded} onRetry={connect} />
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
              "Lost touch with AgentBase's engine. Reconnecting…"}
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
            {section === "automations" && "Automations"}
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
              // Show remediation, not just failure.
              <button
                type="button"
                className="app__setup"
                title={verified.reason ?? "Tasks cannot start until setup is finished."}
                onClick={() => {
                  setSection(blockerKind === "space" ? "space" : "settings");
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
            <BudgetMeter
              budget={budget}
              spaceName={space?.name ?? null}
              runLimitMicros={space?.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null}
              onOpenUsage={() => {
                setSection("usage");
              }}
              onOpenSettings={() => {
                setSection("settings");
                // The section is shown on the next frame; then go to its limits.
                requestAnimationFrame(() => {
                  document.getElementById("settings-budget")?.scrollIntoView({ block: "start" });
                });
              }}
            />
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
                blockerKind={blockerKind}
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
                onOpenSpaceSettings={() => {
                  setSection("space");
                }}
                onOpenNote={openNote}
                onWorkspaceChanged={refreshWorkspace}
                runCapMicros={space?.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null}
                onOpenAutomations={() => {
                  setSection("automations");
                }}
                onAutomate={automate}
                schedulesNonce={schedulesNonce}
                onSchedulesChanged={schedulesChanged}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "automations"}>
            <ErrorBoundary label="the automations section">
              {space === null ? (
                <p className="runs-view__placeholder">Loading the space…</p>
              ) : (
                <AutomationsView
                  key={space.id}
                  space={space}
                  settings={settings}
                  onOpenRun={openRun}
                  draftRequest={scheduleDraft}
                  schedulesNonce={schedulesNonce}
                  onSchedulesChanged={schedulesChanged}
                />
              )}
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
                  active={section === "space"}
                  onOpenAutomations={() => {
                    setSection("automations");
                  }}
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
                  // Save replies with the full settings document.
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
