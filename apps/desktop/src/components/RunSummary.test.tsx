import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reduceAll } from "../state/reducer";
import { LogBuilder, twoAgentRun } from "../test/log";

import { RunSummary } from "./RunSummary";

/**
 * The run's header. Most of what it shows is covered by `replayIdentity`;
 * these are the facts the reducer folded that nothing used to render.
 */

describe("RunSummary", () => {
  it("counts model and tool errors, and names them", () => {
    /* `view.errors` was folded from `llm.error` and `tool.error` and rendered
       nowhere; an agent that hit five provider errors in a row looked like an
       agent that was thinking. */
    const log = new LogBuilder();
    const view = reduceAll([
      ...twoAgentRun().slice(0, 4),
      log.add("llm.error", { error: "rate limited (429)" }, "supervisor"),
      log.add("tool.error", { tool: "run_shell", error: "timed out after 30s" }, "supervisor"),
    ]);

    render(<RunSummary view={view} />);

    expect(screen.getByTestId("fact-errors").textContent).toBe("2");
    const list = screen.getByTestId("run-errors");
    expect(list.textContent).toContain("rate limited (429)");
    expect(list.textContent).toContain("timed out after 30s");
  });

  it("says so when the run was stopped by the monthly cap", () => {
    const log = new LogBuilder();
    const view = reduceAll([
      log.add("run.started", { goal: "spend" }),
      log.add("budget.exceeded", { spent_micros: 1000, cap_micros: 1000, reason: "over" }),
    ]);

    render(<RunSummary view={view} />);

    expect(screen.getByTestId("budget-exceeded").textContent).toContain("cap");
  });

  it("shows what the run cost, from the log", () => {
    render(<RunSummary view={reduceAll(twoAgentRun())} />);

    // 1200 + 800 micros from the fixture's two priced calls.
    expect(screen.getByTestId("fact-cost").textContent).toBe("$0.0020");
  });

  it("shows neither when there is nothing to show", () => {
    render(<RunSummary view={reduceAll(twoAgentRun())} />);

    expect(screen.queryByTestId("run-errors")).toBeNull();
    expect(screen.queryByTestId("budget-exceeded")).toBeNull();
  });
});
