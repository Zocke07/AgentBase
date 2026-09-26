import type {
  ChannelIdentity,
  ChannelStatusResponse,
  ChatGPTAuthResponse,
  ChatGPTRuntimeResponse,
  ProviderCatalogueResponse,
  RiskLevel,
  SettingsResponse,
  SpaceResponse,
  ToolPolicy,
  ToolResponse,
  UpdateSettingsRequest,
  VerifyResponse,
  WorkspaceSettings,
} from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import { openChatGPTAuthUrl } from "../lib/external";
import { revealAvailable, revealFolder } from "../lib/folder";
import { clearSecret, keychainAvailable, setSecret } from "../lib/keychain";
import { restartApp, restartAvailable } from "../lib/shell";
import { THEMES, useThemeStore, type Theme } from "../lib/theme";
import { useFetched } from "../state/useFetched";

import { Skeleton } from "./Skeleton";

/**
 * The settings screen: every workspace setting, plus keys.
 *
 * Keys go to the OS keychain, not to the sidecar (§1 constraint 4): the
 * webview writes an entry the shell reads at the next spawn, so every key row
 * says "restart to apply" and the section offers the restart itself once a
 * key has changed, and which keys are set comes from `configured_secrets` by
 * name only. Save is a PATCH of what changed, diffed
 * against what the screen loaded, and a refusal lands on the field the
 * server named. Money is dollars here and integer micros on the wire.
 */

export interface SettingsViewProps {
  /** Called with the sidecar's reply after a save, so the shell can refresh. */
  onSaved: (settings: SettingsResponse) => void;
  /** Every space, for choosing where a chat command's runs happen. */
  spaces?: readonly SpaceResponse[];
  /** Show the first-run tour again; absent where the shell has none. */
  onReplayTour?: (() => void) | undefined;
}

interface Form {
  provider: string;
  openai_access: "api_key" | "chatgpt";
  ollama_base_url: string;
  /** Dollars, as typed. */
  cap: string;
  max_steps_per_agent: string;
  max_agents_per_run: string;
  max_run_seconds: string;
  /** Dollars per run, as typed; "0" lifts the ceiling. */
  run_cap: string;
  auto_approve: RiskLevel[];
  /** Per-tool answers; a tool absent here is "ask", decided by the risk levels. */
  tool_policies: Record<string, ToolPolicy>;
  discord_enabled: boolean;
  channel_identities: ChannelIdentity[];
  channel_approvals: "dashboard_only" | "originator";
  /** The space a chat command's runs happen in; "" is the default space. */
  channel_space_id: string;
}

const RISK_LEVELS: readonly RiskLevel[] = ["low", "medium", "high"];
const MICROS_PER_DOLLAR = 1_000_000;
/** The key for a refusal the server did not attribute to a field. */
const FORM = "__form__";

const EMPTY_CATALOGUE: ProviderCatalogueResponse = { providers: [], models: {} };
const NO_CHANNELS: ChannelStatusResponse[] = [];
const NO_TOOLS: ToolResponse[] = [];

/** The three answers a tool can have, in the order the select lists them. */
const TOOL_POLICIES: readonly { value: ToolPolicy; label: string }[] = [
  { value: "ask", label: "Ask, by risk level" },
  { value: "allow", label: "Always allow" },
  { value: "deny", label: "Never allow" },
];

function fromSettings(settings: WorkspaceSettings): Form {
  return {
    provider: settings.provider ?? "",
    openai_access: settings.openai_access ?? "api_key",
    ollama_base_url: settings.ollama_base_url ?? "",
    cap: ((settings.monthly_cap_micros ?? 0) / MICROS_PER_DOLLAR).toFixed(2),
    max_steps_per_agent: String(settings.max_steps_per_agent ?? ""),
    max_agents_per_run: String(settings.max_agents_per_run ?? ""),
    max_run_seconds: String(settings.max_run_seconds ?? ""),
    run_cap: ((settings.max_run_cost_micros ?? 0) / MICROS_PER_DOLLAR).toFixed(2),
    auto_approve: [...(settings.auto_approve ?? [])],
    tool_policies: { ...(settings.tool_policies ?? {}) },
    discord_enabled: settings.discord_enabled ?? false,
    channel_identities: [...(settings.channel_identities ?? [])],
    channel_approvals: settings.channel_approvals ?? "dashboard_only",
    channel_space_id: settings.channel_space_id ?? "",
  };
}

/**
 * A field the generated type promises and an older sidecar does not send.
 * Typed as it may arrive, so the fallback beside it is a real branch.
 */
function maybeAbsent<T>(value: T): T | undefined {
  return value;
}

/** Dollars typed by a person → whole micros. Never a float on the wire. */
function dollarsToMicros(dollars: string): number | null {
  const parsed = Number(dollars.trim());
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * MICROS_PER_DOLLAR);
}

/** The request for what differs between `opened` and `form`. */
function diff(opened: Form, form: Form): UpdateSettingsRequest {
  const patch: UpdateSettingsRequest = {};
  if (form.provider !== opened.provider) patch.provider = form.provider;
  if (form.openai_access !== opened.openai_access) patch.openai_access = form.openai_access;
  if (form.ollama_base_url !== opened.ollama_base_url) patch.ollama_base_url = form.ollama_base_url;
  const cap = dollarsToMicros(form.cap);
  if (form.cap !== opened.cap && cap !== null) patch.monthly_cap_micros = cap;
  for (const key of ["max_steps_per_agent", "max_agents_per_run", "max_run_seconds"] as const) {
    if (form[key] !== opened[key]) patch[key] = Number(form[key]);
  }
  const runCap = dollarsToMicros(form.run_cap);
  if (form.run_cap !== opened.run_cap && runCap !== null) patch.max_run_cost_micros = runCap;
  if (form.auto_approve.join() !== opened.auto_approve.join()) patch.auto_approve = form.auto_approve;
  if (JSON.stringify(form.tool_policies) !== JSON.stringify(opened.tool_policies)) {
    patch.tool_policies = form.tool_policies;
  }
  if (form.discord_enabled !== opened.discord_enabled) patch.discord_enabled = form.discord_enabled;
  if (JSON.stringify(form.channel_identities) !== JSON.stringify(opened.channel_identities)) {
    patch.channel_identities = form.channel_identities;
  }
  if (form.channel_approvals !== opened.channel_approvals) patch.channel_approvals = form.channel_approvals;
  // An empty string means the default space; null cannot travel in this PATCH.
  if (form.channel_space_id !== opened.channel_space_id) patch.channel_space_id = form.channel_space_id;
  return patch;
}

/** What each stored secret is, in words; the stored name is shown beneath. */
const KEY_LABELS: Readonly<Record<string, string>> = {
  anthropic_api_key: "Anthropic API key",
  openai_api_key: "OpenAI API key",
  discord_bot_token: "Discord bot token",
};

/** The page's sections, in order, for the "On this page" bar. */
const SETTINGS_SECTIONS: readonly { id: string; label: string }[] = [
  { id: "settings-provider", label: "Provider" },
  { id: "settings-keys", label: "Keys" },
  { id: "settings-budget", label: "Budget" },
  { id: "settings-limits", label: "Limits" },
  { id: "settings-channels", label: "Chat" },
  { id: "settings-appearance", label: "Appearance" },
  { id: "settings-about", label: "About" },
];

export function SettingsView({ onSaved, spaces = [], onReplayTour }: SettingsViewProps) {
  const loadSettings = useCallback(() => api.getSettings(), []);
  const loadCatalogue = useCallback(() => api.listProviders(), []);
  const loadChannels = useCallback(() => api.getChannels(), []);
  const loadTools = useCallback(() => api.listTools(), []);
  const current = useFetched<SettingsResponse | null>(loadSettings, null);
  const catalogue = useFetched(loadCatalogue, EMPTY_CATALOGUE);
  const channels = useFetched(loadChannels, NO_CHANNELS);
  const tools = useFetched(loadTools, NO_TOOLS);
  // The reply to a save is the whole settings document; the form starts from it next.
  const [replied, setReplied] = useState<SettingsResponse | null>(null);
  const [saved, setSaved] = useState(false);
  const loaded = replied ?? current.data;

  return (
    <div className="settings">
      {current.error !== null && (
        <p className="settings__error" role="alert">
          {current.error}
        </p>
      )}
      {loaded === null ? (
        current.loading ? (
          <div className="settings__form">
            <Skeleton label="Loading your settings" title lines={5} />
          </div>
        ) : (
          <p className="settings__loading">Settings could not be read.</p>
        )
      ) : (
        <SettingsForm
          // Start the form from whatever copy is newest.
          key={JSON.stringify(loaded.settings)}
          loaded={loaded}
          spaces={spaces}
          catalogue={catalogue.data}
          catalogueError={catalogue.error}
          channels={channels.data}
          tools={tools.data}
          saved={saved}
          onEdited={() => {
            setSaved(false);
          }}
          onSaved={(reply) => {
            setReplied(reply);
            setSaved(true);
            onSaved(reply);
            channels.reload();
          }}
          onReplayTour={onReplayTour}
        />
      )}
    </div>
  );
}

interface SettingsFormProps {
  loaded: SettingsResponse;
  spaces: readonly SpaceResponse[];
  catalogue: ProviderCatalogueResponse;
  catalogueError: string | null;
  channels: readonly ChannelStatusResponse[];
  /** The tool catalogue, for the per-tool answers. */
  tools: readonly ToolResponse[];
  /** Whether the last save has not been edited since; shown beside the button. */
  saved: boolean;
  onReplayTour?: (() => void) | undefined;
  onEdited: () => void;
  onSaved: (settings: SettingsResponse) => void;
}

function SettingsForm({
  loaded,
  spaces,
  catalogue,
  catalogueError,
  channels,
  tools,
  saved,
  onReplayTour,
  onEdited,
  onSaved,
}: SettingsFormProps) {
  const [opened] = useState<Form>(() => fromSettings(loaded.settings));
  const [form, setForm] = useState<Form>(opened);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);
  const [verified, setVerified] = useState<VerifyResponse | "checking" | null>(null);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((prior) => ({ ...prior, [key]: value }));
    setErrors(({ [key]: _cleared, ...rest }) => rest);
    onEdited();
  };
  const errorFor = (field: string): string | null => errors[field] ?? null;

  const providerEntry = catalogue.providers.find((entry) => entry.name === form.provider);
  const freeText = providerEntry?.free_text_model ?? false;

  const patch = diff(opened, form);
  const dirty = Object.keys(patch).length > 0;

  const save = async () => {
    setErrors({});
    if (dollarsToMicros(form.cap) === null) {
      setErrors({ monthly_cap_micros: "Enter the cap in dollars, zero or more." });
      return;
    }
    if (!dirty) return;
    setSaving(true);
    try {
      onSaved(await api.updateSettings(patch));
    } catch (failure) {
      if (failure instanceof ApiError) setErrors({ [failure.field ?? FORM]: failure.message });
      else setErrors({ [FORM]: failure instanceof Error ? failure.message : String(failure) });
    } finally {
      setSaving(false);
    }
  };

  const check = async () => {
    setVerified("checking");
    try {
      setVerified(await api.verifySettings());
    } catch (failure) {
      setVerified({ ok: false, reason: failure instanceof Error ? failure.message : String(failure) });
    }
  };

  return (
    <form
      className="settings__form"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      data-testid="settings-form"
    >
      {/* Jump to a section: the page is long, and the first thing most people
          come here for (a key) should be one click away. */}
      <nav className="settings__nav" aria-label="Settings sections">
        {SETTINGS_SECTIONS.map((entry) => (
          <a key={entry.id} href={`#${entry.id}`} className="settings__nav-link">
            {entry.label}
          </a>
        ))}
      </nav>

      <h2 className="settings__group">Get started</h2>

      {/* --- provider ------------------------------------------------------ */}
      <section className="settings__section" id="settings-provider">
        <h2>Provider</h2>
        <p className="settings__hint">
          Which company&apos;s AI your agents use. Each space picks the exact model in Space settings,
          and an agent can pick its own.
        </p>
        {catalogueError !== null && (
          <p className="settings__error" role="alert">
            {catalogueError}
          </p>
        )}
        <div className="editor__row">
          <label className="editor__field">
            <span>Provider</span>
            <select
              value={form.provider}
              onChange={(changed) => {
                set("provider", changed.target.value);
              }}
              aria-invalid={errorFor("provider") !== null}
              data-testid="setting-provider"
            >
              {catalogue.providers.map((entry) => (
                <option key={entry.name} value={entry.name}>
                  {entry.name}
                  {entry.requires_key ? "" : " (no key needed)"}
                </option>
              ))}
            </select>
            <FieldError field="provider" message={errorFor("provider")} />
          </label>
        </div>

        {freeText && (
          <label className="editor__field">
            <span>Ollama address</span>
            <input
              value={form.ollama_base_url}
              onChange={(changed) => {
                set("ollama_base_url", changed.target.value);
              }}
              aria-invalid={errorFor("ollama_base_url") !== null}
              data-testid="setting-ollama-url"
            />
            <FieldError field="ollama_base_url" message={errorFor("ollama_base_url")} />
          </label>
        )}

        {form.provider === "openai" && (
          <fieldset className="editor__tools" data-testid="openai-access">
            <legend>OpenAI access</legend>
            <label className="editor__tool">
              <input
                type="radio"
                name="openai_access"
                checked={form.openai_access === "api_key"}
                onChange={() => {
                  set("openai_access", "api_key");
                }}
                data-testid="setting-openai-api-key"
              />
              <span>API key</span>
              <span className="editor__tool-description">Usage-based API billing</span>
            </label>
            <label className="editor__tool">
              <input
                type="radio"
                name="openai_access"
                checked={form.openai_access === "chatgpt"}
                onChange={() => {
                  set("openai_access", "chatgpt");
                }}
                data-testid="setting-openai-chatgpt"
              />
              <span>ChatGPT subscription</span>
              <span className="editor__tool-description">Your personal monthly plan</span>
            </label>
            <p className="settings__hint">
              Both modes use the same OpenAI provider, the spaces' model choices, agent loop, tool approvals,
              event log, and limits. Subscription calls count at the model&apos;s API-equivalent price
              only for AgentBase&apos;s safety cap; they are not API charges.
            </p>
            {form.openai_access === "chatgpt" && <ChatGPTAccount />}
            <FieldError field="openai_access" message={errorFor("openai_access")} />
          </fieldset>
        )}

        <div className="settings__verify">
          <button type="button" className="button button--small" onClick={() => void check()}>
            Check
          </button>
          <span className="settings__hint">
            Asks the sidecar whether the <em>saved</em> settings can build a provider: no model is called.
          </span>
          {verified !== null && (
            <p
              className={`settings__verify-result${verified !== "checking" && !verified.ok ? " settings__verify-result--bad" : ""}`}
              data-testid="verify-result"
            >
              {verified === "checking"
                ? "Checking…"
                : verified.ok
                  ? `Ready: ${verified.provider ?? ""}`
                  : (verified.reason ?? "The current settings cannot build a provider.")}
            </p>
          )}
        </div>
      </section>

      {/* --- keys ---------------------------------------------------------- */}
      <section className="settings__section" id="settings-keys" data-testid="keys" data-tour="keys">
        <h2>Keys</h2>
        <p className="settings__hint">
          An API key lets AgentBase use your account with the provider above. It is kept in your
          computer&apos;s secure password store, never in a file, and read when AgentBase starts: after
          adding or changing one, restart AgentBase with the button that appears. Restarting stops a
          run that is still going.
        </p>
        <KeyRows loaded={loaded} />
      </section>

      <h2 className="settings__group">Spending and safety</h2>

      {/* --- budget ---------------------------------------------------------- */}
      <section className="settings__section" id="settings-budget">
        <h2>Monthly budget</h2>
        <p className="settings__hint">
          One spending limit for the whole app each month, across every space. A run that would go over
          it stops before it asks the AI anything more.
        </p>
        <div className="editor__row">
          <label className="editor__field editor__field--narrow">
            <span>Monthly cap (USD)</span>
            <input
              inputMode="decimal"
              value={form.cap}
              onChange={(changed) => {
                set("cap", changed.target.value);
                setErrors(({ monthly_cap_micros: _cleared, ...rest }) => rest);
              }}
              aria-invalid={errorFor("monthly_cap_micros") !== null}
              data-testid="setting-cap"
            />
            <FieldError field="monthly_cap_micros" message={errorFor("monthly_cap_micros")} />
          </label>
        </div>
      </section>

      {/* --- limits and the approval policy ------------------------------- */}
      <section className="settings__section" id="settings-limits">
        <h2>Limits and approvals</h2>
        <p className="settings__hint">
          How long and how much one run may do, and which actions may happen without asking you first.
          Each space can change the limits for itself, and can make approvals stricter but never looser.
        </p>
        <div className="editor__row">
          <NumberField
            label="Steps per agent"
            field="max_steps_per_agent"
            value={form.max_steps_per_agent}
            error={errorFor("max_steps_per_agent")}
            onChange={(value) => {
              set("max_steps_per_agent", value);
            }}
            testId="setting-max-steps"
          />
          <NumberField
            label="Agents per run"
            field="max_agents_per_run"
            value={form.max_agents_per_run}
            error={errorFor("max_agents_per_run")}
            onChange={(value) => {
              set("max_agents_per_run", value);
            }}
            testId="setting-max-agents"
          />
          <NumberField
            label="Seconds per run"
            field="max_run_seconds"
            value={form.max_run_seconds}
            error={errorFor("max_run_seconds")}
            onChange={(value) => {
              set("max_run_seconds", value);
            }}
            testId="setting-max-seconds"
          />
          <label className="editor__field editor__field--narrow">
            <span>Dollars per run</span>
            <input
              inputMode="decimal"
              value={form.run_cap}
              onChange={(changed) => {
                set("run_cap", changed.target.value);
                setErrors(({ max_run_cost_micros: _cleared, ...rest }) => rest);
              }}
              aria-invalid={errorFor("max_run_cost_micros") !== null}
              data-testid="setting-run-cap"
            />
            <span className="editor__hint">
              A run that has spent this stops where it stands; 0 leaves only the monthly cap.
            </span>
            <FieldError field="max_run_cost_micros" message={errorFor("max_run_cost_micros")} />
          </label>
        </div>

        <fieldset className="editor__tools">
          <legend>Calls that run without asking</legend>
          <p className="editor__hint">
            The app-wide policy for unattended runs. Nothing ticked means every tool call stops for
            you; a space or agent definition can narrow this further but never widen it.
          </p>
          <div className="editor__risks">
            {RISK_LEVELS.map((level) => (
              <label key={level} className="editor__tool">
                <input
                  type="checkbox"
                  checked={form.auto_approve.includes(level)}
                  onChange={() => {
                    set(
                      "auto_approve",
                      form.auto_approve.includes(level)
                        ? form.auto_approve.filter((item) => item !== level)
                        : RISK_LEVELS.filter((item) => item === level || form.auto_approve.includes(item)),
                    );
                  }}
                  data-testid={`setting-auto-${level}`}
                />
                <span className={`risk risk--${level}`}>{level}</span>
                <span className="editor__tool-description">
                  {level === "low" && "reads inside the workspace"}
                  {level === "medium" && "writes inside the workspace, fetches a public URL"}
                  {level === "high" && "runs a shell command"}
                </span>
              </label>
            ))}
          </div>
          <FieldError field="auto_approve" message={errorFor("auto_approve")} />
        </fieldset>

        <fieldset className="editor__tools" data-testid="setting-tool-policies">
          <legend>Answers by tool</legend>
          <p className="editor__hint">
            Two ways to say what runs without asking. The levels above answer by how risky a call
            is; this table answers by tool, and its answer wins. On <b>Ask</b>, the levels decide.
            On <b>Always allow</b>, the tool never asks, even with its level unticked. On{" "}
            <b>Never allow</b>, it is refused every time, even with its level ticked. For example,
            with <b>low</b> ticked, <code>write_file</code> on Always allow and <code>run_shell</code>{" "}
            on Never allow: reads and writes run on their own, a shell command is refused, and a web
            fetch (medium, unticked) still asks. A space can only make an answer stricter.
          </p>
          {tools.length === 0 ? (
            <p className="editor__hint">The tool catalogue has not loaded.</p>
          ) : (
            <table className="policy-table">
              <tbody>
                {tools.map((tool) => (
                  <tr key={tool.name}>
                    <th scope="row">
                      <code>{tool.name}</code>
                      <span className={`risk risk--${tool.risk}`}>{tool.risk}</span>
                    </th>
                    <td className="policy-table__description">{tool.description}</td>
                    <td>
                      <select
                        value={form.tool_policies[tool.name] ?? "ask"}
                        aria-label={`Answer for ${tool.name}`}
                        data-testid={`setting-policy-${tool.name}`}
                        onChange={(changed) => {
                          const { [tool.name]: _dropped, ...rest } = form.tool_policies;
                          const chosen = changed.target.value as ToolPolicy;
                          set("tool_policies", chosen === "ask" ? rest : { ...rest, [tool.name]: chosen });
                        }}
                      >
                        {TOOL_POLICIES.map((choice) => (
                          <option key={choice.value} value={choice.value}>
                            {choice.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <FieldError field="tool_policies" message={errorFor("tool_policies")} />
        </fieldset>
      </section>

      <h2 className="settings__group">More</h2>

      {/* --- channels -------------------------------------------------------- */}
      <section className="settings__section" id="settings-channels">
        <h2>Chat channels</h2>
        <div className="settings__channels">
          {(["discord"] as const).map((channel) => {
            const status = channels.find((entry) => entry.channel === channel);
            const enabledKey = `${channel}_enabled` as const;
            return (
              <div key={channel} className="settings__channel" data-testid={`channel-${channel}`}>
                <label className="editor__checkbox">
                  <input
                    type="checkbox"
                    checked={form[enabledKey]}
                    onChange={(changed) => {
                      set(enabledKey, changed.target.checked);
                    }}
                    data-testid={`setting-${channel}-enabled`}
                  />
                  <span>Enable {channel}</span>
                </label>
                {status !== undefined && (
                  <div className="settings__channel-status">
                    <span className={`status status--${status.running ? "running" : status.enabled ? "failed" : "pending"}`}>
                      {status.running ? "running" : status.enabled ? "not running" : "off"}
                    </span>
                    {!status.configured && <span> · no token set</span>}
                    {status.failures > 0 && <span> · {status.failures} failures</span>}
                    {status.last_error !== null && status.last_error !== undefined && (
                      <p className="settings__channel-error">{status.last_error}</p>
                    )}
                    {status.refused !== undefined && status.refused.length > 0 && (
                      <p className="settings__hint">Refused: {status.refused.join(", ")}</p>
                    )}
                  </div>
                )}
                <FieldError field={enabledKey} message={errorFor(enabledKey)} />
              </div>
            );
          })}
        </div>

        <IdentityList
          identities={form.channel_identities}
          error={errorFor("channel_identities")}
          onChange={(identities) => {
            set("channel_identities", identities);
          }}
        />

        <fieldset className="editor__tools">
          <legend>Who may answer an approval</legend>
          {(
            [
              ["dashboard_only", "Only this window: the question is shown in chat, answered here."],
              ["originator", "Also the chat user who started the run."],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="editor__tool">
              <input
                type="radio"
                name="channel_approvals"
                checked={form.channel_approvals === value}
                onChange={() => {
                  set("channel_approvals", value);
                }}
                data-testid={`setting-approvals-${value}`}
              />
              <span className="editor__tool-description">{label}</span>
            </label>
          ))}
          <FieldError field="channel_approvals" message={errorFor("channel_approvals")} />
        </fieldset>

        <label className="editor__field editor__field--narrow">
          <span>Where a chat command runs</span>
          <select
            value={form.channel_space_id}
            onChange={(changed) => {
              set("channel_space_id", changed.target.value);
            }}
            data-testid="setting-channel-space"
          >
            {spaces
              .filter((space) => space.archived !== true)
              .map((space) => (
                <option key={space.id} value={space.is_default ? "" : space.id}>
                  {space.name}
                  {space.is_default ? " (default)" : ""}
                </option>
              ))}
          </select>
          <FieldError field="channel_space_id" message={errorFor("channel_space_id")} />
        </label>
      </section>

      <AppearanceSection />

      <AboutSection version={loaded.version} dataDir={loaded.data_dir} onReplayTour={onReplayTour} />

      {errorFor(FORM) !== null && (
        <p className="editor__error editor__error--form" role="alert" data-testid="error-form">
          {errorFor(FORM)}
        </p>
      )}

      <div className="editor__actions settings__actions">
        {dirty && !saving && <span className="settings__unsaved">You have unsaved changes.</span>}
        {saved && !dirty && (
          <span className="settings__saved" role="status">
            Saved. New runs will use this.
          </span>
        )}
        <button type="submit" className="button button--primary" disabled={saving || !dirty} aria-busy={saving}>
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>
    </form>
  );
}

/** The version that answered, where its data lives, and the tour again. */
function AboutSection({
  version,
  dataDir,
  onReplayTour,
}: {
  version: string;
  dataDir: string;
  onReplayTour: (() => void) | undefined;
}) {
  const [opening, setOpening] = useState<string | null>(null);
  const open = async () => {
    setOpening(null);
    try {
      await revealFolder(dataDir);
    } catch (failure) {
      setOpening(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <section className="settings__section about" id="settings-about" data-testid="about">
      <h2>About AgentBase</h2>
      <dl className="about__facts">
        <dt>Version</dt>
        <dd data-testid="about-version">{version}</dd>
        <dt>Data folder</dt>
        <dd>
          <code className="settings__folder-path" data-testid="about-data-dir">
            {dataDir}
          </code>
          {revealAvailable() && (
            <button type="button" className="button button--small" onClick={() => void open()}>
              Open folder
            </button>
          )}
        </dd>
      </dl>
      <p className="settings__hint">
        The database, every space&apos;s folder and a fetched ChatGPT runtime live in the data folder;
        keys live in the OS keychain. Release notes for this version are on the project&apos;s GitHub
        releases page under <code>v{version}</code>.
      </p>
      {opening !== null && (
        <p className="field-error" role="alert">
          {opening}
        </p>
      )}
      {onReplayTour !== undefined && (
        <div className="card__actions">
          <button type="button" className="button button--small" onClick={onReplayTour}>
            Replay the tour
          </button>
        </div>
      )}
    </section>
  );
}

/** Light or dark: a fact about this window, kept in this browser, applied at once. */
function AppearanceSection() {
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);
  const label: Record<Theme, string> = { system: "Follow the system", light: "Light", dark: "Dark" };

  return (
    <section className="settings__section" id="settings-appearance" data-testid="appearance">
      <h2>Appearance</h2>
      <div className="settings__theme" role="radiogroup" aria-label="Theme">
        {THEMES.map((choice) => (
          <label key={choice}>
            <input
              type="radio"
              name="theme"
              checked={theme === choice}
              onChange={() => {
                setTheme(choice);
              }}
              data-testid={`theme-${choice}`}
            />
            <span>{label[choice]}</span>
          </label>
        ))}
      </div>
      <p className="settings__hint">Applies to this window straight away, and is remembered on this computer.</p>
    </section>
  );
}

const DISCONNECTED_CHATGPT: ChatGPTAuthResponse = {
  state: "disconnected",
  email: null,
  plan: null,
  error: null,
};

const RUNTIME_POLL_MS = 1_000;

function megabytes(bytes: number): string {
  return `${String(Math.round(bytes / 1_000_000))} MB`;
}

/** ChatGPT OAuth stays independent of saving the access-mode preference. */
function ChatGPTAccount() {
  const load = useCallback(() => api.getChatGPTAuth(), []);
  const auth = useFetched(load, DISCONNECTED_CHATGPT);
  const [working, setWorking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [download, setDownload] = useState<ChatGPTRuntimeResponse | null>(null);

  useEffect(() => {
    if (auth.data.state !== "connecting" && auth.data.state !== "preparing") return;
    const timer = window.setInterval(auth.reload, RUNTIME_POLL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [auth.data.state, auth.reload]);

  const act = async (operation: () => Promise<void>) => {
    setWorking(true);
    setFailure(null);
    try {
      await operation();
      auth.reload();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
      setDownload(null);
    }
  };

  // The App Server runtime is not shipped in the app: the first sign-in
  // fetches the pinned build, then the browser sign-in proceeds by itself.
  const connect = () =>
    act(async () => {
      let status = auth.data;
      if (status.runtime !== null && status.runtime !== undefined && status.runtime.state !== "ready") {
        status = await api.installChatGPTRuntime();
        setDownload(status.runtime ?? null);
        while (status.state === "preparing") {
          await new Promise((resolve) => window.setTimeout(resolve, RUNTIME_POLL_MS));
          status = await api.getChatGPTAuth();
          setDownload(status.runtime ?? null);
        }
        if (status.runtime?.state !== "ready") {
          throw new Error(status.runtime?.error ?? status.error ?? "The ChatGPT runtime could not be installed.");
        }
      }
      const attempt = await api.startChatGPTLogin();
      await openChatGPTAuthUrl(attempt.auth_url);
    });

  const runtime = download ?? auth.data.runtime ?? null;
  const downloading = runtime !== null && runtime.state === "downloading";
  const progress = downloading
    ? `downloading the ChatGPT runtime · ${megabytes(runtime.downloaded_bytes ?? 0)} of ${megabytes(runtime.total_bytes ?? 0)}`
    : null;

  const state = auth.loading
    ? "checking"
    : auth.data.state === "connected"
      ? "connected"
      : auth.data.state === "connecting"
        ? "waiting for browser sign-in"
        : progress ?? "not connected";

  return (
    <div className="settings__oauth" data-testid="chatgpt-auth">
      <div>
        <span className={`status status--${auth.data.state === "connected" ? "running" : "pending"}`}>
          {state}
        </span>
        {auth.data.email !== null && auth.data.email !== undefined && (
          <span className="settings__oauth-account">
            {" "}
            · {auth.data.email}
            {auth.data.plan !== null && auth.data.plan !== undefined ? ` · ${auth.data.plan}` : ""}
          </span>
        )}
      </div>
      <div className="settings__oauth-actions">
        {auth.data.state === "connected" ? (
          <button
            type="button"
            className="button button--small button--danger"
            disabled={working}
            onClick={() => void act(api.logoutChatGPT)}
          >
            Sign out
          </button>
        ) : auth.data.state === "connecting" ? (
          <button
            type="button"
            className="button button--small"
            disabled={working}
            onClick={() => void act(api.cancelChatGPTLogin)}
          >
            Cancel sign-in
          </button>
        ) : (
          <button
            type="button"
            className="button button--small button--primary"
            disabled={working || auth.data.state === "preparing"}
            onClick={() => void connect()}
          >
            {working ? (downloading ? "Downloading…" : "Opening…") : "Sign in with ChatGPT"}
          </button>
        )}
        <button type="button" className="button button--small" onClick={auth.reload}>
          Refresh
        </button>
      </div>
      {runtime !== null && runtime.state !== "ready" && auth.data.state !== "connected" && (
        <p className="settings__hint" data-testid="chatgpt-runtime">
          The first sign-in downloads the Codex App Server runtime {runtime.version} (about{" "}
          {megabytes(runtime.total_bytes ?? 112_000_000)}) from PyPI into AgentBase's data folder,
          verified against its pinned checksum. API-key access never needs it.
        </p>
      )}
      {(failure ?? auth.error ?? auth.data.error) !== null && (
        <p className="settings__error" role="alert">
          {failure ?? auth.error ?? auth.data.error}
        </p>
      )}
    </div>
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

function NumberField({
  label,
  field,
  value,
  error,
  onChange,
  testId,
}: {
  label: string;
  field: string;
  value: string;
  error: string | null;
  onChange: (value: string) => void;
  testId: string;
}) {
  return (
    <label className="editor__field editor__field--narrow">
      <span>{label}</span>
      <input
        type="number"
        min={1}
        value={value}
        onChange={(changed) => {
          onChange(changed.target.value);
        }}
        aria-invalid={error !== null}
        data-testid={testId}
      />
      <FieldError field={field} message={error} />
    </label>
  );
}

/** One row per secret the sidecar accepts. "Set" means it arrived at the last start. */
function KeyRows({ loaded }: { loaded: SettingsResponse }) {
  const available = keychainAvailable();
  // An older sidecar answers without `known_secrets`; fall back to what is set.
  const names: readonly string[] = maybeAbsent(loaded.known_secrets) ?? loaded.configured_secrets;
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [written, setWritten] = useState<ReadonlySet<string>>(() => new Set());
  const [cleared, setCleared] = useState<ReadonlySet<string>>(() => new Set());
  const [failure, setFailure] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);

  const restart = async () => {
    setFailure(null);
    setRestarting(true);
    try {
      await restartApp();
    } catch (error) {
      setRestarting(false);
      setFailure(error instanceof Error ? error.message : String(error));
    }
  };

  const commit = async (name: string) => {
    if (draft.trim() === "") return;
    setFailure(null);
    try {
      await setSecret(name, draft.trim());
      setWritten((prior) => new Set(prior).add(name));
      setCleared((prior) => {
        const next = new Set(prior);
        next.delete(name);
        return next;
      });
      setEditing(null);
      setDraft("");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    }
  };

  const remove = async (name: string) => {
    setFailure(null);
    try {
      await clearSecret(name);
      setCleared((prior) => new Set(prior).add(name));
      setWritten((prior) => {
        const next = new Set(prior);
        next.delete(name);
        return next;
      });
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="settings__keys">
      {!available && (
        <p className="settings__hint">
          Keys can be set only from the AgentBase app, which holds the keychain. This page is open in
          a browser; the rows below show what the sidecar received at its last start.
        </p>
      )}
      {failure !== null && (
        <p className="settings__error" role="alert">
          {failure}
        </p>
      )}
      <ul className="settings__key-list">
        {names.map((name) => {
          const configured = loaded.configured_secrets.includes(name);
          const state = written.has(name)
            ? "saved: restart AgentBase to use it"
            : cleared.has(name)
              ? "removed: restart AgentBase to apply"
              : configured
                ? "set"
                : "not set";
          return (
            <li key={name} className="settings__key" data-testid={`secret-${name}`}>
              <span className="settings__key-label">
                <strong>{KEY_LABELS[name] ?? name}</strong>
                <code className="settings__key-name">{name}</code>
              </span>
              <span className={`settings__key-state${configured || written.has(name) ? " settings__key-state--set" : ""}`}>
                {state}
              </span>
              {available && editing !== name && (
                <span className="settings__key-actions">
                  <button
                    type="button"
                    className="button button--small"
                    aria-label={`Set ${name}`}
                    onClick={() => {
                      setEditing(name);
                      setDraft("");
                    }}
                  >
                    Set…
                  </button>
                  {(configured || written.has(name)) && !cleared.has(name) && (
                    <button
                      type="button"
                      className="button button--small button--danger"
                      aria-label={`Clear ${name}`}
                      onClick={() => void remove(name)}
                    >
                      Clear
                    </button>
                  )}
                </span>
              )}
              {available && editing === name && (
                <span className="settings__key-actions">
                  <input
                    type="password"
                    autoComplete="off"
                    aria-label={name}
                    value={draft}
                    placeholder="paste the key"
                    onChange={(changed) => {
                      setDraft(changed.target.value);
                    }}
                    onKeyDown={(pressed) => {
                      if (pressed.key === "Enter") {
                        pressed.preventDefault();
                        void commit(name);
                      }
                    }}
                  />
                  <button type="button" className="button button--small button--primary" onClick={() => void commit(name)}>
                    Save key
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      setEditing(null);
                      setDraft("");
                    }}
                  >
                    Cancel
                  </button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {restartAvailable() && (written.size > 0 || cleared.size > 0) && (
        <p className="settings__restart" data-testid="restart-offer">
          <button
            type="button"
            className="button button--primary"
            disabled={restarting}
            onClick={() => void restart()}
          >
            {restarting ? "Restarting…" : "Restart AgentBase"}
          </button>
          <span className="settings__hint">
            Quits and reopens the app so the sidecar starts with the keys as they are now.
          </span>
        </p>
      )}
    </div>
  );
}

/** The chat allowlist. An empty list admits nobody. */
function IdentityList({
  identities,
  error,
  onChange,
}: {
  identities: readonly ChannelIdentity[];
  error: string | null;
  onChange: (identities: ChannelIdentity[]) => void;
}) {
  // The one channel this build speaks. A second one would make this a select.
  const channel: ChannelIdentity["channel"] = "discord";
  const [externalId, setExternalId] = useState("");
  const [identity, setIdentity] = useState("");

  const add = () => {
    if (externalId.trim() === "" || identity.trim() === "") return;
    onChange([...identities, { channel, external_user_id: externalId.trim(), identity: identity.trim() }]);
    setExternalId("");
    setIdentity("");
  };

  return (
    <fieldset className="editor__tools">
      <legend>Who may give the bots tasks</legend>
      <p className="editor__hint">
        An allowlist of chat accounts. Nobody on it means nobody: a bot in a server can be addressed by
        everyone in it, and what a stranger would reach is your budget, your desktop&apos;s approval
        dialogs and, through <code>run_shell</code>, your user account.
      </p>
      {identities.length > 0 && (
        <ul className="settings__identities">
          {identities.map((entry) => (
            <li key={`${entry.channel}:${entry.external_user_id}`} className="settings__identity">
              <span className="settings__identity-channel">{entry.channel}</span>
              <span className="settings__identity-id">{entry.external_user_id}</span>
              <span>→ {entry.identity}</span>
              <button
                type="button"
                className="button button--small button--danger"
                aria-label={`Remove ${entry.identity}`}
                onClick={() => {
                  onChange(identities.filter((item) => item !== entry));
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="settings__identity-add">
        <span className="settings__identity-channel" aria-label="Channel">
          {channel}
        </span>
        <input
          value={externalId}
          placeholder="account id on that channel"
          onChange={(changed) => {
            setExternalId(changed.target.value);
          }}
          aria-label="Account id"
          data-testid="identity-external-id"
        />
        <input
          value={identity}
          placeholder="a name for them here"
          onChange={(changed) => {
            setIdentity(changed.target.value);
          }}
          aria-label="Name"
          data-testid="identity-name"
        />
        <button type="button" className="button button--small" onClick={add}>
          Add
        </button>
      </div>
      <FieldError field="channel_identities" message={error} />
    </fieldset>
  );
}
