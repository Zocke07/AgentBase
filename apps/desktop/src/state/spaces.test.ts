import type { SpaceResponse } from "@agentbase/schemas";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";

import { useSpaces } from "./spaces";

vi.mock("../lib/api", () => ({
  listSpaces: vi.fn(),
}));

const spaces: SpaceResponse[] = [
  {
    id: "space-main",
    name: "Main",
    created_at: "2026-09-24T00:00:00Z",
    updated_at: "2026-09-24T00:00:00Z",
    folder: "D:\\data\\spaces\\space-main",
    is_default: true,
  },
  {
    id: "space-lab",
    name: "Lab",
    created_at: "2026-09-24T00:00:00Z",
    updated_at: "2026-09-24T00:00:00Z",
    folder: "D:\\data\\spaces\\space-lab",
    is_default: false,
  },
];

beforeEach(() => {
  localStorage.clear();
  useSpaces.getState().reset();
  vi.mocked(api.listSpaces).mockResolvedValue(spaces);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the remembered space", () => {
  it("migrates an AgentSpace selection when AgentBase has no selection", async () => {
    localStorage.setItem("agentspace.space", "space-lab");

    await useSpaces.getState().load();

    expect(useSpaces.getState().currentId).toBe("space-lab");
    expect(localStorage.getItem("agentbase.space")).toBe("space-lab");
  });

  it("prefers the AgentBase selection when both names are present", async () => {
    localStorage.setItem("agentbase.space", "space-main");
    localStorage.setItem("agentspace.space", "space-lab");

    await useSpaces.getState().load();

    expect(useSpaces.getState().currentId).toBe("space-main");
  });
});
