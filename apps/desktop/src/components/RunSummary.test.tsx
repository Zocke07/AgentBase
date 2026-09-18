import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { reduceAll } from "../state/reducer";
import { LogBuilder, twoAgentRun } from "../test/log";

import { RunSummary } from "./RunSummary";

vi.mock("../lib/api", () => ({
  listMemories: vi.fn(),
  updateMemory: vi.fn(),
}));

const mocked = vi.mocked(api);

const proposed = {
  path: "memory/runs/run-1.md",
  run_id: "run-1",
  source: "run",
  title: "pick storage",
  goal: "pick storage",
  outcome: "SQLite.",
  status: "proposed" as const,
  pinned: false,
  confidence: "medium",
  created_at: "2026-09-18T00:00:00Z",
  updated_at: "2026-09-18T00:00:00Z",
};

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

  it("lists the retrieved excerpts with their cost and the memory note the run wrote", () => {
    const log = new LogBuilder();
    const view = reduceAll([
      log.add("run.started", {
        goal: "pick storage",
        knowledge: [
          {
            citation: "[[decisions/storage#WAL]]",
            score: 0.8,
            matched_terms: ["storag", "wal"],
            reasons: ["body: storag, wal"],
            estimated_tokens: 12,
          },
        ],
        knowledge_exclusions: ["[[recipes/soup]]"],
      }),
      log.add("run.completed", { summary: "SQLite.", memory_path: "memory/runs/run-1.md" }),
    ]);

    render(<RunSummary view={view} />);

    const context = screen.getByTestId("run-context");
    expect(context.textContent).toContain("1 excerpt, about 12 tokens, 1 excluded by you");
    expect(context.textContent).toContain("[[decisions/storage#WAL]]");
    expect(context.textContent).toContain("matched storag, wal");
    expect(context.textContent).toContain("[[recipes/soup]]");
    expect(screen.getByTestId("run-memory").textContent).toContain("memory/runs/run-1.md");
  });

  it("shows how long the run took, from the events' own timestamps", () => {
    /* The fixture stamps one second per event; 28 events span 27 seconds. */
    render(<RunSummary view={reduceAll(twoAgentRun())} />);

    expect(screen.getByTestId("fact-duration").textContent).toBe("27s");
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

  it("looks up the memory's status, approves it in place and opens it beside the inbox", async () => {
    /* The summary used to say "approve it in the Knowledge inbox" and leave
       the user to find it; the seam between a run and its memory is the one
       place a person decides what the app remembers. */
    mocked.listMemories.mockResolvedValue({ items: [proposed], proposed: 1, approved: 0, archived: 0 });
    mocked.updateMemory.mockResolvedValue({ ...proposed, status: "approved" });
    const log = new LogBuilder();
    const view = reduceAll([
      log.add("run.started", { goal: "pick storage" }),
      log.add("run.completed", { summary: "SQLite.", memory_path: "memory/runs/run-1.md" }),
    ]);
    const onOpenMemory = vi.fn();
    const onMemoryChanged = vi.fn();

    render(
      <RunSummary view={view} spaceId="space-1" onOpenMemory={onOpenMemory} onMemoryChanged={onMemoryChanged} />,
    );

    const row = screen.getByTestId("run-memory");
    await waitFor(() => {
      expect(row.textContent).toContain("proposed");
    });
    expect(row.textContent).toContain("not retrieved until you approve it");

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(mocked.updateMemory).toHaveBeenCalledWith("space-1", "memory/runs/run-1.md", { status: "approved" });
    await waitFor(() => {
      expect(row.textContent).toContain("later runs can retrieve it");
    });
    expect(onMemoryChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Open in the inbox" }));
    expect(onOpenMemory).toHaveBeenCalledWith("memory/runs/run-1.md");
  });

  it("folds a long summary and unfolds it on request", async () => {
    /* A long summary pushed the canvas and the log, the evidence for the
       claim, off the bottom of the screen. jsdom has no layout, so the
       height is stubbed on the measured element. */
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => 900 });
    try {
      const log = new LogBuilder();
      const view = reduceAll([
        log.add("run.started", { goal: "long" }),
        log.add("run.completed", { summary: "# Plan\n\n" + "- item\n".repeat(60) }),
      ]);
      render(<RunSummary view={view} />);

      const fold = screen.getByRole("button", { name: "Show the whole summary" });
      expect(fold.getAttribute("aria-expanded")).toBe("false");
      expect(screen.getByTestId("run-claim").querySelector(".claim__body--folded")).not.toBeNull();

      await userEvent.click(fold);
      expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByTestId("run-claim").querySelector(".claim__body--folded")).toBeNull();
    } finally {
      if (original !== undefined) Object.defineProperty(HTMLElement.prototype, "scrollHeight", original);
    }
  });
});
