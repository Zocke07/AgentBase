import type {
  AlertsResponse,
  ApprovalResponse,
  BudgetResponse,
  NoteSummary,
  SettingsResponse,
  VerifyResponse,
} from "@agentbase/schemas";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentsView } from "./components/AgentsView";
import { AutomationsView } from "./components/AutomationsView";
import { CommandPalette } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { type BlockerKind, HomeView } from "./components/HomeView";
import { KnowledgeView } from "./components/KnowledgeView";
import { Rail, type Section } from "./components/Rail";
import { RunsView } from "./components/RunsView";
import { SettingsView } from "./components/SettingsView";
import { Skeleton } from "./components/Skeleton";
import { SpaceSettingsView } from "./components/SpaceSettingsView";
import { StartupScreen } from "./components/StartupScreen";
import { Toolbar } from "./components/Toolbar";
import { Tour } from "./components/Tour";
import { UsageView } from "./components/UsageView";
import * as api from "./lib/api";
import { modelLabel, providerLabel } from "./lib/format";
import { notifyDesktop } from "./lib/notify";
import { paletteCommands, type PaletteActions } from "./lib/palette";
import { SECTION_LABEL, SECTION_ORDER } from "./lib/sections";
import { matchesKeys, SHORTCUTS, shouldIgnoreKey } from "./lib/shortcuts";
import { connectWithRetry, type SidecarStatus } from "./lib/sidecar";
import { useTheme, useThemeStore } from "./lib/theme";
import { useTransparency } from "./lib/transparency";
import { moveWithTransition } from "./lib/viewTransition";
import { pendingNotices, readRaised, writeRaised } from "./state/alerts";
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

/** The shortcuts that work wherever focus is. */
const WINDOW_SHORTCUTS = SHORTCUTS.filter((entry) => entry.scope === "window");

/** Bring a card into view once its section shows, and put focus on it. */
function revealCard(testId: string): void {
  requestAnimationFrame(() => {
    const card = document.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
    if (card === null) return;
    card.scrollIntoView({ block: "start" });
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    card.focus({ preventScroll: true });
  });
}

export function App() {
  const [status, setStatus] = useState<SidecarStatus>({ kind: "connecting", attempt: 0 });
  const [section, showSection] = useState<Section>("home");
  // Every section change goes through one place, so it can cross-fade
  // (brief 5.3). The promise settles once the new section is in the document.
  // The section last asked for is kept on the document root, written when
  // it is asked for: a second change inside a transition, or one from a
  // callback made renders ago, compares with where the window is going,
  // not with a section a closure remembers.
  useEffect(() => {
    document.documentElement.dataset.section = section;
  }, [section]);
  const goTo = useCallback((next: Section): Promise<void> => {
    const root = document.documentElement;
    if (root.dataset.section === next) return Promise.resolve();
    root.dataset.section = next;
    return moveWithTransition(() => {
      showSection(next);
    });
  }, []);
  const setSection = useCallback(
    (next: Section) => {
      void goTo(next);
    },
    [goTo],
  );
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
    /** A data file for Agent files rather than a note. */
    file?: boolean;
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
  useTransparency();

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

  // Market alerts across spaces (Phase 18): the badge, Home's list, notices.
  const [alertList, setAlertList] = useState<AlertsResponse | null>(null);
  const refreshAlerts = useCallback(() => {
    void api
      .listAlerts()
      .then(setAlertList)
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
    refreshAlerts();
  }, [spaceId, refreshApprovals, refreshAlerts]);

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

  // A run that finished may have written files: Knowledge rereads its lists.
  const [outputsNonce, setOutputsNonce] = useState(0);
  const finishedRuns = runs
    .filter((run) => !unfinished(run))
    .map((run) => run.id)
    .join(",");
  const lastFinished = useRef<string | null>(null);
  useEffect(() => {
    if (lastFinished.current !== null && lastFinished.current !== finishedRuns) {
      setOutputsNonce((current) => current + 1);
    }
    lastFinished.current = finishedRuns;
  }, [finishedRuns]);
  useEffect(() => {
    if (status.kind !== "ready") return;
    const timer = setInterval(
      () => {
        void reloadRuns();
        if (anyUnfinished) refreshWorkspace();
        else {
          refreshApprovals();
          refreshAlerts();
        }
        // A scheduled stage may have fired: its next time and outcome moved.
        schedulesChanged();
      },
      anyUnfinished ? BACKGROUND_REFRESH_MS : IDLE_REFRESH_MS,
    );
    return () => {
      clearInterval(timer);
    };
  }, [status.kind, anyUnfinished, reloadRuns, refreshWorkspace, refreshApprovals, refreshAlerts, schedulesChanged]);

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

  // Each alert and each finished explanation raises one desktop notice per
  // window. A window's first look records what is already there instead of
  // replaying it, so opening the app is not a burst of old news.
  const desktopNotices = settings?.settings.alert_desktop_notifications !== false;
  useEffect(() => {
    if (alertList === null) return;
    const stored = readRaised();
    const pending = pendingNotices(alertList.alerts, stored ?? new Set());
    if (stored !== null && pending.length === 0) return;
    writeRaised([...(stored ?? []), ...pending.map((notice) => notice.key)]);
    if (stored === null || !desktopNotices) return;
    // A burst of checks shows its latest few; the rest are on Home.
    for (const notice of pending.slice(-3)) {
      void notifyDesktop(notice.title, notice.body).catch(() => undefined);
    }
  }, [alertList, desktopNotices]);

  // Home shows the space's alerts; looking at it marks them seen, and the ones
  // that were new stay marked for this visit.
  const spaceAlerts = (alertList?.alerts ?? []).filter((alert) => alert.space_id === spaceId);
  const unseenHere = spaceAlerts.filter((alert) => alert.seen_at === null);
  const unseenKey = unseenHere.map((alert) => alert.id).join(",");
  const [freshAlerts, setFreshAlerts] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    if (section !== "home" || spaceId === null || unseenKey === "") return;
    const ids = unseenKey.split(",");
    void api
      .markAlertsSeen(spaceId)
      .then(() => {
        setFreshAlerts((current) => new Set([...current, ...ids]));
        refreshAlerts();
      })
      .catch(() => undefined);
  }, [section, spaceId, unseenKey, refreshAlerts]);

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
  }, [setSection]);

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
      setFreshAlerts(new Set());
    },
    [spaceId, selectSpace],
  );

  const openNote = useCallback((path: string, heading: string | null) => {
    setNoteRequest((current) => ({ path, heading, nonce: (current?.nonce ?? 0) + 1 }));
    setSection("knowledge");
  }, [setSection]);

  const openFile = useCallback((path: string) => {
    setNoteRequest((current) => ({ path, heading: null, nonce: (current?.nonce ?? 0) + 1, file: true }));
    setSection("knowledge");
  }, [setSection]);

  const openMemory = useCallback((path: string) => {
    setNoteRequest((current) => ({ path, heading: null, nonce: (current?.nonce ?? 0) + 1, inbox: true }));
    setSection("knowledge");
  }, [setSection]);

  const memoryChanged = useCallback(() => {
    setMemoryNonce((current) => current + 1);
  }, []);

  const automate = useCallback((goal: string) => {
    setScheduleDraft((current) => ({ goal, nonce: (current?.nonce ?? 0) + 1 }));
    setSection("automations");
  }, [setSection]);

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
  }, [setSection]);

  // The window's shortcuts, from the keyboard map: a section by its digit,
  // the sidebar, the palette and Settings. Escape closes the drawer.
  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    if (status.kind !== "ready") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && drawer) {
        setDrawerOpen(false);
        return;
      }
      const hit = WINDOW_SHORTCUTS.find((entry) => matchesKeys(event, entry.keys));
      // The shell is never hidden, so its shortcuts hold wherever focus was
      // left, a hidden section included; only a plain key yields to a field.
      if (hit === undefined || (hit.keys.mod !== true && shouldIgnoreKey(event.target, hit.keys))) return;
      event.preventDefault();
      if (hit.id === "palette") {
        setPaletteOpen((open) => !open);
        return;
      }
      setPaletteOpen(false);
      if (hit.id === "rail") toggleRail();
      else if (hit.id === "settings") setSection("settings");
      else {
        const target = SECTION_ORDER.find((candidate) => hit.id === `section-${candidate}`);
        if (target !== undefined) setSection(target);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [status.kind, drawer, toggleRail, setSection]);

  // The command palette's rows. Notes are read when it opens, as Knowledge
  // rereads its own lists on use; everything else is already in the window.
  const [agentRequest, setAgentRequest] = useState<{ id: string; nonce: number } | null>(null);
  const [createSpaceRequest, setCreateSpaceRequest] = useState(0);
  const [paletteNotes, setPaletteNotes] = useState<{
    spaceId: string;
    notes: readonly NoteSummary[];
    failed: boolean;
  } | null>(null);
  useEffect(() => {
    if (!paletteOpen || spaceId === null) return undefined;
    let current = true;
    void api
      .listKnowledge(spaceId)
      .then((index) => {
        if (current) setPaletteNotes({ spaceId, notes: index.notes, failed: false });
      })
      .catch(() => {
        if (current) setPaletteNotes({ spaceId, notes: [], failed: true });
      });
    return () => {
      current = false;
    };
  }, [paletteOpen, spaceId]);
  const agents = useRoster((state) => state.agents);
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);
  const notesRead = paletteNotes !== null && paletteNotes.spaceId === spaceId ? paletteNotes : null;
  const paletteStatus =
    spaceId === null
      ? undefined
      : notesRead === null
        ? "Still reading the notes…"
        : notesRead.failed
          ? "The notes could not be read, so none are listed."
          : undefined;
  // Each the same act as the control it stands for.
  const paletteActions = useMemo<PaletteActions>(
    () => ({
      section: setSection,
      startRun: () => {
        void goTo("home").then(() => {
          requestAnimationFrame(() => {
            document.getElementById("goal")?.focus();
          });
        });
      },
      schedule: () => {
        automate("");
      },
      newSpace: () => {
        if (narrow) setDrawerOpen(true);
        setCreateSpaceRequest((current) => current + 1);
      },
      toggleRail,
      theme: setTheme,
      tour: () => {
        setTourOpen(true);
      },
      portfolio: () => {
        void goTo("home").then(() => {
          revealCard("portfolio-editor");
        });
      },
      marketWatch: () => {
        void goTo("automations").then(() => {
          revealCard("market-watch");
        });
      },
      space: switchSpace,
      run: openRun,
      agent: (id) => {
        setSection("agents");
        setAgentRequest((current) => ({ id, nonce: (current?.nonce ?? 0) + 1 }));
      },
      note: (path) => {
        openNote(path, null);
      },
    }),
    [setSection, goTo, automate, narrow, toggleRail, setTheme, switchSpace, openRun, openNote],
  );
  // Built only while the palette is open, and again only when what it lists
  // changes: a live run re-renders the window on every event.
  const notes = notesRead?.notes;
  const commands = useMemo(
    () =>
      paletteOpen
        ? paletteCommands({
            spaces,
            currentSpaceId: spaceId,
            runs,
            agents,
            notes: notes ?? [],
            railOpen: !railCollapsed,
            theme,
            actions: paletteActions,
          })
        : [],
    [paletteOpen, spaces, spaceId, runs, agents, notes, railCollapsed, theme, paletteActions],
  );

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
        createSpaceRequest={createSpaceRequest}
        onSpaceCreated={(created) => {
          void loadSpaces().then(() => {
            switchSpace(created.id);
            setSection("home");
          });
        }}
        badges={{
          home: section === "home" ? 0 : unseenHere.length,
          runs: pendingApprovals.length,
          knowledge: inboxCount,
        }}
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

        <Toolbar
          title={section === "home" ? (space?.name ?? "Home") : SECTION_LABEL[section]}
          waiting={pendingApprovals.length}
          onOpenWaiting={() => {
            const first = pendingApprovals[0];
            if (first !== undefined) openRunWherever(first.run_id);
          }}
          setup={
            verified !== null && !verified.ok
              ? {
                  reason: verified.reason ?? "Tasks cannot start until setup is finished.",
                  onFinish: () => {
                    setSection(blockerKind === "space" ? "space" : "settings");
                  },
                }
              : null
          }
          model={
            effectiveProvider === null
              ? null
              : {
                  label: effectiveModel === null ? providerLabel(effectiveProvider) : modelLabel(effectiveModel),
                  title: `Tasks in this space use ${providerLabel(effectiveProvider)}'s ${effectiveModel ?? "model"}. An agent can use a model of its own.`,
                }
          }
          meter={{
            budget,
            spaceName: space?.name ?? null,
            runLimitMicros: space?.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null,
            onOpenUsage: () => {
              setSection("usage");
            },
            onOpenSettings: () => {
              // Once the section is drawn, go to its limits.
              void goTo("settings").then(() => {
                requestAnimationFrame(() => {
                  document.getElementById("settings-budget")?.scrollIntoView({ block: "start" });
                });
              });
            },
          }}
          onOpenPalette={() => {
            setPaletteOpen(true);
          }}
        />

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
                onPortfolioSaved={() => { setOutputsNonce((current) => current + 1); }}
                runCapMicros={space?.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null}
                onOpenAutomations={() => {
                  setSection("automations");
                }}
                onAutomate={automate}
                schedulesNonce={schedulesNonce}
                onSchedulesChanged={schedulesChanged}
                alerts={spaceAlerts}
                freshAlerts={freshAlerts}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "automations"}>
            <ErrorBoundary label="the automations section">
              {space === null ? (
                <Skeleton label="Loading the space" lines={4} title />
              ) : (
                <AutomationsView
                  key={space.id}
                  space={space}
                  settings={settings}
                  onOpenRun={openRun}
                  draftRequest={scheduleDraft}
                  schedulesNonce={schedulesNonce}
                  onSchedulesChanged={schedulesChanged}
                  onOpenFile={openFile}
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
                onOpenFile={openFile}
                onOpenMemory={openMemory}
                onMemoryChanged={memoryChanged}
                marketWatch={space?.is_default === true}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "agents"}>
            <ErrorBoundary label="the agents section">
              <AgentsView
                workspaceProvider={effectiveProvider}
                spaceId={spaceId}
                spaces={spaces}
                openRequest={agentRequest}
              />
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "knowledge"}>
            <ErrorBoundary label="the knowledge vault">
              {space === null ? (
                <Skeleton label="Loading the space" lines={4} title />
              ) : (
                <KnowledgeView
                  key={space.id}
                  space={space}
                  onOpenRun={openRun}
                  openRequest={noteRequest ?? undefined}
                  reloadNonce={memoryNonce}
                  active={section === "knowledge"}
                  refreshNonce={outputsNonce}
                  onInboxCount={setInboxCount}
                />
              )}
            </ErrorBoundary>
          </div>
          <div className="app__view" hidden={section !== "usage"}>
            <ErrorBoundary label="the usage section">
              <UsageView
                space={space}
                active={section === "usage"}
                ledgerMicros={budget?.spent_micros ?? null}
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
                <Skeleton label="Loading the space" lines={4} title />
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
      <CommandPalette
        open={paletteOpen}
        commands={commands}
        status={paletteStatus}
        onClose={() => {
          setPaletteOpen(false);
        }}
      />
      <Tour open={tourShowing} section={section} onSection={setSection} onClose={closeTour} onDemo={demoRun} />
    </div>
  );
}
