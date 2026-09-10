import type { AgentDef, CreateAgentRequest, ToolResponse } from "@agentspace/schemas";
import { useState } from "react";

import { ApiError } from "../lib/api";


/**
 * Create or edit one agent definition — §5 Phase 7's `AgentEditor.tsx`.
 *
 * Two requirements from the spec shape this whole component.
 *
 * **"Surface the API's validation errors inline on the offending field — never a
 * toast that loses which field was wrong."** Phase 5 built the backend half of
 * this: every rejection is a 4xx carrying `{message, field}`, and Phase 6 kept
 * it that way. So a failure here is rendered against the input named by the
 * server, and only falls back to a form-level message when the server did not
 * name one. Nothing guesses which field is at fault from the message text.
 *
 * **"Tool checkboxes show each tool's risk level next to it, so the consequence
 * of ticking `run_shell` is visible at the moment of ticking it."** The risk
 * comes from `GET /tools`, which reads the same catalogue the approval gate
 * enforces against — a hardcoded list here would drift from the thing that
 * actually decides.
 *
 * Note what an allowlist does *not* do: ticking `run_shell` grants permission
 * from the definition, never from the user. Every call still stops at the
 * approval gate (§1 constraint 5), which is why the hint below says so.
 */

export interface AgentEditorProps {
  /** The definition being edited, or null to create a new one. */
  agent: AgentDef | null;
  tools: readonly ToolResponse[];
  providers: readonly string[];
  models: readonly string[];
  onSave: (body: CreateAgentRequest) => Promise<void>;
  onCancel: () => void;
}

interface FormState {
  name: string;
  role: string;
  system_prompt: string;
  provider: string;
  model: string;
  allowed_tools: string[];
  max_steps: string;
  enabled: boolean;
}

const INHERIT = "";

function initial(agent: AgentDef | null): FormState {
  return {
    name: agent?.name ?? "",
    role: agent?.role ?? "",
    system_prompt: agent?.system_prompt ?? "",
    provider: agent?.provider ?? INHERIT,
    model: agent?.model ?? INHERIT,
    allowed_tools: [...(agent?.allowed_tools ?? [])],
    // Empty means "whatever this workspace allows". Defaulting to a literal
    // here is the Phase 5 bug: a definition rejected for a field the caller
    // never supplied, whenever the workspace cap sits below that literal.
    max_steps: agent?.max_steps === undefined ? "" : String(agent.max_steps),
    enabled: agent?.enabled ?? true,
  };
}

export function AgentEditor({
  agent,
  tools,
  providers,
  models,
  onSave,
  onCancel,
}: AgentEditorProps) {
  const [form, setForm] = useState<FormState>(() => initial(agent));
  const [fieldError, setFieldError] = useState<{ field: string | null; message: string } | null>(
    null,
  );
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    // Clear the error on the field being corrected, so the message goes away
    // when the user acts on it rather than only on the next submit.
    if (fieldError?.field === key) setFieldError(null);
  };

  /** The inline message for one input, or null. */
  const errorFor = (field: string): string | null =>
    fieldError !== null && fieldError.field === field ? fieldError.message : null;

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
    setSaving(true);
    setFieldError(null);

    const trimmed = form.max_steps.trim();
    const body: CreateAgentRequest = {
      name: form.name.trim(),
      role: form.role.trim(),
      system_prompt: form.system_prompt,
      provider: form.provider === INHERIT ? null : form.provider,
      model: form.model === INHERIT ? null : form.model,
      allowed_tools: form.allowed_tools,
      max_steps: trimmed === "" ? null : Number(trimmed),
      enabled: form.enabled,
    };

    try {
      await onSave(body);
    } catch (failure) {
      if (failure instanceof ApiError) {
        setFieldError({ field: failure.field, message: failure.message });
      } else {
        setFieldError({
          field: null,
          message: failure instanceof Error ? failure.message : String(failure),
        });
      }
    } finally {
      setSaving(false);
    }
  };

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
          data-testid="field-role"
        />
        {errorFor("role") !== null && (
          <span className="editor__error" role="alert" data-testid="error-role">
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
          data-testid="field-system-prompt"
        />
        {errorFor("system_prompt") !== null && (
          <span className="editor__error" role="alert" data-testid="error-system_prompt">
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
            <option value={INHERIT}>inherit the workspace default</option>
            {providers.map((name) => (
              <option key={name} value={name}>
                {name}
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
          <select
            value={form.model}
            onChange={(changed) => {
              set("model", changed.target.value);
            }}
            data-testid="field-model"
          >
            <option value={INHERIT}>inherit the workspace default</option>
            {models.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
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
            placeholder="workspace limit"
            onChange={(changed) => {
              set("max_steps", changed.target.value);
            }}
            aria-invalid={errorFor("max_steps") !== null}
            data-testid="field-max-steps"
          />
          {errorFor("max_steps") !== null && (
            <span className="editor__error" role="alert" data-testid="error-max_steps">
              {errorFor("max_steps")}
            </span>
          )}
        </label>
      </div>

      <fieldset className="editor__tools">
        <legend>Tools this agent may call</legend>
        <p className="editor__hint">
          An allowlist: an agent can call nothing that is not ticked here. Ticking
          a tool is permission from the definition, not from you — every call still
          stops at the approval gate unless your policy pre-approves its risk level.
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

      {fieldError !== null && fieldError.field === null && (
        <p className="editor__error editor__error--form" role="alert" data-testid="error-form">
          {fieldError.message}
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
