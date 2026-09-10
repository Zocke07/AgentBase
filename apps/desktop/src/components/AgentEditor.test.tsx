import type { AgentDef, ToolResponse } from "@agentspace/schemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";

import { AgentEditor } from "./AgentEditor";



/**
 * The agent editor.
 *
 * §5 Phase 7 names two requirements for this component specifically, and both
 * are tested here rather than left to inspection:
 *
 *  - "Surface the API's validation errors inline on the offending field — never
 *    a toast that loses which field was wrong."
 *  - "Tool checkboxes show each tool's risk level next to it, so the consequence
 *    of ticking `run_shell` is visible at the moment of ticking it."
 */

const TOOLS: ToolResponse[] = [
  { name: "read_file", description: "Read a file in the workspace.", risk: "low", available: true },
  { name: "write_file", description: "Write a file in the workspace.", risk: "medium", available: true },
  { name: "run_shell", description: "Run a shell command.", risk: "high", available: true },
];

function editor(overrides: Partial<Parameters<typeof AgentEditor>[0]> = {}) {
  const onSave = overrides.onSave ?? vi.fn().mockResolvedValue(undefined);
  render(
    <AgentEditor
      agent={overrides.agent ?? null}
      tools={TOOLS}
      providers={["anthropic", "ollama"]}
      models={["claude-sonnet-5", "qwen3:4b"]}
      onSave={onSave}
      onCancel={overrides.onCancel ?? vi.fn()}
    />,
  );
  return { onSave };
}

describe("validation errors land on the field the server blamed", () => {
  it("shows a duplicate-name conflict against the name input", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(409, "an agent named 'researcher' already exists", "name"),
    );
    editor({ onSave });

    await user.type(screen.getByTestId("field-name"), "researcher");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-name").textContent).toBe(
      "an agent named 'researcher' already exists",
    );
    expect(screen.getByTestId("field-name").getAttribute("aria-invalid")).toBe("true");
  });

  it("shows a max_steps rejection against the max steps input", async () => {
    /* The Phase 5 bug's own error message, on the input that caused it. */
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(400, "max_steps of 20 is above this workspace's limit of 10", "max_steps"),
    );
    editor({ onSave });

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-max_steps").textContent).toContain("above this workspace");
  });

  it("shows an unknown-tool rejection against the tool list", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(400, "unknown tool 'delete_everything'", "allowed_tools"),
    );
    editor({ onSave });

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-allowed_tools").textContent).toContain("unknown tool");
  });

  it("falls back to a form-level message only when the server named no field", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(new ApiError(500, "the sidecar is unreachable"));
    editor({ onSave });

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-form").textContent).toBe("the sidecar is unreachable");
  });

  it("clears a field's error as soon as the user edits that field", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(new ApiError(409, "already exists", "name"));
    editor({ onSave });

    await user.type(screen.getByTestId("field-name"), "taken");
    await user.click(screen.getByRole("button", { name: "Create agent" }));
    expect(screen.queryByTestId("error-name")).not.toBeNull();

    await user.type(screen.getByTestId("field-name"), "-2");

    expect(screen.queryByTestId("error-name")).toBeNull();
  });
});

describe("the tool allowlist", () => {
  it("shows every tool's risk level beside its checkbox", async () => {
    editor();

    for (const tool of TOOLS) {
      const checkbox = screen.getByTestId(`tool-${tool.name}`);
      const row = checkbox.closest("label");
      expect(row?.textContent).toContain(tool.risk);
    }
    await Promise.resolve();
  });

  it("sends only the ticked tools", async () => {
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.type(screen.getByTestId("field-name"), "shell_user");
    await user.click(screen.getByTestId("tool-run_shell"));
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ allowed_tools: ["run_shell"] }));
  });

  it("says plainly that ticking a tool is not the same as approving its calls", () => {
    editor();

    expect(screen.getByTestId("agent-editor").textContent).toContain(
      "every call still stops at the approval gate",
    );
  });
});

describe("what gets sent", () => {
  it("omits max_steps when the field is blank, rather than inventing one", async () => {
    /* CLAUDE.md, Phase 5: "a default that duplicates a value the user can change
       is a bug waiting for the user to change it". A literal 20 here would be
       rejected by any workspace whose cap is lower, naming a field the user
       never filled in. */
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.type(screen.getByTestId("field-name"), "plain");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ max_steps: null }));
  });

  it("sends null for provider and model when set to inherit", async () => {
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.type(screen.getByTestId("field-name"), "inheritor");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ provider: null, model: null }),
    );
  });

  it("loads an existing definition into the form", () => {
    const agent: AgentDef = {
      id: "def-1",
      name: "note_keeper",
      role: "Keeps notes",
      system_prompt: "You keep notes.",
      provider: "ollama",
      model: "qwen3:4b",
      allowed_tools: ["read_file"],
      max_steps: 4,
      auto_approve: [],
      is_builtin: false,
      enabled: false,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    };
    editor({ agent });

    expect(screen.getByTestId("field-name")).toHaveProperty("value", "note_keeper");
    expect(screen.getByTestId("field-system-prompt")).toHaveProperty("value", "You keep notes.");
    expect(screen.getByTestId("field-max-steps")).toHaveProperty("value", "4");
    expect(screen.getByTestId("tool-read_file")).toHaveProperty("checked", true);
    expect(screen.getByTestId("tool-run_shell")).toHaveProperty("checked", false);
    expect(screen.getByTestId("field-enabled")).toHaveProperty("checked", false);
  });

  it("says a built-in cannot be deleted", () => {
    const agent: AgentDef = {
      id: "def-2",
      name: "researcher",
      role: "Researches",
      system_prompt: "p",
      allowed_tools: [],
      is_builtin: true,
      enabled: true,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    };
    editor({ agent });

    expect(screen.getByTestId("agent-editor").textContent).toContain("not deleted");
  });
});
