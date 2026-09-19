import type {
  CreateScheduleRequest,
  RiskLevel,
  ScheduleResponse,
  SettingsResponse,
  SpaceResponse,
  ToolPolicy,
} from "@agentspace/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { whenLabel } from "../lib/format";
import { useFetched } from "../state/useFetched";

/**
 * A space's schedules: goals it runs on its own at set times, while the app
 * is open. The list says when each will next run and what happened last
 * time; the editor is a picker (daily, weekly, every N hours) with the
 * sidecar's own preview of what that means, so the words and the times a
 * user sees before saving are the ones the scheduler will use.
 */

export interface SchedulesProps {
  space: SpaceResponse;
  /** The app-wide settings, to say what the space's approval policy means for an unattended run. */
  settings: SettingsResponse | null;
  /** Open the run a schedule last started; absent where no run view is reachable. */
  onOpenRun?: ((runId: string) => void) | undefined;
}

type Cadence = CreateScheduleRequest["cadence"];
type Missed = NonNullable<CreateScheduleRequest["missed"]>;

interface Draft {
  name: string;
  goal: string;
  kind: Cadence["kind"];
  at: string;
  weekdays: number[];
  everyHours: string;
  missed: Missed;
  enabled: boolean;
  /** A time limit for this schedule's runs, as typed; blank inherits the space's. */
  seconds: string;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const FORM = "__form__";
const NO_SCHEDULES: ScheduleResponse[] = [];

const BLANK: Draft = {
  name: "",
  goal: "",
  kind: "daily",
  at: "09:00",
  weekdays: [0, 1, 2, 3, 4],
  everyHours: "6",
  missed: "run_on_launch",
  enabled: true,
  seconds: "",
};

function fromSchedule(schedule: ScheduleResponse): Draft {
  const cadence = schedule.cadence;
  return {
    name: schedule.name,
    goal: schedule.goal,
    kind: cadence.kind,
    at: cadence.kind === "interval" ? BLANK.at : cadence.at,
    weekdays: cadence.kind === "weekly" ? [...cadence.weekdays] : BLANK.weekdays,
    everyHours: cadence.kind === "interval" ? String(cadence.every_hours) : BLANK.everyHours,
    missed: schedule.missed ?? "run_on_launch",
    enabled: schedule.enabled ?? true,
    seconds: schedule.max_run_seconds === null || schedule.max_run_seconds === undefined ? "" : String(schedule.max_run_seconds),
  };
}

/** The cadence the draft describes, or the reason it does not describe one yet. */
function cadenceOf(draft: Draft): { cadence: Cadence } | { error: string; field: string } {
  if (draft.kind === "interval") {
    const hours = Number(draft.everyHours);
    if (!/^\d+$/.test(draft.everyHours.trim()) || hours < 1 || hours > 168) {
      return { error: "A whole number of hours from 1 to 168.", field: "everyHours" };
    }
    return { cadence: { kind: "interval", every_hours: hours } };
  }
  if (!/^\d{2}:\d{2}$/.test(draft.at)) return { error: "A time of day, like 09:30.", field: "at" };
  if (draft.kind === "weekly") {
    if (draft.weekdays.length === 0) return { error: "Pick at least one day.", field: "weekdays" };
    return { cadence: { kind: "weekly", at: draft.at, weekdays: [...draft.weekdays].sort((a, b) => a - b) } };
  }
  return { cadence: { kind: "daily", at: draft.at } };
}

/**
 * The risk levels a run in this space may call without asking: the space's
 * own policy narrowed by the app-wide one, the way the sidecar resolves it.
 */
function effectiveAutoApprove(space: SpaceResponse, settings: SettingsResponse | null): RiskLevel[] {
  const appWide = settings?.settings.auto_approve ?? [];
  const own = space.auto_approve ?? null;
  return own === null ? [...appWide] : own.filter((level) => appWide.includes(level));
}

/** Strictness, for narrowing: a space may move a tool along this order, never back. */
const STRICTNESS: Record<ToolPolicy, number> = { allow: 0, ask: 1, deny: 2 };

/**
 * The per-tool answers a run in this space gets: the app-wide ones with the
 * space's laid over them, each tool keeping the stricter answer, the way the
 * sidecar merges them.
 */
function effectiveToolPolicies(space: SpaceResponse, settings: SettingsResponse | null): Record<string, ToolPolicy> {
  const merged: Record<string, ToolPolicy> = { ...(settings?.settings.tool_policies ?? {}) };
  for (const [tool, wanted] of Object.entries(space.tool_policies ?? {})) {
    const above = merged[tool] ?? "ask";
    merged[tool] = STRICTNESS[wanted] >= STRICTNESS[above] ? wanted : above;
  }
  return merged;
}

/** "write_file and http_get" from a list of names. */
function names(tools: string[]): string {
  return tools.length <= 1 ? tools.join("") : `${tools.slice(0, -1).join(", ")} and ${tools[tools.length - 1] ?? ""}`;
}

export function Schedules({ space, settings, onOpenRun }: SchedulesProps) {
  const load = useCallback(() => api.listSchedules(space.id), [space.id]);
  const schedules = useFetched(load, NO_SCHEDULES);
  // What the editor is open on: nothing, a new schedule, or one row's id.
  const [editing, setEditing] = useState<{ kind: "none" } | { kind: "new" } | { kind: "row"; id: string }>({ kind: "none" });
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allowed = effectiveAutoApprove(space, settings);
  const policies = effectiveToolPolicies(space, settings);
  const always = Object.keys(policies).filter((tool) => policies[tool] === "allow");
  const never = Object.keys(policies).filter((tool) => policies[tool] === "deny");
  const runSeconds = space.max_run_seconds ?? settings?.settings.max_run_seconds ?? null;
  const steps = space.max_steps_per_agent ?? settings?.settings.max_steps_per_agent ?? null;
  const agentsPerRun = space.max_agents_per_run ?? settings?.settings.max_agents_per_run ?? null;
  const runCap = space.max_run_cost_micros ?? settings?.settings.max_run_cost_micros ?? null;
  const unattended = allowed.length > 0 || always.length > 0;

  const act = async (id: string, work: () => Promise<string | null>) => {
    setBusyId(id);
    setError(null);
    try {
      const said = await work();
      if (said !== null) setNotice(said);
      schedules.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusyId(null);
    }
  };

  const editingRow = editing.kind === "row" ? (schedules.data.find((row) => row.id === editing.id) ?? null) : null;

  return (
    <section className="settings__section" data-testid="schedules">
      <div className="schedules__head">
        <h2>Schedules</h2>
        {editing.kind === "none" && (
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              setEditing({ kind: "new" });
              setNotice(null);
            }}
          >
            New schedule
          </button>
        )}
      </div>
      <p className="settings__hint">
        A goal this space runs on its own at set times, while AgentSpace is open. A time that passes
        while the app is closed is run once at the next launch or skipped, as each schedule says.
      </p>
      {space.archived === true && (
        <p className="settings__hint schedules__warning" role="status">
          This space is archived, so its schedules will not run.
        </p>
      )}
      {/* What a run with nobody at the window will do here, read the way the
          sidecar reads it: levels, then answers by tool, then the limits. */}
      <div className={unattended ? "schedules__readout" : "schedules__readout schedules__readout--warn"} data-testid="schedules-policy">
        <p>
          <b>Unattended, a run here</b>{" "}
          {unattended
            ? `${[
                allowed.length > 0 ? `calls ${allowed.join("- and ")}-risk tools without asking` : "",
                always.length > 0 ? `runs ${names(always)} without asking whatever the level` : "",
                never.length > 0 ? `is refused ${names(never)}` : "",
              ]
                .filter((part) => part !== "")
                .join(", ")}; everything else asks and, with nobody to answer, waits${
                runSeconds !== null ? ` up to ${String(runSeconds)} seconds` : ""
              }, then the run fails.`
            : `asks before every tool call${never.length > 0 ? ` (and is refused ${names(never)})` : ""} and, with nobody to answer, each question waits${
                runSeconds !== null ? ` up to ${String(runSeconds)} seconds` : ""
              }, then the run fails.`}
          {steps !== null && agentsPerRun !== null && runSeconds !== null && (
            <>
              {" "}
              It stops at {String(steps)} steps per agent, {String(agentsPerRun)} agents,{" "}
              {String(runSeconds)} seconds{runCap !== null && runCap > 0 && ` or $${(runCap / 1_000_000).toFixed(2)} spent`},
              unless a schedule sets its own time limit below.
            </>
          )}
        </p>
        {!unattended && (
          <p>
            To let it work on its own, tick the risk levels you trust or set the tools it needs to
            Always allow, under Limits and approvals above.
          </p>
        )}
      </div>

      {schedules.error !== null && (
        <p className="field-error" role="alert">
          {schedules.error}
        </p>
      )}
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {notice !== null && (
        <p className="settings__saved" role="status">
          {notice}
        </p>
      )}

      {schedules.data.length === 0 && editing.kind === "none" && !schedules.loading && (
        <p className="schedules__empty">No schedules yet.</p>
      )}

      {schedules.data.length > 0 && (
        <ul className="schedules__list">
          {schedules.data.map((row) => {
            const busy = busyId === row.id;
            return (
              <li key={row.id} className={`schedule${row.enabled === false ? " schedule--off" : ""}`} data-testid={`schedule-${row.id}`}>
                <div className="schedule__main">
                  <div className="schedule__title">
                    <label className="schedule__switch">
                      <input
                        type="checkbox"
                        checked={row.enabled ?? true}
                        disabled={busy}
                        aria-label={`${row.name} enabled`}
                        onChange={(changed) => {
                          const enabled = changed.target.checked;
                          void act(row.id, async () => {
                            await api.updateSchedule(row.id, { enabled });
                            return null;
                          });
                        }}
                      />
                    </label>
                    <span className="schedule__name">{row.name}</span>
                    <span className="schedule__summary">{row.summary}</span>
                  </div>
                  <p className="schedule__goal">{row.goal}</p>
                  <p className="schedule__when">
                    {row.enabled === false ? (
                      "Off"
                    ) : row.next_run_at !== null && row.next_run_at !== undefined ? (
                      <>Next: {whenLabel(row.next_run_at)}</>
                    ) : (
                      "No next time"
                    )}
                    {row.last_run_at !== null && row.last_run_at !== undefined && (
                      <>
                        {" · Last: "}
                        {whenLabel(row.last_run_at)}
                        {row.last_run_id !== null && row.last_run_id !== undefined && onOpenRun !== undefined && (
                          <>
                            {" "}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => {
                                onOpenRun(row.last_run_id ?? "");
                              }}
                            >
                              open the run
                            </button>
                          </>
                        )}
                      </>
                    )}
                    {row.last_outcome !== null && row.last_outcome !== undefined && (
                      <span className="schedule__outcome"> · {row.last_outcome}</span>
                    )}
                    {row.max_run_seconds !== null && row.max_run_seconds !== undefined && (
                      <span className="schedule__limit"> · its runs get {String(row.max_run_seconds)} seconds</span>
                    )}
                  </p>
                </div>
                <div className="schedule__actions">
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy || space.archived === true}
                    onClick={() => {
                      void act(row.id, async () => {
                        const run = await api.runScheduleNow(row.id);
                        return `Started a run for ${row.name}: ${run.id.slice(0, 8)}.`;
                      });
                    }}
                  >
                    Run now
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    disabled={busy}
                    onClick={() => {
                      setEditing({ kind: "row", id: row.id });
                      setNotice(null);
                    }}
                  >
                    Edit
                  </button>
                  {confirming === row.id ? (
                    <span className="roster__confirm">
                      <button
                        type="button"
                        className="button button--small button--danger"
                        disabled={busy}
                        onClick={() => {
                          setConfirming(null);
                          void act(row.id, async () => {
                            await api.deleteSchedule(row.id);
                            if (editing.kind === "row" && editing.id === row.id) setEditing({ kind: "none" });
                            return `Deleted ${row.name}.`;
                          });
                        }}
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        className="button button--small"
                        onClick={() => {
                          setConfirming(null);
                        }}
                      >
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="button button--small"
                      disabled={busy}
                      onClick={() => {
                        setConfirming(row.id);
                      }}
                    >
                      Delete…
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {editing.kind !== "none" && (
        <ScheduleEditor
          key={editing.kind === "row" ? editing.id : "new"}
          spaceId={space.id}
          existing={editingRow}
          onCancel={() => {
            setEditing({ kind: "none" });
          }}
          onSaved={(saved, created) => {
            setEditing({ kind: "none" });
            setNotice(
              created
                ? `Saved ${saved.name}. ${saved.summary}${saved.next_run_at !== null && saved.next_run_at !== undefined ? `; next ${whenLabel(saved.next_run_at)}` : ""}.`
                : `Saved ${saved.name}.`,
            );
            schedules.reload();
          }}
        />
      )}
    </section>
  );
}

function ScheduleEditor({
  spaceId,
  existing,
  onCancel,
  onSaved,
}: {
  spaceId: string;
  existing: ScheduleResponse | null;
  onCancel: () => void;
  onSaved: (saved: ScheduleResponse, created: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => (existing === null ? BLANK : fromSchedule(existing)));
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<{ summary: string; next: string[] } | null>(null);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((prior) => ({ ...prior, [key]: value }));
    setErrors(({ [key]: _cleared, ...rest }) => rest);
  };
  const errorFor = (field: string): string | null => errors[field] ?? null;

  // The preview is the sidecar's own reading of the cadence, in the machine's
  // zone; asked for on every change so the words update as the picker does.
  const shaped = cadenceOf(draft);
  const previewKey = "cadence" in shaped ? JSON.stringify(shaped.cadence) : null;
  useEffect(() => {
    if (previewKey === null) return undefined;
    let live = true;
    const cadence = JSON.parse(previewKey) as Cadence;
    void api
      .previewSchedule(cadence)
      .then((reply) => {
        if (live) setPreview({ summary: reply.summary, next: reply.next });
      })
      .catch(() => {
        // The preview is a courtesy; a save still validates.
      });
    return () => {
      live = false;
    };
  }, [previewKey]);

  const save = async () => {
    setErrors({});
    if (draft.name.trim() === "") {
      setErrors({ name: "A schedule needs a name." });
      return;
    }
    if (draft.goal.trim() === "") {
      setErrors({ goal: "What should the agents do each time?" });
      return;
    }
    if ("error" in shaped) {
      setErrors({ [shaped.field]: shaped.error });
      return;
    }
    const seconds = draft.seconds.trim();
    if (seconds !== "" && (!/^\d+$/.test(seconds) || Number(seconds) < 1)) {
      setErrors({ max_run_seconds: "A whole number of seconds, 1 or more, or blank to use the space's limit." });
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: draft.name.trim(),
        goal: draft.goal.trim(),
        cadence: shaped.cadence,
        missed: draft.missed,
        enabled: draft.enabled,
        max_run_seconds: seconds === "" ? null : Number(seconds),
      };
      const saved =
        existing === null
          ? await api.createSchedule({ space_id: spaceId, ...body })
          : await api.updateSchedule(existing.id, body);
      onSaved(saved, existing === null);
    } catch (failure) {
      if (failure instanceof ApiError) setErrors({ [failure.field ?? FORM]: failure.message });
      else setErrors({ [FORM]: failure instanceof Error ? failure.message : String(failure) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="schedule-editor" data-testid="schedule-editor">
      <h3>{existing === null ? "New schedule" : `Edit ${existing.name}`}</h3>
      <div className="editor__row">
        <label className="editor__field">
          <span>Name</span>
          <input
            type="text"
            value={draft.name}
            maxLength={60}
            placeholder="Morning digest"
            onChange={(changed) => {
              set("name", changed.target.value);
            }}
            aria-invalid={errorFor("name") !== null}
            data-testid="schedule-name"
          />
          <FieldError message={errorFor("name")} />
        </label>
      </div>
      <label className="editor__field">
        <span>Goal</span>
        <textarea
          rows={3}
          value={draft.goal}
          placeholder="Summarise what changed in the notes since yesterday and propose a memory."
          onChange={(changed) => {
            set("goal", changed.target.value);
          }}
          aria-invalid={errorFor("goal") !== null}
          data-testid="schedule-goal"
        />
        <FieldError message={errorFor("goal")} />
      </label>

      <fieldset className="editor__tools schedule-editor__cadence">
        <legend>When</legend>
        <div className="schedule-editor__kinds" role="radiogroup" aria-label="Cadence">
          {(
            [
              ["daily", "Every day"],
              ["weekly", "On chosen days"],
              ["interval", "Every few hours"],
            ] as const
          ).map(([kind, label]) => (
            <label key={kind} className="editor__tool">
              <input
                type="radio"
                name="cadence-kind"
                checked={draft.kind === kind}
                onChange={() => {
                  set("kind", kind);
                }}
                data-testid={`schedule-kind-${kind}`}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
        {draft.kind !== "interval" && (
          <label className="editor__field editor__field--narrow">
            <span>At</span>
            <input
              type="time"
              value={draft.at}
              onChange={(changed) => {
                set("at", changed.target.value);
              }}
              aria-invalid={errorFor("at") !== null}
              data-testid="schedule-at"
            />
            <FieldError message={errorFor("at")} />
          </label>
        )}
        {draft.kind === "weekly" && (
          <div className="schedule-editor__days" role="group" aria-label="Days">
            {WEEKDAYS.map((name, day) => {
              const on = draft.weekdays.includes(day);
              return (
                <label key={name} className={`schedule-editor__day${on ? " schedule-editor__day--on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => {
                      set(
                        "weekdays",
                        on ? draft.weekdays.filter((item) => item !== day) : [...draft.weekdays, day],
                      );
                    }}
                    data-testid={`schedule-day-${String(day)}`}
                  />
                  {name}
                </label>
              );
            })}
            <FieldError message={errorFor("weekdays")} />
          </div>
        )}
        {draft.kind === "interval" && (
          <label className="editor__field editor__field--narrow">
            <span>Every (hours)</span>
            <input
              inputMode="numeric"
              value={draft.everyHours}
              onChange={(changed) => {
                set("everyHours", changed.target.value);
              }}
              aria-invalid={errorFor("everyHours") !== null}
              data-testid="schedule-hours"
            />
            <FieldError message={errorFor("everyHours")} />
          </label>
        )}
        <p className="schedule-editor__preview" data-testid="schedule-preview">
          {preview === null
            ? "Times are in this computer's local time."
            : `${preview.summary}. Next: ${preview.next.map(whenLabel).join(", ")}.`}
        </p>
        <FieldError message={errorFor("cadence")} />
      </fieldset>

      <fieldset className="editor__tools">
        <legend>If the app is closed at that time</legend>
        <label className="editor__tool">
          <input
            type="radio"
            name="missed"
            checked={draft.missed === "run_on_launch"}
            onChange={() => {
              set("missed", "run_on_launch");
            }}
            data-testid="schedule-missed-run"
          />
          <span>Run it once when AgentSpace next opens</span>
        </label>
        <label className="editor__tool">
          <input
            type="radio"
            name="missed"
            checked={draft.missed === "skip"}
            onChange={() => {
              set("missed", "skip");
            }}
            data-testid="schedule-missed-skip"
          />
          <span>Skip it and wait for the next time</span>
        </label>
      </fieldset>

      <label className="editor__field schedule-editor__limit">
        <span>Time limit for its runs (seconds)</span>
        <input
          type="text"
          inputMode="numeric"
          value={draft.seconds}
          placeholder="the space's limit"
          onChange={(changed) => {
            set("seconds", changed.target.value);
          }}
          aria-invalid={errorFor("max_run_seconds") !== null}
          data-testid="schedule-seconds"
        />
        <span className="editor__hint">
          Only this schedule's runs get this long; runs you start here keep the space's limit.
        </span>
        <FieldError message={errorFor("max_run_seconds")} />
      </label>

      <label className="editor__checkbox">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(changed) => {
            set("enabled", changed.target.checked);
          }}
          data-testid="schedule-enabled"
        />
        <span>Enabled</span>
      </label>

      {errorFor(FORM) !== null && (
        <p className="editor__error editor__error--form" role="alert">
          {errorFor(FORM)}
        </p>
      )}

      <div className="editor__actions">
        <button type="button" className="button" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className="button button--primary" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : existing === null ? "Create schedule" : "Save schedule"}
        </button>
      </div>
    </div>
  );
}

function FieldError({ message }: { message: string | null }) {
  if (message === null) return null;
  return (
    <span className="editor__error" role="alert">
      {message}
    </span>
  );
}
