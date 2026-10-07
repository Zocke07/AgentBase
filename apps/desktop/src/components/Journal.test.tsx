import type { KnowledgeNote, NoteSummary } from "@agentbase/schemas";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { journalDays, journalEntries, monthHeading } from "../state/journal";

import { JournalIndex, JournalPage } from "./Journal";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  getKnowledgeNote: vi.fn(),
}));

const mocked = vi.mocked(api);

function noteAt(path: string, updated: string): NoteSummary {
  return { path, title: path, excerpt: "", updated_at: updated };
}

function noteText(path: string): KnowledgeNote {
  return {
    path,
    title: path,
    excerpt: "",
    updated_at: "2026-10-07T23:20:00Z",
    content: `## DECISION TABLE\n\n| Ticker | Action |\n| --- | --- |\n| AAPL | pass from ${path} |\n`,
  };
}

beforeEach(() => {
  mocked.getKnowledgeNote.mockImplementation((_space, path) => Promise.resolve(noteText(path)));
});

describe("JournalPage", () => {
  it("reads every dated report as one page, newest first, and opens one as a note", async () => {
    const onOpenNote = vi.fn();
    const days = journalDays(
      journalEntries([
        noteAt("decisions/2026-10-05.md", "2026-10-06T23:20:00Z"),
        noteAt("portfolio/review-2026-10-06.md", "2026-10-07T23:03:00Z"),
        noteAt("decisions/2026-10-06.md", "2026-10-07T23:20:00Z"),
      ]),
    );
    render(
      <JournalPage spaceId="space-lab" days={days} focus={null} onOpenNote={onOpenNote} onLink={vi.fn()} onTag={vi.fn()} />,
    );

    const journal = screen.getByTestId("journal");
    expect(journal.textContent).toContain("3 reports from 2 dates");
    const reports = within(journal).getAllByRole("article");
    expect(reports.map((report) => report.getAttribute("aria-label"))).toEqual([
      "Decision, decisions/2026-10-06.md",
      "Portfolio review, portfolio/review-2026-10-06.md",
      "Decision, decisions/2026-10-05.md",
    ]);
    // Each report is drawn from its own file, a table as a table.
    const newest = within(journal).getByRole("article", { name: "Decision, decisions/2026-10-06.md" });
    expect(await within(newest).findByText("pass from decisions/2026-10-06.md")).toBeTruthy();
    expect(within(newest).getByRole("table")).toBeTruthy();
    expect(mocked.getKnowledgeNote).toHaveBeenCalledTimes(3);

    await userEvent.click(screen.getByRole("button", { name: "Open note decisions/2026-10-05.md" }));
    expect(onOpenNote).toHaveBeenCalledWith("decisions/2026-10-05.md");
  });

  it("draws a week of dates at a time and widens to a date picked further back", async () => {
    const days = journalDays(
      journalEntries(
        Array.from({ length: 10 }, (_, position) =>
          noteAt(`decisions/2026-09-${String(10 + position)}.md`, `2026-09-${String(10 + position)}T23:00:00Z`),
        ),
      ),
    );
    const { rerender } = render(
      <JournalPage spaceId="space-lab" days={days} focus={null} onOpenNote={vi.fn()} onLink={vi.fn()} onTag={vi.fn()} />,
    );

    const dated = () => [...screen.getByTestId("journal").querySelectorAll<HTMLElement>("[data-date]")].map((day) => day.dataset.date);
    expect(dated()).toHaveLength(7);
    expect(dated()[0]).toBe("2026-09-19");
    await waitFor(() => {
      expect(mocked.getKnowledgeNote).toHaveBeenCalledTimes(7);
    });

    // Picking the oldest date in the index brings it onto the page.
    rerender(
      <JournalPage
        spaceId="space-lab"
        days={days}
        focus={{ date: "2026-09-10", nonce: 1 }}
        onOpenNote={vi.fn()}
        onLink={vi.fn()}
        onTag={vi.fn()}
      />,
    );
    expect(dated()).toHaveLength(10);
    expect(dated().at(-1)).toBe("2026-09-10");
    expect(screen.queryByRole("button", { name: /older date/ })).toBeNull();
  });

  it("offers the older dates a page at a time", async () => {
    const days = journalDays(
      journalEntries(
        Array.from({ length: 9 }, (_, position) =>
          noteAt(`decisions/2026-09-${String(10 + position)}.md`, `2026-09-${String(10 + position)}T23:00:00Z`),
        ),
      ),
    );
    render(<JournalPage spaceId="space-lab" days={days} focus={null} onOpenNote={vi.fn()} onLink={vi.fn()} onTag={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Show 2 older dates" }));
    expect(screen.getByTestId("journal").querySelectorAll("[data-date]")).toHaveLength(9);
  });

  it("explains what collects here before anything does", () => {
    render(<JournalPage spaceId="space-lab" days={[]} focus={null} onOpenNote={vi.fn()} onLink={vi.fn()} onTag={vi.fn()} />);

    expect(screen.getByText(/Each day's decision, its portfolio review and the weekly review collect here/)).toBeTruthy();
  });
});

describe("JournalIndex", () => {
  it("lists the dates by month, filters by kind, and picks a date", async () => {
    const onKind = vi.fn();
    const onPick = vi.fn();
    const days = journalDays(
      journalEntries([
        noteAt("decisions/2026-10-06.md", "2026-10-07T23:20:00Z"),
        noteAt("portfolio/review-2026-10-06.md", "2026-10-07T23:03:00Z"),
        noteAt("decisions/2026-09-30.md", "2026-10-01T23:20:00Z"),
      ]),
    );
    render(
      <JournalIndex
        days={days}
        kinds={["Decision", "Portfolio review"]}
        kind={null}
        onKind={onKind}
        current={null}
        onPick={onPick}
      />,
    );

    const index = screen.getByTestId("journal-index");
    expect(within(index).getAllByRole("region")).toHaveLength(2);
    const october = within(index).getByRole("region", { name: monthHeading("2026-10-06") });
    expect(within(october).getByText("Decision · Portfolio review")).toBeTruthy();

    await userEvent.selectOptions(within(index).getByRole("combobox"), "Decision");
    expect(onKind).toHaveBeenCalledWith("Decision");
    expect(within(index).getByRole("option", { name: "Portfolio reviews" })).toBeTruthy();

    const september = within(index).getByRole("region", { name: monthHeading("2026-09-30") });
    await userEvent.click(within(september).getByRole("button"));
    expect(onPick).toHaveBeenCalledWith("2026-09-30");
  });
});
