import type { SettingsResponse, SpaceResponse } from "@agentspace/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { SpaceSettingsView } from "./SpaceSettingsView";

/**
 * One space's settings: what is sent, and in particular that "Inherit" is
 * sent as null rather than dropped: the one thing that separates this form
 * from the app-wide one.
 */

// Only the transport is replaced; `ApiError` itself stays real, so the form
// sees the same class the real calls throw.
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  listProviders: vi.fn(),
  listTools: vi.fn(),
  updateSpace: vi.fn(),
  deleteSpace: vi.fn(),
  listSchedules: vi.fn(),
}));

const mocked = vi.mocked(api);

const lab: SpaceResponse = {
  id: "space-lab",
  name: "Lab",
  description: "",
  provider: null,
  model: null,
  auto_approve: null,
  max_steps_per_agent: null,
  max_agents_per_run: null,
  max_run_seconds: 1200,
  archived: false,
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  folder: "D:\\data\\spaces\\space-lab",
  is_default: false,
};

const settings: SettingsResponse = {
  settings: {
    provider: "ollama",
    model: "qwen3:4b",
    auto_approve: ["low"],
    tool_policies: { write_file: "allow", run_shell: "deny" },
    max_steps_per_agent: 20,
    max_agents_per_run: 5,
    max_run_seconds: 600,
  },
  configured_secrets: [],
  known_secrets: [],
  supported_providers: ["ollama"],
  model_is_priced: true,
  version: "0.4.0",
  data_dir: "D:\\data",
};

beforeEach(() => {
  mocked.listSchedules.mockResolvedValue([]);
  mocked.listTools.mockResolvedValue([
    { name: "read_file", description: "Read a file", risk: "low", available: true },
    { name: "write_file", description: "Write a file", risk: "medium", available: true },
    { name: "run_shell", description: "Run a command", risk: "high", available: true },
  ]);
  mocked.listProviders.mockResolvedValue({
    providers: [{ name: "ollama", requires_key: false, free_text_model: true }],
    models: { ollama: [] },
  });
  mocked.updateSpace.mockImplementation((_id, patch) =>
    Promise.resolve({ ...lab, ...patch, updated_at: "2026-09-12T00:00:01Z" } as SpaceResponse),
  );
});

describe("what is sent", () => {
  it("sends a rule set back to blank as null, so the sidecar reads it as inherit", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={onChanged} />);

    await user.clear(screen.getByTestId("space-max_run_seconds"));
    await user.click(screen.getByRole("button", { name: "Save space" }));

    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenCalledWith("space-lab", { max_run_seconds: null });
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("sends only what changed, as numbers", async () => {
    const user = userEvent.setup();
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);

    await user.type(screen.getByTestId("space-max_agents_per_run"), "2");
    await user.click(screen.getByRole("button", { name: "Save space" }));

    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenCalledWith("space-lab", { max_agents_per_run: 2 });
    });
  });

  it("switches the approval policy from inherit to the space's own, and back", async () => {
    const user = userEvent.setup();
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);

    await user.click(screen.getByTestId("space-approvals-own"));
    await user.click(screen.getByTestId("space-auto-medium"));
    await user.click(screen.getByRole("button", { name: "Save space" }));

    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenLastCalledWith("space-lab", { auto_approve: ["medium"] });
    });
    // Ticked but not in the app-wide policy: the page says it will still ask.
    expect(screen.getByTestId("space-auto-medium").closest("label")?.textContent).toContain("still asks");
  });

  it("offers only stricter answers for a tool, and inherits again once none is left", async () => {
    /* The app allows write_file, asks about read_file and refuses run_shell:
       write_file can be made to ask or be refused here, read_file can only
       be refused, and run_shell has nothing left to narrow. */
    const user = userEvent.setup();
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);
    const options = (name: string) =>
      [...screen.getByTestId<HTMLSelectElement>(`space-policy-${name}`).options].map((o) => o.value);

    await waitFor(() => {
      expect(options("write_file")).toEqual(["", "ask", "deny"]);
    });
    expect(options("read_file")).toEqual(["", "deny"]);
    expect(screen.getByTestId<HTMLSelectElement>("space-policy-run_shell").disabled).toBe(true);
    expect(screen.getByTestId("space-policy-run_shell").textContent).toContain("never allow");

    await user.selectOptions(screen.getByTestId("space-policy-write_file"), "ask");
    await user.click(screen.getByRole("button", { name: "Save space" }));
    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenLastCalledWith("space-lab", { tool_policies: { write_file: "ask" } });
    });
  });

  it("goes back to inheriting outright once no answer of its own is left", async () => {
    const user = userEvent.setup();
    render(
      <SpaceSettingsView
        space={{ ...lab, tool_policies: { write_file: "ask" } }}
        settings={settings}
        onChanged={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId<HTMLSelectElement>("space-policy-write_file").value).toBe("ask");
    });

    await user.selectOptions(screen.getByTestId("space-policy-write_file"), "");
    await user.click(screen.getByRole("button", { name: "Save space" }));
    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenLastCalledWith("space-lab", { tool_policies: null });
    });
  });

  it("shows the inherited values as placeholders, never as the space's own", () => {
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);

    const steps = screen.getByTestId<HTMLInputElement>("space-max_steps_per_agent");
    expect(steps.value).toBe("");
    expect(steps.placeholder).toBe("20");
    expect(screen.getByTestId<HTMLInputElement>("space-max_run_seconds").value).toBe("1200");
  });

  it("puts a refusal on the field the server named", async () => {
    const user = userEvent.setup();
    mocked.updateSpace.mockRejectedValue(new api.ApiError(400, "A space named 'Main' already exists.", "name"));
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);

    await user.clear(screen.getByTestId("space-name"));
    await user.type(screen.getByTestId("space-name"), "Main");
    await user.click(screen.getByRole("button", { name: "Save space" }));

    expect((await screen.findByTestId("error-name")).textContent).toContain("already exists");
  });
});

describe("the danger zone", () => {
  it("is not offered for the default space", () => {
    render(
      <SpaceSettingsView space={{ ...lab, is_default: true }} settings={settings} onChanged={vi.fn()} />,
    );
    expect(screen.queryByTestId("danger-zone")).toBeNull();
    expect(screen.getByTestId("space-folder").textContent).toContain("space-lab");
  });

  it("archives, and deletes only after a second click", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    mocked.deleteSpace.mockResolvedValue(undefined);
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Archive this space" }));
    await waitFor(() => {
      expect(mocked.updateSpace).toHaveBeenCalledWith("space-lab", { archived: true });
    });

    await user.click(screen.getByRole("button", { name: "Delete this space…" }));
    expect(mocked.deleteSpace).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(mocked.deleteSpace).toHaveBeenCalledWith("space-lab");
    });
    expect(onChanged).toHaveBeenLastCalledWith(null);
  });

  it("shows the sidecar's reason when a delete is refused", async () => {
    const user = userEvent.setup();
    mocked.deleteSpace.mockRejectedValue(new Error("'Lab' has 3 runs and cannot be deleted: runs are history. Archive it instead."));
    render(<SpaceSettingsView space={lab} settings={settings} onChanged={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Delete this space…" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect((await screen.findByTestId("error-form")).textContent).toContain("Archive it instead");
  });
});
