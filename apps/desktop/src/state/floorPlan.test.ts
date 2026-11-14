import type { AgentDef, Run, ScheduleResponse } from "@agentbase/schemas";
import { describe, expect, it } from "vitest";

import { nextAutomation, restingDesk, runDesk, toolsOnDesk, toolsSummary } from "./floorPlan";

const agent = (extra: Partial<AgentDef> = {}): AgentDef => ({
  id: "a1",
  space_id: "s1",
  name: "writer",
  role: "Drafts the report",
  system_prompt: "",
  created_at: "2026-11-14T00:00:00Z",
  updated_at: "2026-11-14T00:00:00Z",
  ...extra,
});

describe("the floor plan", () => {
  it("draws an available agent at its desk, ready", () => {
    const desk = restingDesk(agent({ model: "claude-sonnet-5-5" }));
    expect(desk).toMatchObject({ name: "writer", ghost: false, face: "dot", stateLabel: "Available", role: "Drafts the report" });
    expect(desk.model).not.toBeNull();
    expect(desk.accessibleName.startsWith("writer Available")).toBe(true);
  });

  it("pushes the chair in for an agent the supervisor may not use, and says so", () => {
    const desk = restingDesk(agent({ enabled: false }));
    expect(desk.ghost).toBe(true);
    expect(desk.stateLabel).toBe("Not available");
  });

  it("is the same desk for the same definition", () => {
    expect(restingDesk(agent())).toEqual(restingDesk(agent()));
  });

  it("lists the tools riskiest first, and an unlisted tool as unknown, never safe", () => {
    const tools = toolsOnDesk(agent({ allowed_tools: ["read_file", "run_shell", "gone", "http_get"] }), [
      { name: "read_file", description: "", risk: "low", available: true },
      { name: "run_shell", description: "", risk: "high", available: true },
      { name: "http_get", description: "", risk: "medium", available: true },
    ]);
    expect(tools.map((tool) => `${tool.name}:${tool.risk}`)).toEqual(["run_shell:high", "http_get:medium", "read_file:low", "gone:unknown"]);
    expect(toolsSummary(tools)).toBe("4 tools, 1 high risk");
    expect(toolsSummary([])).toBe("No tools");
  });
});

describe("Home's office", () => {
  const run: Run = {
    id: "run-1",
    space_id: "s1",
    goal: "Summarise the week",
    status: "running",
    origin: "ui",
    origin_ref: null,
    created_at: "2026-11-14T08:00:00Z",
    finished_at: null,
    title: "Weekly summary",
  };

  it("poses a run's desk from its status, and a waiting question over all", () => {
    expect(runDesk(run, "running", false)).toMatchObject({ name: "Weekly summary", face: "thinking", stateLabel: "Working" });
    expect(runDesk(run, "running", true)).toMatchObject({ face: "question", stateLabel: "Waiting for you" });
    expect(runDesk({ ...run, title: null }, "pending", false)).toMatchObject({ name: "Summarise the week", stateLabel: "Starting" });
  });

  it("puts the soonest enabled schedule on the calendar", () => {
    const schedule = (name: string, at: string | null, enabled = true) => ({ name, next_run_at: at, enabled }) as ScheduleResponse;
    const now = Date.parse("2026-11-15T00:00:00Z");
    expect(
      nextAutomation([
        schedule("Weekly review", "2026-11-16T09:00:00Z"),
        schedule("Morning digest", "2026-11-15T07:00:00Z"),
        schedule("Switched off", "2026-11-15T06:00:00Z", false),
        schedule("After another", null),
        schedule("Missed while closed", "2026-11-14T07:00:00Z"),
      ], now),
    ).toEqual({ name: "Morning digest", at: "2026-11-15T07:00:00Z" });
    expect(nextAutomation([], now)).toBeNull();
  });
});
