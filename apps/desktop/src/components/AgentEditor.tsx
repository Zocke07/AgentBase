import type {
  AgentDef,
  CreateAgentRequest,
  ProviderCatalogueResponse,
  RiskLevel,
  ToolResponse,
  UpdateAgentRequest,
} from "@agentbase/schemas";
import { useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { providerLabel } from "../lib/format";

import { ModelOptions } from "./ModelOptions";

/**
 * Create or edit an agent definition.
 *
 * Render refusals on server-named `{message, field}` inputs. Tool risks come
 * from gate-enforced `GET /tools`; selection grants definition permission, not
 * user permission. Models follow provider (free-text without a fixed list).
 * PATCH only form changes to preserve concurrent external toggles.
 */

export interface AgentEditorProps {
  /** Edited definition, or null to create. */
  agent: AgentDef | null;
  tools: readonly ToolResponse[];
  catalogue: ProviderCatalogueResponse;
  /** Current `inherit` resolution; null if settings unavailable. */
  workspaceProvider: string | null;
  /** Create from full form when `agent` is null. */
  onCreate: (body: CreateAgentRequest) => Promise<void>;
  /** PATCH only user-changed agent fields. */
  onPatch: (patch: UpdateAgentRequest) => Promise<void>;
  onCancel: () => void;
  /** Notify when form diverges from its opening state. */
  onDirtyChange?: (dirty: boolean) => void;
}

interface FormState {
  name: string;
  role: string;
  system_prompt: string;
  provider: string;
  model: string;
  allowed_tools: string[];
  auto_approve: RiskLevel[];
  max_steps: string;
  enabled: boolean;
}

/** Levels a policy may answer; high risk (run_shell) always asks a person, so
    a definition naming it would narrow nothing and is not offered. */
const RISK_LEVELS: readonly RiskLevel[] = ["low", "medium"];

const isRiskLevel = (value: string): value is RiskLevel =>
  (RISK_LEVELS as readonly string[]).includes(value);

const INHERIT = "";
/** The key for a message the server did not attribute to a field. */
const FORM = "__form__";

/** The form as the API wants it. */
function toRequest(form: FormState): CreateAgentRequest {
  const trimmed = form.max_steps.trim();
  return {
    name: form.name.trim(),
    role: form.role.trim(),
    system_prompt: form.system_prompt,
    provider: form.provider === INHERIT ? null : form.provider,
    model: form.model === INHERIT ? null : form.model,
    allowed_tools: form.allowed_tools,
    auto_approve: form.auto_approve,
    max_steps: trimmed === "" ? null : Number(trimmed),
    enabled: form.enabled,
  };
}

/** Fields changed from `before` to `after`, as PATCH body. */
function changedFields(before: CreateAgentRequest, after: CreateAgentRequest): UpdateAgentRequest {
  const patch: UpdateAgentRequest = {};
  for (const key of Object.keys(after) as (keyof CreateAgentRequest)[]) {
    const was = before[key];
    const now = after[key];
    const same = Array.isArray(was) && Array.isArray(now)
      ? was.length === now.length && was.every((item, index) => item === now[index])
      : was === now;
    if (!same) Object.assign(patch, { [key]: now });
  }
  return patch;
}

function initial(agent: AgentDef | null): FormState {
  return {
    name: agent?.name ?? "",
    role: agent?.role ?? "",
    system_prompt: agent?.system_prompt ?? "",
    provider: agent?.provider ?? INHERIT,
    model: agent?.model ?? INHERIT,
    allowed_tools: [...(agent?.allowed_tools ?? [])],
    auto_approve: (agent?.auto_approve ?? []).filter(isRiskLevel),
    // Empty inherits workspace cap; literal defaults can cause unsupplied-field
    // rejection when the workspace cap is lower.
    max_steps: agent?.max_steps === undefined ? "" : String(agent.max_steps),
    enabled: agent?.enabled ?? true,
  };
}

export function AgentEditor({
  agent,
  tools,
  catalogue,
  workspaceProvider,
  onCreate,
  onPatch,
  onCancel,
  onDirtyChange,
}: AgentEditorProps) {
  // Diff saves against opening snapshot.
  const [opened] = useState<FormState>(() => initial(agent));
  const [form, setForm] = useState<FormState>(opened);
  // Map field messages; `FORM` handles unattributed errors and preflight can
  // name multiple fields.
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const dirty = Object.keys(changedFields(toRequest(opened), toRequest(form))).length > 0;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    // Clear corrected-field errors immediately.
    setErrors(({ [key]: _cleared, ...rest }) => rest);
  };

  /** Inline input message or null. */
  const errorFor = (field: string): string | null => errors[field] ?? null;

  // Model behavior follows pinned provider or workspace provider.
  const effectiveProvider = form.provider === INHERIT ? workspaceProvider : form.provider;
  const providerEntry = catalogue.providers.find((entry) => entry.name === effectiveProvider);
  const freeText = providerEntry?.free_text_model ?? false;
  const knownModels = effectiveProvider === null ? [] : (catalogue.models[effectiveProvider] ?? []);
  // Keep out-of-list saved model visible instead of mislabeling it `inherit`.
  const strayModel =
    form.model !== INHERIT && !freeText && !knownModels.includes(form.model) ? form.model : null;

  const toggleRisk = (level: RiskLevel) => {
    setForm((current) => ({
      ...current,
      auto_approve: current.auto_approve.includes(level)
        ? current.auto_approve.filter((item) => item !== level)
        : RISK_LEVELS.filter((item) => item === level || current.auto_approve.includes(item)),
    }));
  };

  const toggleTool = (name: string) => {
    setForm((current) => ({
      ...current,
      allowed_tools: current.allowed_tools.includes(name)
        ? current.allowed_tools.filter((tool) => tool !== name)
        : [...current.allowed_tools, name],
    }));
  };

  const submit = async (submitted: SubmitEvent | { preventDefault: () => void }) => {
    submitted.preventDefault();
    setErrors({});

    // Block visibly incomplete forms locally; server remains authority for
    // uniqueness, caps, and tool catalog.
    const incomplete: Record<string, string> = {};
    if (form.name.trim() === "") incomplete.name = "Give the agent a name.";
    if (form.system_prompt.trim() === "") incomplete.system_prompt = "Give the agent a system prompt.";
    if (Object.keys(incomplete).length > 0) {
      setErrors(incomplete);
      return;
    }

    setSaving(true);
    const body = toRequest(form);

    // Send edits only when changed; avoid expected 400 for empty PATCH.
    if (agent !== null) {
      const patch = changedFields(toRequest(opened), body);
      if (Object.keys(patch).length === 0) {
        setSaving(false);
        onCancel();
        return;
      }
      try {
        await onPatch(patch);
      } catch (failure) {
        report(failure);
      } finally {
        setSaving(false);
      }
      return;
    }

    try {
      await onCreate(body);
    } catch (failure) {
      report(failure);
    } finally {
      setSaving(false);
    }
  };

  /** Put a save failure on the field the server named, or on the form. */
  function report(failure: unknown) {
    if (failure instanceof ApiError) {
      setErrors({ [failure.field ?? FORM]: failure.message });
    } else {
      setErrors({ [FORM]: failure instanceof Error ? failure.message : String(failure) });
    }
  }

  return (
    <form className="editor" onSubmit={(event) => void submit(event)} data-testid="agent-editor">
      <h2>{agent === null ? "New agent" : `Edit ${agent.name}`}</h2>

      {agent?.is_builtin === true && (
        <p className="editor__hint">
          A built-in definition. It can be edited and disabled, but not deleted.
        </p>
      )}

      <label className="editor__field">
        <span>Name</span>
        <input
          value={form.name}
          onChange={(changed) => {
            set("name", changed.target.value);
          }}
          aria-invalid={errorFor("name") !== null}
          aria-describedby={errorFor("name") === null ? undefined : "error-name"}
          data-testid="field-name"
        />
        {errorFor("name") !== null && (
          <span className="editor__error" id="error-name" role="alert" data-testid="error-name">
            {errorFor("name")}
          </span>
        )}
      </label>

      <label className="editor__field">
        <span>Role</span>
        <input
          value={form.role}
          onChange={(changed) => {
            set("role", changed.target.value);
          }}
          aria-invalid={errorFor("role") !== null}
          aria-describedby={errorFor("role") === null ? undefined : "error-role"}
          data-testid="field-role"
        />
        {errorFor("role") !== null && (
          <span className="editor__error" id="error-role" role="alert" data-testid="error-role">
            {errorFor("role")}
          </span>
        )}
      </label>

      <label className="editor__field">
        <span>System prompt</span>
        <textarea
          rows={8}
          value={form.system_prompt}
          onChange={(changed) => {
            set("system_prompt", changed.target.value);
          }}
          aria-invalid={errorFor("system_prompt") !== null}
          aria-describedby={errorFor("system_prompt") === null ? undefined : "error-system_prompt"}
          data-testid="field-system-prompt"
        />
        {errorFor("system_prompt") !== null && (
          <span
            className="editor__error"
            id="error-system_prompt"
            role="alert"
            data-testid="error-system_prompt"
          >
            {errorFor("system_prompt")}
          </span>
        )}
      </label>

      <div className="editor__row">
        <label className="editor__field">
          <span>Provider</span>
          <select
            value={form.provider}
            onChange={(changed) => {
              set("provider", changed.target.value);
            }}
            data-testid="field-provider"
          >
            <option value={INHERIT}>inherit the space default</option>
            {catalogue.providers.map((entry) => (
              <option key={entry.name} value={entry.name}>
                {providerLabel(entry.name)}
              </option>
            ))}
          </select>
          {errorFor("provider") !== null && (
            <span className="editor__error" role="alert" data-testid="error-provider">
              {errorFor("provider")}
            </span>
          )}
        </label>

        <label className="editor__field">
          <span>Model</span>
          {freeText ? (
            <input
              value={form.model}
              placeholder="inherit the space default"
              onChange={(changed) => {
                set("model", changed.target.value);
              }}
              aria-invalid={errorFor("model") !== null}
              data-testid="field-model"
            />
          ) : (
            <select
              value={form.model}
              onChange={(changed) => {
                set("model", changed.target.value);
              }}
              data-testid="field-model"
            >
              <option value={INHERIT}>inherit the space default</option>
              <ModelOptions
                entries={effectiveProvider === null ? undefined : catalogue.catalog[effectiveProvider]}
                models={knownModels}
              />
              {strayModel !== null && <option value={strayModel}>{strayModel}</option>}
            </select>
          )}
          {freeText && (
            <span className="editor__hint editor__hint--field">
              {effectiveProvider} serves whatever you have pulled: type the model name.
            </span>
          )}
          {strayModel !== null && (
            <span className="editor__hint editor__hint--field" data-testid="model-stray">
              {strayModel} is not one of {effectiveProvider}&apos;s models. A run would refuse it.
            </span>
          )}
          {errorFor("model") !== null && (
            <span className="editor__error" role="alert" data-testid="error-model">
              {errorFor("model")}
            </span>
          )}
        </label>

        <label className="editor__field editor__field--narrow">
          <span>Max steps</span>
          <input
            type="number"
            min={1}
            value={form.max_steps}
            placeholder="default (up to 20)"
            onChange={(changed) => {
              set("max_steps", changed.target.value);
            }}
            aria-invalid={errorFor("max_steps") !== null}
            aria-describedby={errorFor("max_steps") === null ? undefined : "error-max_steps"}
            data-testid="field-max-steps"
          />
          {errorFor("max_steps") !== null && (
            <span className="editor__error" id="error-max_steps" role="alert" data-testid="error-max_steps">
              {errorFor("max_steps")}
            </span>
          )}
        </label>
      </div>

      <fieldset className="editor__tools">
        <legend>Tools this agent may call</legend>
        <p className="editor__hint">
          An allowlist: an agent can call nothing that is not ticked here. Ticking
          a tool is permission from the definition, not from you: every call still
          passes the approval gate, and runs on its own only when your policy
          answers it, by risk level, by tool and, for a fetch, by site. A shell
          command always asks.
        </p>

        {tools.map((tool) => (
          <label key={tool.name} className="editor__tool">
            <input
              type="checkbox"
              checked={form.allowed_tools.includes(tool.name)}
              onChange={() => {
                toggleTool(tool.name);
              }}
              data-testid={`tool-${tool.name}`}
            />
            <span className="editor__tool-name">{tool.name}</span>
            {/* The risk level, beside the checkbox, at the moment of ticking. */}
            <span className={`risk risk--${tool.risk}`}>{tool.risk}</span>
            <span className="editor__tool-description">{tool.description}</span>
            {!tool.available && <span className="editor__tool-missing">not implemented</span>}
          </label>
        ))}

        {errorFor("allowed_tools") !== null && (
          <span className="editor__error" role="alert" data-testid="error-allowed_tools">
            {errorFor("allowed_tools")}
          </span>
        )}
      </fieldset>

      <fieldset className="editor__tools">
        <legend>Calls this agent may make without asking</legend>
        <p className="editor__hint">
          Narrows the space policy for this agent only: it can never widen it.
          Nothing ticked means the space policy applies as it is.
        </p>
        <div className="editor__risks">
          {RISK_LEVELS.map((level) => (
            <label key={level} className="editor__tool">
              <input
                type="checkbox"
                checked={form.auto_approve.includes(level)}
                onChange={() => {
                  toggleRisk(level);
                }}
                data-testid={`auto-${level}`}
              />
              <span className={`risk risk--${level}`}>{level}</span>
              <span className="editor__tool-description">
                {level === "low" && "reads inside the space folder"}
                {level === "medium" && "writes inside the space folder, fetches from a listed site"}
              </span>
            </label>
          ))}
        </div>
        {errorFor("auto_approve") !== null && (
          <span className="editor__error" role="alert" data-testid="error-auto_approve">
            {errorFor("auto_approve")}
          </span>
        )}
      </fieldset>

      <label className="editor__checkbox">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(changed) => {
            set("enabled", changed.target.checked);
          }}
          data-testid="field-enabled"
        />
        <span>Available to the supervisor</span>
      </label>

      {errorFor(FORM) !== null && (
        <p className="editor__error editor__error--form" role="alert" data-testid="error-form">
          {errorFor(FORM)}
        </p>
      )}

      <div className="editor__actions">
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="button button--primary" disabled={saving}>
          {agent === null ? "Create agent" : "Save changes"}
        </button>
      </div>
    </form>
  );
}
