import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { reduceAll } from "../state/reducer";
import { LogBuilder, twoAgentRun } from "../test/log";
import { SCENARIOS } from "../test/scenarios";

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
  it("lists the files the run wrote and opens each where it lives", async () => {
    // A run reported "decisions/2026-10-07.md" and the person could not find it.
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "Decide" }),
      log.add("tool.called", { tool: "write_file", args: { path: "decisions/2026-10-06.md" }, call_id: "w1" }, "decision"),
      log.add("tool.result", { tool: "write_file", call_id: "w1", result: "Wrote 10 characters." }, "decision"),
      log.add("tool.called", { tool: "check_limits", args: { date: "2026-10-06" }, call_id: "c1" }, "risk-manager"),
      log.add(
        "tool.result",
        { tool: "check_limits", call_id: "c1", result: JSON.stringify({ written: ["risk/rule-checks-2026-10-06.json"] }) },
        "risk-manager",
      ),
    ];
    const onOpenNote = vi.fn();
    const onOpenFile = vi.fn();
    render(<RunSummary view={reduceAll(events)} onOpenNote={onOpenNote} onOpenFile={onOpenFile} />);

    const files = screen.getByTestId("run-files");
    expect(files.textContent).toContain("Wrote 2 files");
    await userEvent.click(within(files).getByRole("button", { name: /2026-10-06\.md/ }));
    expect(onOpenNote).toHaveBeenCalledWith("decisions/2026-10-06.md", null);
    await userEvent.click(within(files).getByRole("button", { name: /rule-checks-2026-10-06\.json/ }));
    expect(onOpenFile).toHaveBeenCalledWith("risk/rule-checks-2026-10-06.json");
  });

  it("folds a long list of written files behind a count", async () => {
    const log = new LogBuilder();
    const written = Array.from({ length: 9 }, (_, index) => `raw/prices/T${String(index)}.csv`);
    const events = [
      log.add("run.started", { goal: "Prices" }),
      log.add("tool.called", { tool: "read_prices", args: { symbols: [] }, call_id: "p1" }, "market-movers"),
      log.add("tool.result", { tool: "read_prices", call_id: "p1", result: JSON.stringify({ written }) }, "market-movers"),
    ];
    render(<RunSummary view={reduceAll(events)} onOpenFile={vi.fn()} />);

    const files = screen.getByTestId("run-files");
    expect(within(files).getAllByRole("button", { name: /\.csv/ })).toHaveLength(6);
    await userEvent.click(within(files).getByRole("button", { name: "3 more" }));
    expect(within(files).getAllByRole("button", { name: /\.csv/ })).toHaveLength(9);
  });

  it("summarises model and tool errors before revealing their details", () => {
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
    expect(screen.getByTestId("fact-errors").parentElement?.className).toBe("run-summary__fact--bad");
    expect(screen.getByTestId("fact-agents").parentElement?.className).toBe("");
    expect(screen.getByTestId("run-issue-badge").textContent).toBe("2 errors");
    const disclosure = screen.getByTestId("run-errors");
    expect(disclosure.tagName).toBe("DETAILS");
    expect(disclosure.hasAttribute("open")).toBe(false);
    expect(disclosure.querySelector("summary")?.textContent).toContain("2 errors during this run");
    expect(disclosure.textContent).toContain("1 model failure and 1 tool failure");
    expect(disclosure.textContent).toContain("rate limited (429)");
    expect(disclosure.textContent).toContain("timed out after 30s");
  });

  it("lists a lookup that found nothing without calling it a failure", () => {
    /* 2026-10-13: a decision listed a "facts" folder that never existed and
       sent one read without its path. Nothing failed or changed, yet the run
       said "2 tool failures. Review these before trusting the outcome." */
    const log = new LogBuilder();
    const lookups = [
      ...twoAgentRun().slice(0, 4),
      log.add("tool.error", { tool: "list_dir", error: "There is no directory at facts in the workspace." }, "supervisor"),
      log.add("tool.error", { tool: "read_file", error: "The arguments for this read_file call could not be read." }, "supervisor"),
    ];
    const { unmount } = render(<RunSummary view={reduceAll(lookups)} />);

    expect(screen.queryByTestId("run-issue-badge")).toBeNull();
    expect(screen.getByTestId("fact-errors").textContent).toBe("0");
    const disclosure = screen.getByTestId("run-errors");
    expect(disclosure.className).toContain("run-summary__problems--calm");
    expect(disclosure.querySelector("summary")?.textContent).toContain("2 missed lookups");
    expect(disclosure.textContent).not.toContain("Review these before trusting the outcome");
    expect(disclosure.textContent).toContain("supervisor · lookup");
    expect(disclosure.textContent).toContain("There is no directory at facts");
    unmount();

    // Beside a real failure, the lookups are counted with it, not hidden.
    render(
      <RunSummary
        view={reduceAll([...lookups, log.add("tool.error", { tool: "write_file", error: "disk full" }, "supervisor")])}
      />,
    );
    expect(screen.getByTestId("run-issue-badge").textContent).toBe("1 error");
    expect(screen.getByTestId("run-errors").textContent).toContain(
      "1 tool failure and 2 missed lookups. Review these before trusting the outcome.",
    );
  });

  it("lists a refused call its agent sent again without calling it a failure", () => {
    /* 2026-10-13: a supervisor's spawn_agent arguments could not be read, so
       the call was refused before it ran. It was sent again and ran, yet the
       run said "1 error during this run". */
    const log = new LogBuilder();
    const resent = [
      ...twoAgentRun().slice(0, 4),
      log.add("tool.requested", { tool: "spawn_agent", call_id: "c1", args: {} }, "supervisor"),
      log.add(
        "tool.error",
        { tool: "spawn_agent", call_id: "c1", error: "The arguments for this spawn_agent call could not be read." },
        "supervisor",
      ),
      log.add("tool.requested", { tool: "spawn_agent", call_id: "c2", args: { agent: "decision" } }, "supervisor"),
      log.add("tool.called", { tool: "spawn_agent", call_id: "c2", args: { agent: "decision" } }, "supervisor"),
    ];
    const { unmount } = render(<RunSummary view={reduceAll(resent)} />);

    expect(screen.queryByTestId("run-issue-badge")).toBeNull();
    expect(screen.getByTestId("fact-errors").textContent).toBe("0");
    const disclosure = screen.getByTestId("run-errors");
    expect(disclosure.className).toContain("run-summary__problems--calm");
    expect(disclosure.querySelector("summary")?.textContent).toContain("1 call sent again");
    expect(disclosure.textContent).not.toContain("Review these before trusting the outcome");
    expect(disclosure.textContent).toContain("supervisor · sent again");
    unmount();

    // Never sent again, it is a failure: what it would have started may never have run.
    render(<RunSummary view={reduceAll(resent.slice(0, 6))} />);
    expect(screen.getByTestId("run-issue-badge").textContent).toBe("1 error");
    expect(screen.getByTestId("run-errors").textContent).toContain(
      "1 tool failure. Review these before trusting the outcome.",
    );
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

  it("says what the run could do without asking, from run.started, and nothing for an older run", () => {
    const log = new LogBuilder();
    const view = reduceAll([
      log.add("run.started", {
        goal: "scan",
        approval: {
          levels: ["low", "medium"],
          tool_policies: {},
          hosts: ["news.google.com"],
          question_seconds: 120,
          supervised: false,
          origin: "schedule",
        },
      }),
    ]);
    const { unmount } = render(<RunSummary view={view} />);
    expect(screen.getByTestId("run-policy").textContent).toContain("Low and medium risk ran on its own");
    expect(screen.getByTestId("run-policy").textContent).toContain("a question expired after 120 seconds");
    unmount();

    render(<RunSummary view={reduceAll(twoAgentRun())} />);
    expect(screen.queryByTestId("run-policy")).toBeNull();
  });

  it("heads an automation's run with its title and folds its instructions beneath", () => {
    const log = new LogBuilder();
    const goal = "Ask news-scanner first to discover Yahoo Finance top gainers, then collect headlines.";
    const view = reduceAll([log.add("run.started", { goal })]);
    const { unmount } = render(<RunSummary view={view} title="Morning collection" />);

    expect(screen.getByRole("heading").textContent).toBe("Morning collection");
    expect(screen.getByText("What it was asked to do").closest("details")?.textContent).toContain(goal);
    unmount();

    // A person's own run has no title: the goal they wrote is the headline.
    render(<RunSummary view={view} />);
    expect(screen.getByRole("heading").textContent).toBe(goal);
    expect(screen.queryByText("What it was asked to do")).toBeNull();
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
      expect(row.textContent).toContain("needs attention");
    });
    expect(row.textContent).toContain("before future runs can use it");

    await userEvent.click(screen.getByRole("button", { name: "Keep for future runs" }));
    expect(mocked.updateMemory).toHaveBeenCalledWith("space-1", "memory/runs/run-1.md", { status: "approved" });
    await waitFor(() => {
      expect(row.textContent).toContain("available to future runs");
    });
    expect(onMemoryChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Keep for future runs" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Review saved context" }));
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

  it("beside the office keeps the title, the figures and every problem in view, and folds the rest", () => {
    /* The room shows where a run came from, what it wrote and read and what
       the supervisor said, so the summary gives it the height. What went
       wrong is never one of the things folded away. */
    const scenario = (id: string) => reduceAll([...(SCENARIOS.find((entry) => entry.id === id)?.events ?? [])]);
    const folded = (testId: string) => screen.getByTestId("run-more").contains(screen.getByTestId(testId));

    const collection = render(<RunSummary view={scenario("morning-collection")} compact />);
    expect(screen.getByTestId("run-more").hasAttribute("open")).toBe(false);
    expect(screen.getByTestId("run-more").querySelector("summary")?.textContent).toBe("More about this run");
    for (const part of ["run-policy", "run-context", "run-claim"]) expect(folded(part), part).toBe(true);
    for (const part of ["run-status", "fact-tool-calls", "fact-cost", "run-files"]) expect(folded(part), part).toBe(false);
    // One row of files beside the office; the rest behind the count, as ever.
    expect(screen.getByTestId("run-files").querySelectorAll(".run-files__file")).toHaveLength(3);
    expect(screen.getByTestId("run-files").textContent).toContain("5 more");
    collection.unmount();

    const failed = render(<RunSummary view={scenario("failed-run")} compact />);
    expect(folded("run-errors")).toBe(false);
    expect(folded("run-issue-badge")).toBe(false);
    // Why a run stopped is a problem too: in view, not behind the disclosure.
    expect(screen.getByTestId("run-claim").textContent).toContain("Why the run stopped");
    expect(screen.getByTestId("run-more").contains(screen.getByTestId("run-claim"))).toBe(false);
    failed.unmount();

    const capped = render(<RunSummary view={scenario("over-budget")} compact />);
    expect(folded("budget-exceeded")).toBe(false);
    capped.unmount();

    // Nothing to fold: no disclosure with nothing in it.
    render(<RunSummary view={reduceAll([])} compact />);
    expect(screen.queryByTestId("run-more")).toBeNull();
  });
});
