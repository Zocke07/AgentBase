import type {
  AgentDef,
  CreateAgentRequest,
  ProviderCatalogueResponse,
  ToolResponse,
  UpdateAgentRequest,
} from "@agentbase/schemas";
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
 *  - "Surface the API's validation errors inline on the offending field, never
 *    a toast that loses which field was wrong."
 *  - "Tool checkboxes show each tool's risk level next to it, so the consequence
 *    of ticking `run_shell` is visible at the moment of ticking it."
 */

const TOOLS: ToolResponse[] = [
  { name: "read_file", description: "Read a file in the workspace.", risk: "low", available: true },
  { name: "write_file", description: "Write a file in the workspace.", risk: "medium", available: true },
  { name: "run_shell", description: "Run a shell command.", risk: "high", available: true },
];

const CATALOGUE: ProviderCatalogueResponse = {
  providers: [
    { name: "anthropic", requires_key: true, free_text_model: false },
    { name: "ollama", requires_key: false, free_text_model: true },
    { name: "openai", requires_key: true, free_text_model: false },
  ],
  models: {
    anthropic: ["claude-opus-5", "claude-sonnet-5"],
    ollama: [],
    openai: ["gpt-4o", "gpt-5.4-mini"],
  },
};

/**
 * Render the editor. `onSave` stands in for whichever of the two callbacks the
 * mode under test will call: create for a new definition, patch for an edit.
 */
/** Accepts what either callback would be given, so one double serves both. */
type Save = (body: CreateAgentRequest | UpdateAgentRequest) => Promise<void>;

function editor(
  overrides: Partial<
    Pick<Parameters<typeof AgentEditor>[0], "agent" | "onCancel" | "workspaceProvider">
  > & {
    onSave?: Save;
  } = {},
) {
  const onSave = vi.fn<Save>(overrides.onSave ?? (() => Promise.resolve()));
  render(
    <AgentEditor
      agent={overrides.agent ?? null}
      tools={TOOLS}
      catalogue={CATALOGUE}
      workspaceProvider={overrides.workspaceProvider ?? "anthropic"}
      onCreate={onSave}
      onPatch={onSave}
      onCancel={overrides.onCancel ?? vi.fn()}
    />,
  );
  return { onSave };
}

/** The two fields the editor refuses to send empty. */
async function complete(user: ReturnType<typeof userEvent.setup>, name = "an_agent") {
  const nameField = screen.getByTestId<HTMLInputElement>("field-name");
  if (nameField.value === "") await user.type(nameField, name);
  await user.type(screen.getByTestId("field-system-prompt"), "You do the thing.");
}

const modelOptions = () =>
  [...screen.getByTestId<HTMLSelectElement>("field-model").options].map((option) => option.value);

describe("validation errors land on the field the server blamed", () => {
  it("shows a duplicate-name conflict against the name input", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(409, "an agent named 'researcher' already exists", "name"),
    );
    editor({ onSave });

    await user.type(screen.getByTestId("field-name"), "researcher");
    await complete(user);
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

    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-max_steps").textContent).toContain("above this workspace");
  });

  it("shows an unknown-tool rejection against the tool list", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(400, "unknown tool 'delete_everything'", "allowed_tools"),
    );
    editor({ onSave });

    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-allowed_tools").textContent).toContain("unknown tool");
  });

  it("falls back to a form-level message only when the server named no field", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(new ApiError(500, "the sidecar is unreachable"));
    editor({ onSave });

    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(screen.getByTestId("error-form").textContent).toBe("the sidecar is unreachable");
  });

  it("clears a field's error as soon as the user edits that field", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValue(new ApiError(409, "already exists", "name"));
    editor({ onSave });

    await user.type(screen.getByTestId("field-name"), "taken");
    await complete(user);
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
    await complete(user);
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

describe("the model field follows the provider", () => {
  it("offers only the chosen provider's models", async () => {
    /* A flat list let a definition pin `claude-opus-5` under provider
       `openai`, which the backend would refuse at run time: after the run
       had been started. */
    const user = userEvent.setup();
    editor();

    await user.selectOptions(screen.getByTestId("field-provider"), "openai");

    expect(modelOptions()).toEqual(["", "gpt-4o", "gpt-5.4-mini"]);
  });

  it("offers the workspace provider's models when the provider is inherited", () => {
    editor({ workspaceProvider: "openai" });

    expect(modelOptions()).toEqual(["", "gpt-4o", "gpt-5.4-mini"]);
  });

  it("takes a typed model name for a provider with no fixed list", async () => {
    /* Ollama serves whatever the user has pulled. The old select offered no
       Ollama model at all, so no definition could ever be pinned to one. */
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.selectOptions(screen.getByTestId("field-provider"), "ollama");
    await user.type(screen.getByTestId("field-name"), "local");
    await user.type(screen.getByTestId("field-model"), "qwen3:4b");
    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "ollama", model: "qwen3:4b" }),
    );
  });

  it("keeps showing a saved model that is not in the current provider's list", () => {
    /* Rather than silently displaying "inherit" for a value the form still
       holds: the mismatch is the thing the user needs to see. */
    const agent: AgentDef = {
      id: "def-1",
      space_id: "space-main",
      name: "odd",
      role: "r",
      system_prompt: "p",
      provider: "openai",
      model: "claude-opus-5",
      allowed_tools: [],
      is_builtin: false,
      enabled: true,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    };
    editor({ agent });

    expect(screen.getByTestId("field-model")).toHaveProperty("value", "claude-opus-5");
    expect(screen.getByTestId("agent-editor").textContent).toContain("not one of openai's models");
  });
});

describe("the approval policy", () => {
  it("offers the three risk levels, badged, and sends the ticked ones", async () => {
    /* §4 gives every definition an `auto_approve` column and the reducer
       reads it; no editor field ever reached it. It narrows the workspace
       policy (it can never widen it), and an empty list means inherit. */
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.type(screen.getByTestId("field-name"), "quiet");
    await user.click(screen.getByTestId("auto-low"));
    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ auto_approve: ["low"] }));
    expect(screen.getByTestId("agent-editor").textContent).toContain("never widen");
  });
});

describe("before the round trip", () => {
  it("refuses an empty name and an empty prompt itself, on the fields", async () => {
    /* The server would say the same; a request for a form that is visibly
       incomplete is a round trip for nothing. The server stays the
       authority on everything else. */
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByTestId("error-name").textContent).toContain("name");
    expect(screen.getByTestId("error-system_prompt").textContent).toContain("prompt");
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
    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ max_steps: null }));
  });

  it("sends null for provider and model when set to inherit", async () => {
    const user = userEvent.setup();
    const { onSave } = editor();

    await user.type(screen.getByTestId("field-name"), "inheritor");
    await complete(user);
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ provider: null, model: null }),
    );
  });

  it("loads an existing definition into the form", () => {
    const agent: AgentDef = {
      id: "def-1",
      space_id: "space-main",
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

  it("sends only the fields the user changed when editing", async () => {
    /* The roster's enable toggle and the editor can both be open on the same
       row. The editor used to send its whole form on save, including the
       `enabled` it was opened with, so toggling in the roster and then saving
       an unrelated edit silently undid the toggle. A PATCH carries what the
       user touched; `UpdateAgentRequest` leaves the rest alone. */
    const user = userEvent.setup();
    const agent: AgentDef = {
      id: "def-1",
      space_id: "space-main",
      name: "note_keeper",
      role: "Keeps notes",
      system_prompt: "You keep notes.",
      provider: null,
      model: null,
      allowed_tools: ["read_file"],
      max_steps: 4,
      auto_approve: [],
      is_builtin: false,
      enabled: true,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    };
    const { onSave } = editor({ agent });

    await user.clear(screen.getByTestId("field-role"));
    await user.type(screen.getByTestId("field-role"), "Keeps better notes");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(onSave).toHaveBeenCalledWith({ role: "Keeps better notes" });
  });

  it("closes without a request when nothing was changed", async () => {
    const user = userEvent.setup();
    const agent: AgentDef = {
      id: "def-1",
      space_id: "space-main",
      name: "note_keeper",
      role: "Keeps notes",
      system_prompt: "p",
      allowed_tools: [],
      is_builtin: false,
      enabled: true,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    };
    const onCancel = vi.fn();
    const { onSave } = editor({ agent, onCancel });

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });

  it("says a built-in cannot be deleted", () => {
    const agent: AgentDef = {
      id: "def-2",
      space_id: "space-main",
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
