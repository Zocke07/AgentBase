import type {
  ProviderCatalogueResponse,
  RiskLevel,
  SettingsResponse,
  SpaceResponse,
  ToolPolicy,
  ToolResponse,
  UpdateSpaceRequest,
} from "@agentspace/schemas";
import { useCallback, useState } from "react";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { revealFolder, revealAvailable } from "../lib/folder";
import { useFetched } from "../state/useFetched";

import { Schedules } from "./Schedules";

/**
 * One space's settings: name, description, the folder (shown and opened,
 * never changed), the rules with Inherit as the first choice of each, and a
 * danger zone. Save is a PATCH of what changed, with a rule set back to
 * Inherit sent as `null`. The approval policy can only narrow the app-wide
 * one, and the page says so beside any tick the app-wide policy lacks.
 */

export interface SpaceSettingsViewProps {
  space: SpaceResponse;
  /** The app-wide settings, so "Inherit" can say what it inherits. */
  settings: SettingsResponse | null;
  /** The space changed, or was archived or deleted; the shell re-reads the list. */
  onChanged: (space: SpaceResponse | null) => void;
  /** Open the run a schedule last started. */
  onOpenRun?: ((runId: string) => void) | undefined;
}

interface Form {
  name: string;
  description: string;
  provider: string;
  model: string;
  /** Null: inherit. A list: this space's own policy. */
  auto_approve: RiskLevel[] | null;
  /** Null: inherit every per-tool answer. A map: this space's stricter answers. */
  tool_policies: Record<string, ToolPolicy> | null;
  max_steps_per_agent: string;
  max_agents_per_run: string;
  max_run_seconds: string;
  /** Dollars per run, as typed; blank inherits, "0" lifts the ceiling here. */
  run_cap: string;
}

const MICROS_PER_DOLLAR = 1_000_000;

const RISK_LEVELS: readonly RiskLevel[] = ["low", "medium", "high"];
const LIMITS = ["max_steps_per_agent", "max_agents_per_run", "max_run_seconds"] as const;
const LIMIT_LABEL: Record<(typeof LIMITS)[number], string> = {
  max_steps_per_agent: "Steps per agent",
  max_agents_per_run: "Agents per run",
  max_run_seconds: "Seconds per run",
};
const FORM = "__form__";
const EMPTY_CATALOGUE: ProviderCatalogueResponse = { providers: [], models: {} };
const NO_TOOLS: ToolResponse[] = [];

const POLICY_WORD: Record<ToolPolicy, string> = {
  ask: "ask, by risk level",
  allow: "always allow",
  deny: "never allow",
};

/**
 * The answers a space may give for one tool: the app-wide one, and every
 * stricter one. A space narrows, never widens, so an app-wide refusal leaves
 * only "inherit".
 */
function stricterChoices(appWide: ToolPolicy): ToolPolicy[] {
  if (appWide === "allow") return ["ask", "deny"];
  if (appWide === "ask") return ["deny"];
  return [];
}

/** A limit as typed: blank for inherit, whether the row said null or nothing. */
function limitText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function fromSpace(space: SpaceResponse): Form {
  return {
    name: space.name,
    description: space.description ?? "",
    provider: space.provider ?? "",
    model: space.model ?? "",
    auto_approve: space.auto_approve === undefined || space.auto_approve === null ? null : [...space.auto_approve],
    tool_policies: space.tool_policies === undefined || space.tool_policies === null ? null : { ...space.tool_policies },
    max_steps_per_agent: limitText(space.max_steps_per_agent),
    max_agents_per_run: limitText(space.max_agents_per_run),
    max_run_seconds: limitText(space.max_run_seconds),
    run_cap:
      space.max_run_cost_micros === null || space.max_run_cost_micros === undefined
        ? ""
        : (space.max_run_cost_micros / MICROS_PER_DOLLAR).toFixed(2),
  };
}

/** Dollars typed by a person to whole micros; null when it is not a number. */
function dollarsToMicros(dollars: string): number | null {
  const parsed = Number(dollars.trim());
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * MICROS_PER_DOLLAR);
}

/** The request for what differs between `opened` and `form`. Blank is inherit. */
function diff(opened: Form, form: Form): UpdateSpaceRequest {
  const patch: UpdateSpaceRequest = {};
  if (form.name !== opened.name) patch.name = form.name.trim();
  if (form.description !== opened.description) patch.description = form.description.trim();
  if (form.provider !== opened.provider) patch.provider = form.provider === "" ? null : form.provider;
  if (form.model !== opened.model) patch.model = form.model.trim() === "" ? null : form.model.trim();
  if (JSON.stringify(form.auto_approve) !== JSON.stringify(opened.auto_approve)) {
    patch.auto_approve = form.auto_approve;
  }
  if (JSON.stringify(form.tool_policies) !== JSON.stringify(opened.tool_policies)) {
    patch.tool_policies = form.tool_policies;
  }
  for (const limit of LIMITS) {
    if (form[limit] !== opened[limit]) patch[limit] = form[limit].trim() === "" ? null : Number(form[limit]);
  }
  if (form.run_cap !== opened.run_cap) {
    patch.max_run_cost_micros = form.run_cap.trim() === "" ? null : dollarsToMicros(form.run_cap);
  }
  return patch;
}

export function SpaceSettingsView({ space, settings, onChanged, onOpenRun }: SpaceSettingsViewProps) {
  const loadCatalogue = useCallback(() => api.listProviders(), []);
  const loadTools = useCallback(() => api.listTools(), []);
  const catalogue = useFetched(loadCatalogue, EMPTY_CATALOGUE);
  const tools = useFetched(loadTools, NO_TOOLS);
  // Held above the form: a save reloads the space list, the row's
  // `updated_at` changes, and the form remounts from it, which would lose a
  // "saved" note kept inside it before it was read.
  const [saved, setSaved] = useState(false);

  return (
    <div className="settings">
      <div className="settings__form">
        <SpaceForm
          // Start the form from the row being edited, and again when it changes underneath.
          key={`${space.id}:${space.updated_at}`}
          space={space}
          settings={settings}
          catalogue={catalogue.data}
          tools={tools.data}
          saved={saved}
          onEdited={() => {
            setSaved(false);
          }}
          onChanged={(changed) => {
            setSaved(changed !== null);
            onChanged(changed);
          }}
        />
        <Schedules key={space.id} space={space} settings={settings} onOpenRun={onOpenRun} />
        {!space.is_default && <DangerZone space={space} onChanged={onChanged} />}
      </div>
    </div>
  );
}

function SpaceForm({
  space,
  settings,
  catalogue,
  tools,
  saved,
  onEdited,
  onChanged,
}: SpaceSettingsViewProps & {
  catalogue: ProviderCatalogueResponse;
  tools: readonly ToolResponse[];
  saved: boolean;
  onEdited: () => void;
}) {
  const [opened] = useState<Form>(() => fromSpace(space));
  const [form, setForm] = useState<Form>(opened);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((prior) => ({ ...prior, [key]: value }));
    setErrors(({ [key]: _cleared, ...rest }) => rest);
    onEdited();
  };
  const errorFor = (field: string): string | null => errors[field] ?? null;

  const patch = diff(opened, form);
  const dirty = Object.keys(patch).length > 0;
  const inherited = settings?.settings;
  // The model belongs to the provider the space runs on: its own, or the app-wide one.
  const effectiveProvider = form.provider === "" ? (inherited?.provider ?? "") : form.provider;
  const providerEntry = catalogue.providers.find((entry) => entry.name === effectiveProvider);
  const knownModels = catalogue.models[effectiveProvider] ?? [];
  const freeText = providerEntry?.free_text_model ?? false;

  const save = async () => {
    setErrors({});
    for (const limit of LIMITS) {
      const text = form[limit].trim();
      if (text !== "" && (!/^\d+$/.test(text) || Number(text) < 1)) {
        setErrors({ [limit]: "A whole number of 1 or more, or blank to inherit." });
        return;
      }
    }
    if (form.model.trim() === "") {
      setErrors({ model: "A space needs a model: its runs use it unless an agent picks its own." });
      return;
    }
    if (form.run_cap.trim() !== "" && dollarsToMicros(form.run_cap) === null) {
      setErrors({ max_run_cost_micros: "Dollars, 0 or more, or blank to inherit." });
      return;
    }
    if (!dirty) return;
    setSaving(true);
    try {
      onChanged(await api.updateSpace(space.id, patch));
    } catch (failure) {
      if (failure instanceof ApiError) setErrors({ [failure.field ?? FORM]: failure.message });
      else setErrors({ [FORM]: failure instanceof Error ? failure.message : String(failure) });
    } finally {
      setSaving(false);
    }
  };

  const open = async () => {
    setOpening(null);
    try {
      await revealFolder(space.folder);
    } catch (failure) {
      setOpening(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <form
      className="settings__stack"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      data-testid="space-form"
    >
      {space.archived === true && (
        <div className="card card--notice" role="status">
          <h2 className="card__title">This space is archived</h2>
          <p>Its runs can still be opened. It starts no new ones and is left out of the switcher.</p>
        </div>
      )}

      <section className="settings__section">
        <h2>About this space</h2>
        <div className="editor__row">
          <label className="editor__field">
            <span>Name</span>
            <input
              type="text"
              value={form.name}
              maxLength={60}
              onChange={(changed) => {
                set("name", changed.target.value);
              }}
              aria-invalid={errorFor("name") !== null}
              data-testid="space-name"
            />
            <FieldError field="name" message={errorFor("name")} />
          </label>
        </div>
        <label className="editor__field">
          <span>Description</span>
          <textarea
            rows={2}
            value={form.description}
            onChange={(changed) => {
              set("description", changed.target.value);
            }}
            data-testid="space-description"
          />
        </label>
        <div className="editor__field">
          <span>Folder</span>
          <div className="settings__folder">
            <code className="settings__folder-path" data-testid="space-folder">
              {space.folder}
            </code>
            {revealAvailable() && (
              <button type="button" className="button button--small" onClick={() => void open()}>
                Open folder
              </button>
            )}
          </div>
          <span className="editor__hint editor__hint--field">
            Every file this space&apos;s agents read or write is inside this folder. It was created
            by AgentSpace and cannot be pointed elsewhere.
          </span>
          {opening !== null && (
            <p className="field-error" role="alert">
              {opening}
            </p>
          )}
        </div>
      </section>

      <section className="settings__section">
        <h2>Model</h2>
        <p className="settings__hint">
          Runs in this space use this model unless an agent picks its own. The provider is the
          app-wide one{inherited !== undefined && ` (${inherited.provider ?? "?"})`} unless this
          space chooses another.
        </p>
        <div className="editor__row">
          <label className="editor__field">
            <span>Provider</span>
            <select
              value={form.provider}
              onChange={(changed) => {
                // A model belongs to a provider, so the choice moves with it:
                // the new provider's first listed model, or blank to type.
                const provider = changed.target.value;
                const next = provider === "" ? (inherited?.provider ?? "") : provider;
                const entry = catalogue.providers.find((candidate) => candidate.name === next);
                set("provider", provider);
                set("model", entry?.default_model ?? catalogue.models[next]?.[0] ?? "");
              }}
              data-testid="space-provider"
            >
              <option value="">Inherit{inherited !== undefined && ` (${inherited.provider ?? "?"})`}</option>
              {catalogue.providers.map((entry) => (
                <option key={entry.name} value={entry.name}>
                  {entry.name}
                </option>
              ))}
            </select>
            <FieldError field="provider" message={errorFor("provider")} />
          </label>
          <label className="editor__field">
            <span>Model</span>
            {freeText ? (
              <input
                type="text"
                value={form.model}
                placeholder="the name you pulled, e.g. qwen3:4b"
                onChange={(changed) => {
                  set("model", changed.target.value);
                }}
                aria-invalid={errorFor("model") !== null}
                data-testid="space-model"
              />
            ) : (
              <select
                value={form.model}
                onChange={(changed) => {
                  set("model", changed.target.value);
                }}
                aria-invalid={errorFor("model") !== null}
                data-testid="space-model"
              >
                {form.model !== "" && !knownModels.includes(form.model) && (
                  <option value={form.model}>{form.model} (not in this provider&apos;s list)</option>
                )}
                {form.model === "" && <option value="">choose a model</option>}
                {knownModels.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            )}
            <FieldError field="model" message={errorFor("model")} />
          </label>
        </div>
      </section>

      <section className="settings__section">
        <h2>Limits and approvals</h2>
        <p className="settings__hint">Blank inherits the app-wide default.</p>
        <div className="editor__row">
          {LIMITS.map((limit) => (
            <label key={limit} className="editor__field editor__field--narrow">
              <span>{LIMIT_LABEL[limit]}</span>
              <input
                inputMode="numeric"
                value={form[limit]}
                placeholder={inherited === undefined ? "Inherit" : String(inherited[limit] ?? "")}
                onChange={(changed) => {
                  set(limit, changed.target.value);
                }}
                aria-invalid={errorFor(limit) !== null}
                data-testid={`space-${limit}`}
              />
              <FieldError field={limit} message={errorFor(limit)} />
            </label>
          ))}
          <label className="editor__field editor__field--narrow">
            <span>Dollars per run</span>
            <input
              inputMode="decimal"
              value={form.run_cap}
              placeholder={
                inherited === undefined
                  ? "Inherit"
                  : ((inherited.max_run_cost_micros ?? 0) / MICROS_PER_DOLLAR).toFixed(2)
              }
              onChange={(changed) => {
                set("run_cap", changed.target.value);
              }}
              aria-invalid={errorFor("max_run_cost_micros") !== null}
              data-testid="space-max_run_cost_micros"
            />
            <FieldError field="max_run_cost_micros" message={errorFor("max_run_cost_micros")} />
          </label>
        </div>

        <fieldset className="editor__tools">
          <legend>Calls that run without asking</legend>
          <label className="editor__tool">
            <input
              type="radio"
              name="approval-mode"
              checked={form.auto_approve === null}
              onChange={() => {
                set("auto_approve", null);
              }}
              data-testid="space-approvals-inherit"
            />
            <span className="editor__tool-description">
              Inherit the app-wide policy
              {inherited !== undefined &&
                ` (${(inherited.auto_approve ?? []).length === 0 ? "ask for everything" : (inherited.auto_approve ?? []).join(", ")})`}
            </span>
          </label>
          <label className="editor__tool">
            <input
              type="radio"
              name="approval-mode"
              checked={form.auto_approve !== null}
              onChange={() => {
                set("auto_approve", []);
              }}
              data-testid="space-approvals-own"
            />
            <span className="editor__tool-description">This space&apos;s own policy: nothing ticked asks for everything</span>
          </label>
          {form.auto_approve !== null && (
            <div className="editor__risks">
              {RISK_LEVELS.map((level) => {
                const allowedAbove = (inherited?.auto_approve ?? []).includes(level);
                const chosen = form.auto_approve?.includes(level) ?? false;
                return (
                  <label key={level} className="editor__tool">
                    <input
                      type="checkbox"
                      checked={chosen}
                      onChange={() => {
                        const current = form.auto_approve ?? [];
                        set(
                          "auto_approve",
                          chosen
                            ? current.filter((item) => item !== level)
                            : RISK_LEVELS.filter((item) => item === level || current.includes(item)),
                        );
                      }}
                      data-testid={`space-auto-${level}`}
                    />
                    <span className={`risk risk--${level}`}>{level}</span>
                    <span className="editor__tool-description">
                      {level === "low" && "reads inside the folder"}
                      {level === "medium" && "writes inside the folder, fetches a public URL"}
                      {level === "high" && "runs a shell command"}
                      {inherited !== undefined && chosen && !allowedAbove && ": not enabled app-wide, so still asks"}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          <p className="editor__hint">
            A space can narrow the app-wide policy but never widen it: a level ticked here that the
            app-wide policy does not include still stops for you.
          </p>
          <FieldError field="auto_approve" message={errorFor("auto_approve")} />
        </fieldset>

        <fieldset className="editor__tools" data-testid="space-tool-policies">
          <legend>Answers by tool</legend>
          <p className="editor__hint">
            The app-wide answer for each tool, and what this space makes of it. A space can only
            make an answer stricter: an always-allowed tool can be made to ask or be refused here,
            and a tool that asks can be refused.
          </p>
          {tools.length === 0 ? (
            <p className="editor__hint">The tool catalogue has not loaded.</p>
          ) : (
            <table className="policy-table">
              <tbody>
                {tools.map((tool) => {
                  const appWide: ToolPolicy = inherited?.tool_policies?.[tool.name] ?? "ask";
                  const choices = stricterChoices(appWide);
                  const own = form.tool_policies?.[tool.name];
                  return (
                    <tr key={tool.name}>
                      <th scope="row">
                        <code>{tool.name}</code>
                        <span className={`risk risk--${tool.risk}`}>{tool.risk}</span>
                      </th>
                      <td className="policy-table__description">{tool.description}</td>
                      <td>
                        <select
                          value={own ?? ""}
                          aria-label={`Answer for ${tool.name}`}
                          data-testid={`space-policy-${tool.name}`}
                          disabled={choices.length === 0}
                          onChange={(changed) => {
                            const { [tool.name]: _dropped, ...rest } = form.tool_policies ?? {};
                            const chosen = changed.target.value;
                            const next = chosen === "" ? rest : { ...rest, [tool.name]: chosen as ToolPolicy };
                            // Nothing of its own left: back to inheriting outright.
                            set("tool_policies", Object.keys(next).length === 0 ? null : next);
                          }}
                        >
                          <option value="">Inherit ({POLICY_WORD[appWide]})</option>
                          {choices.map((choice) => (
                            <option key={choice} value={choice}>
                              {choice === "ask" ? "Ask, by risk level" : "Never allow"}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <FieldError field="tool_policies" message={errorFor("tool_policies")} />
        </fieldset>
      </section>

      {errorFor(FORM) !== null && (
        <p className="editor__error editor__error--form" role="alert" data-testid="error-form">
          {errorFor(FORM)}
        </p>
      )}

      <div className="editor__actions settings__actions">
        {saved && !dirty && <span className="settings__saved">Saved. Applies to the next run.</span>}
        <button type="submit" className="button button--primary" disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save space"}
        </button>
      </div>

    </form>
  );
}

/** Archive or delete, kept apart from the form so a click here never submits it. */
function DangerZone({
  space,
  onChanged,
}: {
  space: SpaceResponse;
  onChanged: (space: SpaceResponse | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setArchived = async (archived: boolean) => {
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.updateSpace(space.id, { archived }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteSpace(space.id);
      onChanged(null);
    } catch (failure) {
      setConfirmingDelete(false);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings__section settings__section--danger" data-testid="danger-zone">
      <h2>Archive or delete</h2>
      <p className="settings__hint">
        Archiving keeps every run this space has had and takes it out of the switcher. Deleting
        is only allowed for a space with no runs (delete them one by one from Runs first, or
        archive instead) and removes its agents and schedules.
      </p>
      {error !== null && (
        <p className="editor__error editor__error--form" role="alert" data-testid="error-form">
          {error}
        </p>
      )}
      <div className="card__actions">
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => void setArchived(space.archived !== true)}
        >
          {space.archived === true ? "Unarchive" : "Archive this space"}
        </button>
        {confirmingDelete ? (
          <span className="roster__confirm">
            <span>Delete {space.name} and its agents?</span>
            <button
              type="button"
              className="button button--small button--danger"
              disabled={busy}
              onClick={() => void remove()}
            >
              Delete
            </button>
            <button
              type="button"
              className="button button--small"
              onClick={() => {
                setConfirmingDelete(false);
              }}
            >
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="button button--danger"
            disabled={busy}
            onClick={() => {
              setConfirmingDelete(true);
            }}
          >
            Delete this space…
          </button>
        )}
      </div>
    </section>
  );
}

function FieldError({ field, message }: { field: string; message: string | null }) {
  if (message === null) return null;
  return (
    <span className="editor__error" role="alert" data-testid={`error-${field}`}>
      {message}
    </span>
  );
}
