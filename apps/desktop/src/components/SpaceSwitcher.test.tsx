import type { SpaceResponse } from "@agentbase/schemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { SpaceSwitcher } from "./SpaceSwitcher";

vi.mock("../lib/api", () => ({
  createSpace: vi.fn(),
}));

const mocked = vi.mocked(api);

const space = (id: string, name: string, extra: Partial<SpaceResponse> = {}): SpaceResponse => ({
  id,
  name,
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  folder: `D:\\data\\spaces\\${id}`,
  is_default: false,
  ...extra,
});

const spaces = [
  space("main", "Main", { is_default: true }),
  space("lab", "Lab"),
  space("old", "Old", { archived: true }),
];

beforeEach(() => {
  mocked.createSpace.mockImplementation((body) =>
    Promise.resolve(space("new", body.name)),
  );
});

describe("switching", () => {
  it("shows the current space, lists the live ones, and folds the archived ones away", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<SpaceSwitcher spaces={spaces} currentId="main" onSelect={onSelect} onCreated={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Space: Main/ })).toBeDefined();
    await user.click(screen.getByRole("button", { name: /Space: Main/ }));

    const live = screen.getByRole("listbox", { name: "Spaces" });
    expect(live.textContent).toContain("Lab");
    expect(live.textContent).not.toContain("Old");
    expect(screen.getByText("Archived (1)")).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Lab" }));
    expect(onSelect).toHaveBeenCalledWith("lab");
    expect(screen.queryByRole("listbox", { name: "Spaces" })).toBeNull();
  });
});

describe("creating", () => {
  it("creates a space seeded with the built-in roles by default, and hands it up", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<SpaceSwitcher spaces={spaces} currentId="main" onSelect={vi.fn()} onCreated={onCreated} />);

    await user.click(screen.getByRole("button", { name: /Space: Main/ }));
    await user.click(screen.getByRole("button", { name: "New space…" }));
    await user.type(screen.getByTestId("new-space-name"), "Research");
    await user.click(screen.getByRole("button", { name: "Create space" }));

    expect(mocked.createSpace).toHaveBeenCalledWith({ name: "Research", seed: "builtins" });
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ name: "Research" }));
  });

  it("can copy the current space's roster instead", async () => {
    const user = userEvent.setup();
    render(<SpaceSwitcher spaces={spaces} currentId="lab" onSelect={vi.fn()} onCreated={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Space: Lab/ }));
    await user.click(screen.getByRole("button", { name: "New space…" }));
    await user.type(screen.getByTestId("new-space-name"), "Lab 2");
    await user.click(screen.getByLabelText(/copies of Lab's agents/));
    await user.click(screen.getByRole("button", { name: "Create space" }));

    expect(mocked.createSpace).toHaveBeenCalledWith({ name: "Lab 2", seed: { copy_from: "lab" } });
  });

  it("shows a refusal in place", async () => {
    const user = userEvent.setup();
    mocked.createSpace.mockRejectedValue(new Error("A space named 'Lab' already exists."));
    render(<SpaceSwitcher spaces={spaces} currentId="main" onSelect={vi.fn()} onCreated={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Space: Main/ }));
    await user.click(screen.getByRole("button", { name: "New space…" }));
    await user.type(screen.getByTestId("new-space-name"), "Lab");
    await user.click(screen.getByRole("button", { name: "Create space" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
  });
});
