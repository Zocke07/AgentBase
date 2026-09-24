import type { SettingsResponse } from "@agentbase/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import * as external from "../lib/external";
import * as keychain from "../lib/keychain";
import * as shell from "../lib/shell";

import { SettingsView } from "./SettingsView";

/**
 * The settings screen: the one the user guide said did not exist, sending
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
  listTools: vi.fn(),
  verifySettings: vi.fn(),
  getChannels: vi.fn(),
  getChatGPTAuth: vi.fn(),
  installChatGPTRuntime: vi.fn(),
  startChatGPTLogin: vi.fn(),
  cancelChatGPTLogin: vi.fn(),
  logoutChatGPT: vi.fn(),
}));

vi.mock("../lib/external", () => ({
  openChatGPTAuthUrl: vi.fn(),
}));

vi.mock("../lib/keychain", () => ({
  keychainAvailable: vi.fn(() => false),
  setSecret: vi.fn(),
  clearSecret: vi.fn(),
}));

vi.mock("../lib/shell", () => ({
  restartAvailable: vi.fn(() => false),
  restartApp: vi.fn(),
}));

const mocked = vi.mocked(api);

const settings: SettingsResponse = {
  settings: {
    provider: "anthropic",
    model: "claude-opus-5",
    openai_access: "api_key",
    monthly_cap_micros: 20_000_000,
    ollama_base_url: "http://127.0.0.1:11434",
    auto_approve: [],
    max_steps_per_agent: 20,
    max_agents_per_run: 5,
    max_run_seconds: 600,
    discord_enabled: false,
    channel_identities: [],
    channel_approvals: "dashboard_only",
  },
  configured_secrets: ["anthropic_api_key"],
  known_secrets: ["anthropic_api_key", "discord_bot_token", "openai_api_key"],
  supported_providers: ["anthropic", "ollama", "openai"],
  model_is_priced: true,
  version: "0.4.0",
  data_dir: "D:\\data",
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
  mocked.listTools.mockResolvedValue([
    { name: "read_file", description: "Read a file", risk: "low", available: true },
    { name: "write_file", description: "Write a file", risk: "medium", available: true },
    { name: "run_shell", description: "Run a command", risk: "high", available: true },
  ]);
  mocked.getChannels.mockResolvedValue([
    { channel: "discord", enabled: false, configured: false, running: false, failures: 0, last_error: null, refused: [] },
  ]);
  mocked.getChatGPTAuth.mockResolvedValue({
    state: "disconnected",
    email: null,
    plan: null,
    error: null,
  });
  mocked.startChatGPTLogin.mockResolvedValue({
    login_id: "login_123",
    auth_url: "https://auth.openai.com/oauth/authorize?client_id=test",
  });
  mocked.cancelChatGPTLogin.mockResolvedValue(undefined);
  mocked.logoutChatGPT.mockResolvedValue(undefined);
  vi.mocked(external.openChatGPTAuthUrl).mockResolvedValue(undefined);
  vi.mocked(keychain.keychainAvailable).mockReturnValue(false);
  vi.mocked(shell.restartAvailable).mockReturnValue(false);
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

    expect(screen.getByTestId<HTMLSelectElement>("setting-provider").value).toBe("anthropic");
    // The model is each space's, not chosen here.
    expect(screen.queryByTestId("setting-model")).toBeNull();
    expect(screen.getByTestId<HTMLInputElement>("setting-cap").value).toBe("20.00");
    expect(screen.getByTestId<HTMLInputElement>("setting-max-steps").value).toBe("20");
  });
});

describe("saving", () => {
  it("sends only the fields that changed, as a PATCH", async () => {
    const user = userEvent.setup();
    const { onSaved } = view();
    await loaded();

    await user.clear(screen.getByTestId("setting-max-steps"));
    await user.type(screen.getByTestId("setting-max-steps"), "30");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({ max_steps_per_agent: 30 });
    await waitFor(() => {
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("saves an answer for one tool, and drops it again when set back to ask", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-policy-write_file"), "allow");
    await user.selectOptions(screen.getByTestId("setting-policy-run_shell"), "deny");
    await user.selectOptions(screen.getByTestId("setting-policy-write_file"), "ask");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({ tool_policies: { run_shell: "deny" } });
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

describe("the provider", () => {
  it("chooses the provider alone, and shows the Ollama address for a local one", async () => {
    /* The model moved to the spaces: Settings names whose models run, and
       so which key; each space names the model, an agent its own. */
    const user = userEvent.setup();
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    expect(screen.queryByTestId("setting-model")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(mocked.updateSettings).toHaveBeenCalledWith({ provider: "openai" });

    await user.selectOptions(screen.getByTestId("setting-provider"), "ollama");
    expect(screen.getByTestId("setting-ollama-url")).toBeDefined();
  });

  it("keeps ChatGPT subscription access under the OpenAI provider", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByTestId("setting-openai-chatgpt"));
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(mocked.updateSettings).toHaveBeenCalledWith({
      provider: "openai",
      openai_access: "chatgpt",
    });
    expect(screen.getByTestId("openai-access").textContent).toContain("same OpenAI provider");
  });

  it("starts ChatGPT OAuth and opens only the runtime's browser URL", async () => {
    const user = userEvent.setup();
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByTestId("setting-openai-chatgpt"));
    await user.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));

    expect(mocked.startChatGPTLogin).toHaveBeenCalledOnce();
    expect(external.openChatGPTAuthUrl).toHaveBeenCalledWith(
      "https://auth.openai.com/oauth/authorize?client_id=test",
    );
  });

  it("fetches the App Server runtime first when it is missing, then signs in", async () => {
    /* The runtime is not in the app. The button downloads it, shows the
       progress the sidecar reports, and only then opens the browser sign-in. */
    const user = userEvent.setup();
    const missing = {
      state: "disconnected" as const,
      email: null,
      plan: null,
      error: null,
      runtime: { state: "missing" as const, version: "0.154.0", downloaded_bytes: 0, total_bytes: 112_690_061, error: null },
    };
    const downloading = {
      ...missing,
      state: "preparing" as const,
      runtime: { ...missing.runtime, state: "downloading" as const, downloaded_bytes: 43_000_000 },
    };
    const ready = { ...missing, runtime: { ...missing.runtime, state: "ready" as const } };
    mocked.getChatGPTAuth.mockResolvedValue(missing);
    mocked.installChatGPTRuntime.mockImplementation(() => {
      mocked.getChatGPTAuth.mockResolvedValueOnce(downloading).mockResolvedValue(ready);
      return Promise.resolve(downloading);
    });
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByTestId("setting-openai-chatgpt"));
    expect((await screen.findByTestId("chatgpt-runtime")).textContent).toContain("0.154.0");
    expect(screen.getByTestId("chatgpt-runtime").textContent).toContain("113 MB");
    await user.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));

    expect(mocked.installChatGPTRuntime).toHaveBeenCalledOnce();
    expect((await screen.findByTestId("chatgpt-auth")).textContent).toContain(
      "downloading the ChatGPT runtime · 43 MB of 113 MB",
    );
    await waitFor(
      () => {
        expect(mocked.startChatGPTLogin).toHaveBeenCalledOnce();
      },
      { timeout: 4_000 },
    );
    expect(external.openChatGPTAuthUrl).toHaveBeenCalledWith(
      "https://auth.openai.com/oauth/authorize?client_id=test",
    );
  });

  it("shows why the runtime could not be installed instead of opening a browser", async () => {
    const user = userEvent.setup();
    const failed = {
      state: "error" as const,
      email: null,
      plan: null,
      error: null,
      runtime: {
        state: "error" as const,
        version: "0.154.0",
        downloaded_bytes: 0,
        total_bytes: 112_690_061,
        error: "The ChatGPT runtime download did not match the pinned SHA-256 and was discarded.",
      },
    };
    mocked.getChatGPTAuth.mockResolvedValue({ ...failed, state: "disconnected", runtime: { ...failed.runtime, state: "missing", error: null } });
    mocked.installChatGPTRuntime.mockResolvedValue(failed);
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByTestId("setting-openai-chatgpt"));
    await user.click(await screen.findByRole("button", { name: "Sign in with ChatGPT" }));

    expect((await screen.findByRole("alert")).textContent).toContain("pinned SHA-256");
    expect(mocked.startChatGPTLogin).not.toHaveBeenCalled();
    expect(external.openChatGPTAuthUrl).not.toHaveBeenCalled();
  });

  it("shows the connected ChatGPT account and can sign out", async () => {
    const user = userEvent.setup();
    mocked.getChatGPTAuth.mockResolvedValue({
      state: "connected",
      email: "person@example.com",
      plan: "plus",
      error: null,
    });
    view();
    await loaded();

    await user.selectOptions(screen.getByTestId("setting-provider"), "openai");
    await user.click(screen.getByTestId("setting-openai-chatgpt"));

    expect((await screen.findByTestId("chatgpt-auth")).textContent).toContain(
      "person@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(mocked.logoutChatGPT).toHaveBeenCalledOnce();
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
    expect(rows).toHaveLength(3);
    expect(screen.getByTestId("secret-anthropic_api_key").textContent).toContain("set");
    expect(screen.getByTestId("secret-openai_api_key").textContent).toContain("not set");
  });

  it("explains, outside the app, that keys can only be set from the app", async () => {
    view();
    await loaded();

    expect(screen.getByTestId("keys").textContent).toContain("only from the AgentBase app");
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

  it("offers a restart only once a key has changed, and asks the shell for it", async () => {
    /* The button is the shell's relaunch: the sidecar reads keys at spawn, so
       nothing short of a restart applies a change. Before any change there is
       nothing to apply, and a browser tab has no process to relaunch. */
    const user = userEvent.setup();
    vi.mocked(keychain.keychainAvailable).mockReturnValue(true);
    vi.mocked(shell.restartAvailable).mockReturnValue(true);
    vi.mocked(keychain.clearSecret).mockResolvedValue(undefined);
    vi.mocked(shell.restartApp).mockResolvedValue(undefined);
    view();
    await loaded();
    expect(screen.queryByTestId("restart-offer")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Clear anthropic_api_key" }));
    const restart = await screen.findByRole("button", { name: "Restart AgentBase" });
    await user.click(restart);

    expect(shell.restartApp).toHaveBeenCalledTimes(1);
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Restarting…" }).disabled).toBe(true);
  });

  it("keeps the restart offer usable when the shell refuses", async () => {
    const user = userEvent.setup();
    vi.mocked(keychain.keychainAvailable).mockReturnValue(true);
    vi.mocked(shell.restartAvailable).mockReturnValue(true);
    vi.mocked(keychain.clearSecret).mockResolvedValue(undefined);
    vi.mocked(shell.restartApp).mockRejectedValue(new Error("no relaunch today"));
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Clear anthropic_api_key" }));
    await user.click(await screen.findByRole("button", { name: "Restart AgentBase" }));

    expect((await screen.findByRole("alert")).textContent).toContain("no relaunch today");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Restart AgentBase" }).disabled).toBe(
      false,
    );
  });

  it("offers no restart in a browser tab, which has no process to relaunch", async () => {
    const user = userEvent.setup();
    vi.mocked(keychain.keychainAvailable).mockReturnValue(true);
    vi.mocked(keychain.clearSecret).mockResolvedValue(undefined);
    view();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Clear anthropic_api_key" }));

    expect((await screen.findByTestId("secret-anthropic_api_key")).textContent).toContain("restart");
    expect(screen.queryByTestId("restart-offer")).toBeNull();
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

describe("about", () => {
  it("shows the version that answered and where its data lives, and replays the tour", async () => {
    const onReplayTour = vi.fn();
    render(<SettingsView onSaved={vi.fn()} onReplayTour={onReplayTour} />);
    await loaded();

    const about = screen.getByTestId("about");
    expect(screen.getByTestId("about-version").textContent).toBe("0.4.0");
    expect(screen.getByTestId("about-data-dir").textContent).toBe("D:\\data");
    expect(about.textContent).toContain("v0.4.0");

    await userEvent.click(screen.getByRole("button", { name: "Replay the tour" }));
    expect(onReplayTour).toHaveBeenCalledTimes(1);
  });

  it("offers no replay where the shell has no tour", async () => {
    view();
    await loaded();

    expect(screen.queryByRole("button", { name: "Replay the tour" })).toBeNull();
  });
});
