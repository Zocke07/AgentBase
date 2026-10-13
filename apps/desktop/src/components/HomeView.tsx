import type {
  AgentDef,
  ApprovalResponse,
  MarketAlert,
  Run,
  ScheduleResponse,
  SearchHit,
  SpaceResponse,
} from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { whenLabel } from "../lib/format";
import { pipelineNotice as noticeFor } from "../lib/pipeline";
import { useRoster } from "../state/roster";
import { unfinished, useRunList } from "../state/runList";
import { useFetched } from "../state/useFetched";

import { Markdown } from "./Markdown";
import { MarketAlerts } from "./MarketAlerts";
import { MetricBar } from "./MetricBar";
import { PipelineOffer } from "./PipelineOffer";
import { PortfolioEditor } from "./PortfolioEditor";
import { RunCard } from "./RunCard";

/**
 * Home when no run is open: preflight, what runs on its own (the automations
 * strip, with the shipped pipeline's one-click start), active/pending "Now",
 * Run once for a single task you watch, recent-run cards and roster toggles.
 * No state is tied to a specific run.
 */

export interface HomeViewProps {
  /** Screen space; null until list loads. */
  space: SpaceResponse | null;
  /** Current start refusal or null. */
  blocker: string | null;
  /** What the refusal is about: app setup, this space's own settings (a
   * model the account cannot use) or the month's cap. */
  blockerKind?: BlockerKind | undefined;
  /** All pending approvals, identifying blocked cards. */
  pendingApprovals: readonly ApprovalResponse[];
  /** Open-run log status when table lags. */
  liveStatus: { runId: string; status: Run["status"] } | null;
  /** Effective `provider · model` for retrieval preview. */
  modelLabel: string | null;
  onOpenRun: (runId: string) => void;
  onOpenRuns: () => void;
  onOpenAgents: () => void;
  onOpenSettings: () => void;
  /** Open this space's settings, where its model is chosen. */
  onOpenSpaceSettings?: (() => void) | undefined;
  /** Open a cited note in the Knowledge section. */
  onOpenNote?: ((path: string, heading: string | null) => void) | undefined;
  /** Spend/settings may change; shell reloads header. */
  onWorkspaceChanged: () => void;
  onPortfolioSaved?: (() => void) | undefined;
  /** Per-run spending ceiling in micros, named where the pipeline is offered. */
  runCapMicros?: number | null | undefined;
  onOpenAutomations?: (() => void) | undefined;
  /** Open Automations with a new schedule for this goal ("" for a blank one). */
  onAutomate?: ((goal: string) => void) | undefined;
  /** Moves when schedules change elsewhere, so the strip rereads them. */
  schedulesNonce?: number | undefined;
  /** Home changed the schedules (the pipeline turned on). */
  onSchedulesChanged?: (() => void) | undefined;
  /** This space's recent market alerts, newest first (Phase 18). */
  alerts?: readonly MarketAlert[] | undefined;
  /** Alert ids that were unseen when Home was opened, marked as new. */
  freshAlerts?: ReadonlySet<string> | undefined;
}

export type BlockerKind = "setup" | "space" | "cap";

/** The pre-flight card's title for each cause. */
const BLOCKER_TITLE: Record<BlockerKind, string> = {
  setup: "One step before your first run",
  space: "This space needs a different model",
  cap: "This month's spending cap is reached",
};

const NO_SCHEDULES: ScheduleResponse[] = [];
const NO_ALERTS: readonly MarketAlert[] = [];
const NO_FRESH: ReadonlySet<string> = new Set();

/** How many finished runs the Home screen shows before pointing at the list. */
const RECENT = 6;

/**
 * Summarize a long roster with three names and total count.
 */
function readyLine(names: readonly string[]): string {
  const count = `${String(names.length)} agent${names.length === 1 ? "" : "s"} ready`;
  if (names.length <= 3) return `${count}: ${names.join(", ")}.`;
  return `${count}: ${names.slice(0, 3).join(", ")} and ${String(names.length - 3)} more.`;
}

export function HomeView({
  space,
  blocker,
  blockerKind = "setup",
  pendingApprovals,
  liveStatus,
  modelLabel,
  onOpenRun,
  onOpenRuns,
  onOpenAgents,
  onOpenSettings,
  onOpenSpaceSettings,
  onOpenNote,
  onWorkspaceChanged,
  onPortfolioSaved,
  runCapMicros = null,
  onOpenAutomations,
  onAutomate,
  schedulesNonce = 0,
  onSchedulesChanged,
  alerts = NO_ALERTS,
  freshAlerts = NO_FRESH,
}: HomeViewProps) {
  const [goal, setGoal] = useState("");
  const [stepThrough, setStepThrough] = useState(false);
  const [pipelineNotice, setPipelineNotice] = useState<string | null>(null);
  const [portfolioNonce, setPortfolioNonce] = useState(0);
  const spaceId = space?.id ?? null;
  const loadSchedules = useCallback(
    () => (spaceId === null ? Promise.resolve(NO_SCHEDULES) : api.listSchedules(spaceId)),
    [spaceId],
  );
  const schedules = useFetched(loadSchedules, NO_SCHEDULES);
  const { reload: reloadSchedules } = schedules;
  // Schedules changed in Automations: reread the strip.
  useEffect(() => {
    if (schedulesNonce > 0) reloadSchedules();
  }, [schedulesNonce, reloadSchedules]);
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

  // "Now" includes ongoing runs and user questions.
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
      const run = stepThrough
        ? await api.createRun(trimmed, space?.id, excludedCitations, true)
        : excludedCitations.length === 0
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

  // Scripted run has twenty events, no model or key.
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

  // Empty roster can seed three starter roles.
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
            <h2 className="card__title">{BLOCKER_TITLE[blockerKind]}</h2>
            <p>{blocker}</p>
            <div className="card__actions">
              {blockerKind === "space" && onOpenSpaceSettings !== undefined ? (
                <button type="button" className="button" onClick={onOpenSpaceSettings}>
                  Open Space settings
                </button>
              ) : (
                <button type="button" className="button" onClick={onOpenSettings}>
                  Open settings
                </button>
              )}
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

        {space !== null && <PortfolioEditor key={space.id} spaceId={space.id} reloadNonce={portfolioNonce} running={now.some((run) => run.space_id === space.id && unfinished({ ...run, status: statusOf(run) }))} onSaved={() => {
          onWorkspaceChanged();
          onPortfolioSaved?.();
        }} />}

        <section className="home__section home__automations" data-testid="home-automations">
          {pipelineNotice !== null && (
            <p className="settings__saved" role="status">
              {pipelineNotice}
            </p>
          )}
          {space !== null && (
            <PipelineOffer
              spaceId={space.id}
              // Only this space's rows: a list still loading after a switch
              // must not turn on another space's schedules.
              schedules={schedules.data.filter((row) => row.space_id === space.id)}
              runCapMicros={runCapMicros}
              onTurnedOn={(result) => {
                setPipelineNotice(noticeFor(result));
                setPortfolioNonce((current) => current + 1);
                schedules.reload();
                onSchedulesChanged?.();
              }}
            />
          )}
          <AutomationsLine
            schedules={schedules.data}
            loaded={!schedules.loading}
            spaceName={space?.name ?? "this space"}
            onOpenAutomations={onOpenAutomations}
            onAutomate={onAutomate}
          />
        </section>

        <MarketAlerts
          alerts={alerts}
          fresh={freshAlerts}
          onOpenNote={
            onOpenNote === undefined
              ? undefined
              : (path) => {
                  onOpenNote(path, null);
                }
          }
          onOpenRun={onOpenRun}
          onOpenAutomations={onOpenAutomations}
        />

        <form
          className="new-run"
          data-testid="new-run"
          onSubmit={(submitted) => {
            submitted.preventDefault();
            void start();
          }}
        >
          <h2 className="new-run__title">Run once</h2>
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
            placeholder="Describe what you want done, in plain words. For example: Summarise the notes in this space into one page."
            onChange={(changed) => {
              setGoal(changed.target.value);
              setRetrieval(null);
              setExcludedCitations([]);
            }}
            onKeyDown={(pressed) => {
              // Enter submits; Shift+Enter adds line.
              if (pressed.key === "Enter" && !pressed.shiftKey) {
                pressed.preventDefault();
                void start();
              }
            }}
            data-testid="goal-input"
            data-tour="goal"
          />
          {retrieval !== null && (
            <fieldset className="new-run__retrieval" data-testid="retrieval-preview">
              <legend>Notes it will read</legend>
              <p>
                {retrieval.length > 0 ? (
                  <>
                    {includedCount === 1 ? "This passage" : `These ${String(includedCount)} passages`} from this
                    space&apos;s notes
                    will be sent along with your task to <strong>{modelLabel ?? "the model"}</strong> (about{" "}
                    {includedTokens} tokens). Untick anything you would rather keep out.
                  </>
                ) : (
                  "None of this space's notes or approved memories match this task, so it will start from your words alone."
                )}
              </p>
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
                    <MetricBar value={hit.score} label={`Relevance for ${hit.citation}`} />
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
          <label
            className="new-run__step"
            title="The manual and debug path: every tool call waits for your answer, whatever the approval policy would do."
          >
            <input
              type="checkbox"
              checked={stepThrough}
              onChange={(changed) => {
                setStepThrough(changed.target.checked);
              }}
              data-testid="step-through"
            />
            <span>Step through: ask me before every call</span>
          </label>
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
                  : readyLine(enabled.map((agent) => agent.name))}
                {firstLaunch && rosterLoaded && agents.length === 0 && space !== null && (
                  <>
                    {" "}
                    <button type="button" className="link" disabled={seeding} onClick={() => void seed()}>
                      Start from the starter roles
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
              {onAutomate !== undefined && (
                <button
                  type="button"
                  className="button"
                  disabled={goal.trim() === ""}
                  title="Open Automations with a new schedule for this goal"
                  onClick={() => {
                    onAutomate(goal.trim());
                  }}
                  data-testid="make-recurring"
                >
                  Make this recurring
                </button>
              )}
              <button
                type="button"
                className="button"
                disabled={retrieving || goal.trim() === "" || space === null}
                aria-busy={retrieving}
                title="See which of this space's notes will be sent along with your task"
                onClick={() => void previewRetrieval()}
              >
                {retrieving ? "Looking…" : "Preview notes"}
              </button>
              <button
                type="submit"
                className="button button--primary"
                disabled={starting || goal.trim() === "" || blocker !== null}
                aria-busy={starting}
                title={blocker ?? "Enter starts it too; Shift+Enter makes a new line"}
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
                    Start from the starter roles
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
                  <span className="roster-card__name" title={`${agent.name}: ${agent.role}`}>
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


/**
 * One line on what runs here on its own: how many automations are on and the
 * next one due, or an offer to automate a task when nothing does yet.
 */
function AutomationsLine({
  schedules,
  loaded,
  spaceName,
  onOpenAutomations,
  onAutomate,
}: {
  schedules: readonly ScheduleResponse[];
  loaded: boolean;
  spaceName: string;
  onOpenAutomations?: (() => void) | undefined;
  onAutomate?: ((goal: string) => void) | undefined;
}) {
  if (!loaded) return null;
  const on = schedules.filter((row) => row.enabled !== false);
  const timed = on
    .filter((row) => row.next_run_at !== null && row.next_run_at !== undefined)
    .sort((left, right) => (left.next_run_at ?? "").localeCompare(right.next_run_at ?? ""));
  const next = timed[0];

  return (
    <div className="home__automations-line" data-testid="home-automations-line">
      <p>
        {on.length === 0
          ? `Nothing in ${spaceName} runs on its own yet.`
          : `${String(on.length)} automation${on.length === 1 ? "" : "s"} on.${
              next !== undefined ? ` Next: ${next.name}, ${whenLabel(next.next_run_at ?? "")}.` : ""
            }`}
      </p>
      <div className="home__automations-actions">
        {on.length === 0 && onAutomate !== undefined && (
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              onAutomate("");
            }}
          >
            Automate a task
          </button>
        )}
        {onOpenAutomations !== undefined && (
          <button type="button" className="button button--small" onClick={onOpenAutomations}>
            Open Automations
          </button>
        )}
      </div>
    </div>
  );
}
