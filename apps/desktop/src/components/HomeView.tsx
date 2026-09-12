import type { AgentDef, ApprovalResponse, Run, SpaceResponse } from "@agentspace/schemas";
import { useEffect, useState } from "react";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { unfinished, useRunList } from "../state/runList";

import { RunCard } from "./RunCard";

/**
 * The Home screen — BUILD_SPEC §5 Phase 11, what a person sees when nothing
 * is open.
 *
 * Top to bottom: what stands in the way of a run, if anything; the goal box;
 * **Now** — runs in progress and approvals waiting, each a card that opens
 * the run; **Recent runs** as cards; and the roster, with the toggle that
 * decides whether the supervisor may put an agent to work. A fresh install
 * with no runs gets the goal box as the whole screen, with one sentence about
 * the agents that are ready.
 *
 * Nothing here is about a *particular* run. Starting one hands its id to the
 * shell, which opens it in the Runs section where the fold renders it; the
 * cards are rows of the `runs` table, and the one run whose row the table has
 * not caught up with is told its status by the caller.
 *
 * The pre-flight — "why a run started now would be refused" — is the
 * sidecar's own answer, passed down from the shell. It disables Start rather
 * than letting the click add a dead `failed` row to the list, and offers the
 * two ways out: the settings, or the scripted demo run that needs no key.
 */

export interface HomeViewProps {
  /** The space this screen is about; null until the list has loaded. */
  space: SpaceResponse | null;
  /** Why a run started now would be refused, or null when one can start. */
  blocker: string | null;
  /** Every approval waiting anywhere, so a card can say its run is stuck on one. */
  pendingApprovals: readonly ApprovalResponse[];
  /** What the open run's log says its status is, when the table lags it. */
  liveStatus: { runId: string; status: Run["status"] } | null;
  onOpenRun: (runId: string) => void;
  onOpenRuns: () => void;
  onOpenAgents: () => void;
  onOpenSettings: () => void;
  /** Spend or settings may have changed: the shell re-reads its header. */
  onWorkspaceChanged: () => void;
}

/** How many finished runs the Home screen shows before pointing at the list. */
const RECENT = 6;

export function HomeView({
  space,
  blocker,
  pendingApprovals,
  liveStatus,
  onOpenRun,
  onOpenRuns,
  onOpenAgents,
  onOpenSettings,
  onWorkspaceChanged,
}: HomeViewProps) {
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [busyAgent, setBusyAgent] = useState<string | null>(null);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);

  const runs = useRunList((state) => state.runs);
  const runsLoaded = useRunList((state) => state.loaded);
  const runsError = useRunList((state) => state.error);
  const reloadRuns = useRunList((state) => state.load);
  const ensureRuns = useRunList((state) => state.ensure);
  const agents = useRoster((state) => state.agents);
  const rosterLoaded = useRoster((state) => state.loaded);
  const reloadRoster = useRoster((state) => state.load);
  const ensureRoster = useRoster((state) => state.ensure);

  useEffect(() => {
    ensureRuns();
    ensureRoster();
  }, [ensureRuns, ensureRoster]);

  const waitingOn = new Set(pendingApprovals.map((approval) => approval.run_id));
  const statusOf = (run: Run): Run["status"] =>
    liveStatus !== null && liveStatus.runId === run.id ? liveStatus.status : run.status;

  // "Now": anything the table says is still going, plus anything a person is
  // being asked about. A run that ended while its approval row is still
  // pending would be a sidecar bug; it is listed rather than hidden.
  const now = runs.filter((run) => unfinished({ ...run, status: statusOf(run) }) || waitingOn.has(run.id));
  const recent = runs.filter((run) => !now.includes(run)).slice(0, RECENT);
  const firstLaunch = runsLoaded && runs.length === 0;
  const enabled = agents.filter((agent) => agent.enabled !== false);

  const start = async () => {
    const trimmed = goal.trim();
    if (trimmed === "" || blocker !== null) return;
    setStarting(true);
    setStartError(null);
    try {
      const run = await api.createRun(trimmed, space?.id);
      setGoal("");
      onOpenRun(run.id);
      void reloadRuns();
    } catch (failure) {
      setStartError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setStarting(false);
    }
  };

  // The scripted run: twenty events, no model, no key. It is what the graph
  // can show before any provider is configured.
  const demo = async () => {
    setDemoError(null);
    try {
      const run = await api.startDebugRun();
      onOpenRun(run.id);
      void reloadRuns();
    } catch (failure) {
      setDemoError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  // An empty roster gets the three built-in roles on request — what a space
  // created with "no agents" is offered once its owner changes their mind.
  const seed = async () => {
    if (space === null) return;
    setRosterError(null);
    setSeeding(true);
    try {
      await api.seedSpace(space.id);
      await reloadRoster();
    } catch (failure) {
      setRosterError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSeeding(false);
    }
  };

  const toggle = async (agent: AgentDef) => {
    setRosterError(null);
    setBusyAgent(agent.id);
    try {
      await api.updateAgent(agent.id, { enabled: !(agent.enabled ?? true) });
      await reloadRoster();
      onWorkspaceChanged();
    } catch (failure) {
      setRosterError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusyAgent(null);
    }
  };

  return (
    <div className={`home${firstLaunch ? " home--first" : ""}`} data-testid="home">
      <div className="home__inner">
        {blocker !== null && (
          <section className="card card--notice home__preflight" role="status" data-testid="preflight">
            <h2 className="card__title">Before a run can start</h2>
            <p>{blocker}</p>
            <div className="card__actions">
              <button type="button" className="button" onClick={onOpenSettings}>
                Open settings
              </button>
              <button type="button" className="button" onClick={() => void demo()}>
                Try a demo run
              </button>
            </div>
            {demoError !== null && (
              <p className="field-error" role="alert">
                {demoError}
              </p>
            )}
          </section>
        )}

        <form
          className="new-run"
          data-testid="new-run"
          onSubmit={(submitted) => {
            submitted.preventDefault();
            void start();
          }}
        >
          <label className="new-run__label" htmlFor="goal">
            {firstLaunch
              ? `What should ${space?.name ?? "this space"} work on first?`
              : `What should ${space?.name ?? "this space"} work on?`}
          </label>
          <textarea
            id="goal"
            className="new-run__goal"
            rows={firstLaunch ? 4 : 3}
            value={goal}
            placeholder="Describe the task. The supervisor will plan it and hand parts to the agents that are enabled."
            onChange={(changed) => {
              setGoal(changed.target.value);
            }}
            onKeyDown={(pressed) => {
              // Enter sends, like a chat box; Shift+Enter is a new line.
              if (pressed.key === "Enter" && !pressed.shiftKey) {
                pressed.preventDefault();
                void start();
              }
            }}
            data-testid="goal-input"
          />
          <div className="new-run__row">
            {startError !== null ? (
              <p className="field-error" role="alert">
                {startError}
              </p>
            ) : (
              <p className="new-run__hint">
                {enabled.length === 0
                  ? rosterLoaded
                    ? "No agents are enabled — the supervisor will have nobody to delegate to."
                    : ""
                  : `${String(enabled.length)} agent${enabled.length === 1 ? "" : "s"} ready: ${enabled
                      .map((agent) => agent.name)
                      .join(", ")}.`}
                {firstLaunch && rosterLoaded && agents.length === 0 && space !== null && (
                  <>
                    {" "}
                    <button type="button" className="link" disabled={seeding} onClick={() => void seed()}>
                      Start from the built-in roles
                    </button>
                  </>
                )}
                {firstLaunch && (
                  <>
                    {" "}
                    <button type="button" className="link" onClick={onOpenAgents}>
                      Manage agents
                    </button>
                  </>
                )}
              </p>
            )}
            <button
              type="submit"
              className="button button--primary"
              disabled={starting || goal.trim() === "" || blocker !== null}
            >
              {starting ? "Starting…" : "Start run"}
            </button>
          </div>
        </form>

        {runsError !== null && (
          <p className="field-error" role="alert">
            {runsError}
          </p>
        )}

        {now.length > 0 && (
          <section className="home__section" data-testid="home-now">
            <header className="home__head">
              <h2>Now</h2>
            </header>
            <div className="cards">
              {now.map((run) => (
                <RunCard
                  key={run.id}
                  run={run}
                  liveStatus={statusOf(run)}
                  needsApproval={waitingOn.has(run.id)}
                  onOpen={onOpenRun}
                />
              ))}
            </div>
          </section>
        )}

        {recent.length > 0 && (
          <section className="home__section" data-testid="home-recent">
            <header className="home__head">
              <h2>Recent runs</h2>
              <button type="button" className="button button--small" onClick={onOpenRuns}>
                All runs
              </button>
            </header>
            <div className="cards">
              {recent.map((run) => (
                <RunCard key={run.id} run={run} liveStatus={statusOf(run)} onOpen={onOpenRun} />
              ))}
            </div>
          </section>
        )}

        {!firstLaunch && (
          <section className="home__section" data-testid="home-roster">
            <header className="home__head">
              <h2>Agents</h2>
              <button type="button" className="button button--small" onClick={onOpenAgents}>
                Add an agent
              </button>
            </header>
            {rosterError !== null && (
              <p className="field-error" role="alert">
                {rosterError}
              </p>
            )}
            {rosterLoaded && agents.length === 0 && (
              <p className="home__empty">
                No agents are defined, so the supervisor would have nobody to delegate to.{" "}
                {space !== null && (
                  <button type="button" className="link" disabled={seeding} onClick={() => void seed()}>
                    Start from the built-in roles
                  </button>
                )}
              </p>
            )}
            <ul className="roster-cards">
              {agents.map((agent) => (
                <li
                  key={agent.id}
                  className={`roster-card${agent.enabled === false ? " roster-card--off" : ""}`}
                  data-testid={`home-agent-${agent.name}`}
                >
                  <span className="roster-card__name">
                    {agent.name}
                    {agent.is_builtin === true && <span className="tag">built-in</span>}
                  </span>
                  <span className="roster-card__role">{agent.role}</span>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={agent.enabled ?? true}
                      disabled={busyAgent === agent.id}
                      onChange={() => void toggle(agent)}
                      aria-label={`Available to the supervisor: ${agent.name}`}
                    />
                    <span>{agent.enabled === false ? "off" : "on"}</span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
