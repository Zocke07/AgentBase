import type { AgentDef, ToolResponse } from "@agentspace/schemas";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";

import { AgentsView } from "./AgentsView";

/**
 * The agents tab as a whole: the roster, the editor, and the three fetches
 * behind them.
 *
 * `lib/api` is mocked rather than `fetch`, because what this component owns is
 * which calls it makes and what it does with their outcomes: the request
 * shapes are `api.ts`'s to get right, and are tested there.
 */

vi.mock("../lib/api", () => ({
  listAgents: vi.fn(),
  listTools: vi.fn(),
  listProviders: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mocked = vi.mocked(api);

const writer: AgentDef = {
  id: "def-1",
  space_id: "space-main",
  name: "writer",
  role: "Writes things",
  system_prompt: "You write.",
  provider: null,
  model: null,
  allowed_tools: ["write_file"],
  max_steps: 10,
  auto_approve: [],
  is_builtin: false,
  enabled: true,
  created_at: "2026-09-10T12:00:00Z",
  updated_at: "2026-09-10T12:00:00Z",
};

const tools: ToolResponse[] = [
  { name: "write_file", description: "Write a file", risk: "medium", available: true },
];

beforeEach(() => {
  useRoster.getState().reset();
  useRoster.setState({ spaceId: "space-main" });
  mocked.listAgents.mockResolvedValue([writer]);
  mocked.listTools.mockResolvedValue(tools);
  mocked.listProviders.mockResolvedValue({
    providers: [{ name: "ollama", requires_key: false, free_text_model: true }],
    models: { ollama: [] },
  });
});

describe("what it fetches", () => {
  it("says the roster is loading rather than that it is empty", () => {
    /* `useFetched` starts with the initial value, and for the half-second
       before the first response an empty array read as "No agent definitions
       yet.": wrong, and alarming on a fresh install that has three. */
    mocked.listAgents.mockReturnValue(new Promise(() => undefined));

    render(<AgentsView workspaceProvider="ollama" />);

    expect(screen.queryByText("No agent definitions yet.")).toBeNull();
    expect(screen.getByTestId("agent-list").textContent).toContain("Loading");
  });

  it("shows a failed tool catalogue instead of an editor with no tools", async () => {
    /* Only the roster's error used to be rendered. A failed `/tools` gave the
       editor zero checkboxes and no explanation, and a save from that state
       would have sent `allowed_tools: []`. */
    const user = userEvent.setup();
    mocked.listTools.mockRejectedValue(new Error("GET /tools: HTTP 500"));

    render(<AgentsView workspaceProvider="ollama" />);
    await user.click(await screen.findByRole("button", { name: "New agent" }));

    expect(screen.getByRole("alert").textContent).toContain("GET /tools: HTTP 500");
  });

  it("shows a failed provider catalogue the same way", async () => {
    const user = userEvent.setup();
    mocked.listProviders.mockRejectedValue(new Error("GET /settings/providers: HTTP 500"));

    render(<AgentsView workspaceProvider="ollama" />);
    await user.click(await screen.findByRole("button", { name: "New agent" }));

    expect(screen.getByRole("alert").textContent).toContain("/settings/providers");
  });
});

describe("editing", () => {
  it("opens the editor on the row that was clicked", async () => {
    const user = userEvent.setup();
    render(<AgentsView workspaceProvider="ollama" />);

    await user.click(await screen.findByText("writer"));

    await waitFor(() => {
      expect(screen.getByTestId("agent-editor").textContent).toContain("Edit writer");
    });
  });

  it("reports a refused delete beside the roster rather than hiding the button", async () => {
    const user = userEvent.setup();
    mocked.deleteAgent.mockRejectedValue(new Error("built-in definitions cannot be deleted"));
    render(<AgentsView workspaceProvider="ollama" />);

    await user.click(await screen.findByTestId("delete-writer"));
    await user.click(screen.getByRole("button", { name: "Delete writer" }));

    expect((await screen.findByTestId("roster-error")).textContent).toContain("cannot be deleted");
  });

  it("asks before deleting, and a second click is what deletes", async () => {
    /* A user-authored system prompt is unrecoverable; one misclick on a
       row's Delete used to send the request. */
    const user = userEvent.setup();
    mocked.deleteAgent.mockResolvedValue(undefined);
    render(<AgentsView workspaceProvider="ollama" />);

    await user.click(await screen.findByTestId("delete-writer"));
    expect(mocked.deleteAgent).not.toHaveBeenCalled();
    expect(screen.getByTestId("agent-row-writer").textContent).toContain("Delete writer?");

    await user.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.queryByRole("button", { name: "Keep" })).toBeNull();
    expect(mocked.deleteAgent).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("delete-writer"));
    await user.click(screen.getByRole("button", { name: "Delete writer" }));
    expect(mocked.deleteAgent).toHaveBeenCalledWith("def-1");
  });

  it("asks before discarding an edit in progress", async () => {
    const user = userEvent.setup();
    mocked.listAgents.mockResolvedValue([writer, { ...writer, id: "def-2", name: "critic" }]);
    render(<AgentsView workspaceProvider="ollama" />);
    await user.click(await screen.findByText("writer"));
    await user.type(await screen.findByTestId("field-role"), " and more");

    await user.click(screen.getByText("critic"));

    // Still editing the writer, with the question shown.
    expect(screen.getByTestId("agent-editor").textContent).toContain("Edit writer");
    expect(screen.getByTestId("unsaved").textContent).toContain("unsaved");
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(screen.getByTestId("agent-editor").textContent).toContain("Edit critic");
    });
  });

  it("disables a row's controls while its request is in flight", async () => {
    const user = userEvent.setup();
    let release: () => void = () => undefined;
    mocked.updateAgent.mockReturnValue(new Promise<AgentDef>((resolve) => { release = () => { resolve(writer); }; }));
    render(<AgentsView workspaceProvider="ollama" />);

    await user.click(await screen.findByTestId("toggle-writer"));

    expect(screen.getByTestId("toggle-writer")).toHaveProperty("disabled", true);
    expect(screen.getByTestId("delete-writer")).toHaveProperty("disabled", true);
    release();
    await waitFor(() => {
      expect(screen.getByTestId("toggle-writer")).toHaveProperty("disabled", false);
    });
  });
});
