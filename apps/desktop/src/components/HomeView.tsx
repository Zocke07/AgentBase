import type { AgentDef, ApprovalResponse, Run, SearchHit, SpaceResponse } from "@agentspace/schemas";
import { useEffect, useState } from "react";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { unfinished, useRunList } from "../state/runList";

import { Markdown } from "./Markdown";
import { RunCard } from "./RunCard";

/**
 * The Home screen: what a person sees when nothing is open. Top to bottom:
 * the pre-flight (why a run would be refused, if it would), the goal box,
 * "Now" (runs in progress and approvals waiting), recent runs as cards, and
 * the roster with its enable toggles. A fresh install gets the goal box as
 * the whole screen. Nothing here is about a particular run.
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
  /** "provider · model" a run here would use, so the retrieval preview can say where excerpts go. */
  modelLabel: string | null;
  onOpenRun: (runId: string) => void;
  onOpenRuns: () => void;
  onOpenAgents: () => void;
  onOpenSettings: () => void;
  /** Open a cited note in the Knowledge section. */
  onOpenNote?: ((path: string, heading: string | null) => void) | undefined;
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
  modelLabel,
  onOpenRun,
  onOpenRuns,
  onOpenAgents,
  onOpenSettings,
  onOpenNote,
  onWorkspaceChanged,
}: HomeViewProps) {
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  const [retrieval, setRetrieval] = useState<SearchHit[] | null>(null);
  const [excludedCitations, setExcludedCitations] = useState<string[]>([]);
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

  // "Now": anything still going, plus anything a person is being asked about.
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
      const run =
        excludedCitations.length === 0
          ? await api.createRun(trimmed, space?.id)
          : await api.createRun(trimmed, space?.id, excludedCitations);
      setGoal("");
      setRetrieval(null);
      setExcludedCitations([]);
      onOpenRun(run.id);
      void reloadRuns();
    } catch (failure) {
      setStartError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setStarting(false);
    }
  };

  const kept = (retrieval ?? []).filter((hit) => !excludedCitations.includes(hit.citation));
  const includedCount = kept.length;
  const includedTokens = kept.reduce((total, hit) => total + (hit.estimated_tokens ?? 0), 0);

  const previewRetrieval = async () => {
    const trimmed = goal.trim();
    if (trimmed === "" || space === null) return;
    setRetrieving(true);
    setStartError(null);
    try {
      setRetrieval((await api.searchKnowledge(space.id, trimmed, 6)).hits);
      setExcludedCitations([]);
    } catch (failure) {
      setStartError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setRetrieving(false);
    }
  };

  // The scripted run: twenty events, no model, no key.
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

  // An empty roster gets the three built-in roles on request.
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
              setRetrieval(null);
              setExcludedCitations([]);
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
          {retrieval !== null && (
            <fieldset className="new-run__retrieval" data-testid="retrieval-preview">
              <legend>Retrieved context</legend>
              <p>
                Clear a result to keep it out of this run and its worker handoffs.
                {retrieval.length > 0 && (
                  <>
                    {" "}
                    The {includedCount} kept excerpt{includedCount === 1 ? "" : "s"} (about{" "}
                    {includedTokens} tokens) leave this machine with your goal, sent to{" "}
                    <strong>{modelLabel ?? "the configured model"}</strong>.
                  </>
                )}
              </p>
              {retrieval.length === 0 && <p>No approved memory or note matched this goal.</p>}
              {retrieval.map((hit) => (
                <label key={hit.citation}>
                  <input
                    type="checkbox"
                    checked={!excludedCitations.includes(hit.citation)}
                    onChange={(event) => {
                      setExcludedCitations((current) =>
                        event.target.checked
                          ? current.filter((citation) => citation !== hit.citation)
                          : [...current, hit.citation],
                      );
                    }}
                  />
                  <span>
                    {onOpenNote === undefined ? (
                      <code>{hit.citation}</code>
                    ) : (
                      <button
                        type="button"
                        className="citation"
                        title="Open this note in Knowledge"
                        onClick={(event) => {
                          event.preventDefault();
                          onOpenNote(hit.path, hit.heading ?? null);
                        }}
                      >
                        {hit.citation}
                      </button>
                    )}
                    {hit.excerpt !== "" && (
                      <Markdown source={hit.excerpt} className="md--compact new-run__excerpt" />
                    )}
                    <small>
                      {Math.round(hit.score * 100)}% relevance · {hit.estimated_tokens ?? 0} tokens
                      {(hit.matched_terms ?? []).length > 0 &&
                        ` · matched ${(hit.matched_terms ?? []).join(", ")}`}
                      {(hit.reasons ?? []).length > 0 && ` · ${(hit.reasons ?? []).join(" · ")}`}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          <div className="new-run__row">
            {startError !== null ? (
              <p className="field-error" role="alert">
                {startError}
              </p>
            ) : (
              <p className="new-run__hint">
                {enabled.length === 0
                  ? rosterLoaded
                    ? "No agents are enabled: the supervisor will have nobody to delegate to."
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
            <div className="new-run__actions">
              <button
                type="button"
                className="button"
                disabled={retrieving || goal.trim() === "" || space === null}
                onClick={() => void previewRetrieval()}
              >
                {retrieving ? "Retrieving…" : "Preview context"}
              </button>
              <button
                type="submit"
                className="button button--primary"
                disabled={starting || goal.trim() === "" || blocker !== null}
              >
                {starting ? "Starting…" : "Start run"}
              </button>
            </div>
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
