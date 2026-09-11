import type { SettingsResponse } from "@agentspace/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import * as keychain from "../lib/keychain";

import { SettingsView } from "./SettingsView";

/**
 * The settings screen — the one the user guide said did not exist, sending
 * people to Swagger UI for every setting and to Credential Manager for keys.
 *
 * `lib/api` and `lib/keychain` are mocked: what this component owns is which
 * calls it makes, with what, and what it does with the answers.
 */

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  listProviders: vi.fn(),
  verifySettings: vi.fn(),
  getChannels: vi.fn(),
}));

vi.mock("../lib/keychain", () => ({
  keychainAvailable: vi.fn(() => false),
  setSecret: vi.fn(),
  clearSecret: vi.fn(),
}));

const mocked = vi.mocked(api);

const settings: SettingsResponse = {
  settings: {
    provider: "anthropic",
    model: "claude-opus-5",
    monthly_cap_micros: 20_000_000,
    ollama_base_url: "http://127.0.0.1:11434",
    auto_approve: [],
    max_steps_per_agent: 20,
    max_agents_per_run: 5,
    max_run_seconds: 600,
    discord_enabled: false,
    telegram_enabled: false,
    channel_identities: [],
    channel_approvals: "dashboard_only",
  },
  configured_secrets: ["anthropic_api_key"],
  known_secrets: ["anthropic_api_key", "discord_bot_token", "openai_api_key", "telegram_bot_token"],
  supported_providers: ["anthropic", "ollama", "openai"],
  model_is_priced: true,
};

beforeEach(() => {
  mocked.getSettings.mockResolvedValue(settings);
  mocked.updateSettings.mockImplementation((patch) =>
    Promise.resolve({ ...settings, settings: { ...settings.settings, ...patch } as SettingsResponse["settings"] }),
  );
  mocked.listProviders.mockResolvedValue({
    providers: [
      { name: "anthropic", requires_key: true, free_text_model: false },
      { name: "ollama", requires_key: false, free_text_model: true },
      { name: "openai", requires_key: true, free_text_model: false },
    ],
    models: { anthropic: ["claude-opus-5", "claude-sonnet-5"], ollama: [], openai: ["gpt-4o"] },
  });
  mocked.verifySettings.mockResolvedValue({ ok: true, provider: "anthropic", model: "claude-opus-5" });
  mocked.getChannels.mockResolvedValue([
    { channel: "discord", enabled: false, configured: false, running: false, failures: 0, last_error: null, refused: [] },
    { channel: "telegram", enabled: false, configured: false, running: false, failures: 0, last_error: null, refused: [] },
  ]);
  vi.mocked(keychain.keychainAvailable).mockReturnValue(false);
});

function view(onSaved = vi.fn()) {
  render(<SettingsView onSaved={onSaved} />);
  return { onSaved };
}

async function loaded() {
  await waitFor(() => {
    expect(screen.getByTestId<HTMLSelectElement>("setting-provider").value).toBe("anthropic");
  });
}

describe("loading", () => {
  it("shows the workspace's settings", async () => {
    view();
    await loaded();

    expect(screen.getByTestId<HTMLSelectElement>("setting-model").value).toBe("claude-opus-5");
    expect(screen.getByTestId<HTMLInputElement>("setting-cap").value).toBe("20.00");
    expect(screen.getByTestId<HTMLInputElement>("setting-max-steps").value).toBe("20");
  });
});

describe("saving", () => {
  it("sends only the fields that changed, as a PATCH", async () => {
    const user = userEvent.setup();
    const { onSaved } = view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-model"), "claude-sonnet-5");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({ model: "claude-sonnet-5" });
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("converts the cap from dollars to integer micros", async () => {
    /* Money is integer micros end to end (§5 Phase 3). The field takes dollars
       because that is what a person thinks in; the conversion rounds to whole
       micros rather than sending a float. */
    const user = userEvent.setup();
    view();
    await loaded();

    await user.clear(screen.getByTestId("setting-cap"));
    await user.type(screen.getByTestId("setting-cap"), "12.5");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({ monthly_cap_micros: 12_500_000 });
  });

  it("puts a refusal on the field the server named", async () => {
    const user = userEvent.setup();
    mocked.updateSettings.mockRejectedValue(new ApiError(400, "unknown provider 'x'", "provider"));
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect((await screen.findByTestId("error-provider")).textContent).toContain("unknown provider");
  });

  it("does nothing when nothing changed", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).not.toHaveBeenCalled();
  });
});

describe("the model", () => {
  it("offers the chosen provider's models, and a text box for a free-text provider", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    // A placeholder first: changing the provider clears the model, and the
    // user has to choose one rather than inherit whatever was first.
    expect([...screen.getByTestId<HTMLSelectElement>("setting-model").options].map((o) => o.value)).toEqual(["", "gpt-4o"]);

    await user.selectOptions(screen.getByTestId("setting-provider"), "ollama");
    expect(screen.getByTestId("setting-model").tagName).toBe("INPUT");
    expect(screen.getByTestId("setting-ollama-url")).toBeDefined();
  });

  it("verifies on demand and shows the sidecar's reason", async () => {
    const user = userEvent.setup();
    mocked.verifySettings.mockResolvedValue({ ok: false, reason: "No API key for openai." });
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Check" }));

    expect((await screen.findByTestId("verify-result")).textContent).toContain("No API key for openai");
  });
});

describe("keys", () => {
  it("lists every secret the sidecar accepts, and which are set", async () => {
    view();
    await loaded();

    const rows = screen.getAllByTestId(/^secret-/);
    expect(rows).toHaveLength(4);
    expect(screen.getByTestId("secret-anthropic_api_key").textContent).toContain("set");
    expect(screen.getByTestId("secret-openai_api_key").textContent).toContain("not set");
  });

  it("explains, outside the app, that keys can only be set from the app", async () => {
    view();
    await loaded();

    expect(screen.getByTestId("keys").textContent).toContain("only from the AgentSpace app");
    expect(screen.queryByRole("button", { name: /Set/ })).toBeNull();
  });

  it("writes a key to the keychain and says a restart is needed", async () => {
    /* The webview writes to the OS keychain; the running sidecar never sees
       the value, because keys are read once at spawn (§1 constraint 4). */
    const user = userEvent.setup();
    vi.mocked(keychain.keychainAvailable).mockReturnValue(true);
    vi.mocked(keychain.setSecret).mockResolvedValue(undefined);
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Set openai_api_key" }));
    await user.type(screen.getByLabelText("openai_api_key"), "sk-test-not-real");
    await user.click(screen.getByRole("button", { name: "Save key" }));

    expect(keychain.setSecret).toHaveBeenCalledWith("openai_api_key", "sk-test-not-real");
    expect((await screen.findByTestId("secret-openai_api_key")).textContent).toContain("restart");
    expect(mocked.updateSettings).not.toHaveBeenCalled();
  });

  it("clears a key from the keychain", async () => {
    const user = userEvent.setup();
    vi.mocked(keychain.keychainAvailable).mockReturnValue(true);
    vi.mocked(keychain.clearSecret).mockResolvedValue(undefined);
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Clear anthropic_api_key" }));

    expect(keychain.clearSecret).toHaveBeenCalledWith("anthropic_api_key");
  });
});

describe("channels", () => {
  it("shows whether each adapter is running, and its last error", async () => {
    mocked.getChannels.mockResolvedValue([
      {
        channel: "discord",
        enabled: true,
        configured: true,
        running: false,
        failures: 3,
        last_error: "LoginFailure: Improper token has been passed",
        refused: ["Zocke (868311828982284310)"],
      },
    ]);
    view();
    await loaded();

    const status = await screen.findByTestId("channel-discord");
    expect(status.textContent).toContain("not running");
    expect(status.textContent).toContain("Improper token");
    expect(status.textContent).toContain("Zocke");
  });

  it("adds an identity to the allowlist and sends the whole list", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.type(screen.getByTestId("identity-external-id"), "123");
    await user.type(screen.getByTestId("identity-name"), "owner");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({
      channel_identities: [{ channel: "discord", external_user_id: "123", identity: "owner" }],
    });
  });
});
