import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import { EventLog } from "./EventLog";

/**
 * The log panel's filters are component state — which rows a person is looking
 * at is a fact about the person — and that is exactly why they can go stale:
 * the run underneath them changes and the filter does not.
 */

function log(events = twoAgentRun(), cursor = events.length) {
  const onSelectAgent = vi.fn();
  const agents = [...new Set(events.map((event) => event.agent_id).filter((id): id is string => id !== null))];
  const rendered = render(
    <EventLog
      events={events}
      cursor={cursor}
      agents={agents}
      selectedAgent={null}
      onSelectAgent={onSelectAgent}
    />,
  );
  return { ...rendered, onSelectAgent, agents };
}

const typeFilter = () => screen.getByLabelText<HTMLSelectElement>("Type");

describe("filtering by type", () => {
  it("narrows the rows to one family", async () => {
    const user = userEvent.setup();
    log();

    await user.selectOptions(typeFilter(), "tool");

    const rows = screen.getAllByRole("listitem");
    expect(rows.every((row) => row.textContent.includes("tool."))).toBe(true);
  });

  it("drops a filter the new run has no rows for, instead of showing an empty log", async () => {
    /* Pick a Discord run, filter to `channel.*`, pick a run from this window:
       `channel` is not among its families, the select showed blank, and every
       row was hidden behind a filter the user could not see. */
    const user = userEvent.setup();
    const discord = new LogBuilder("run-discord");
    const chatRun = [
      discord.add("channel.inbound", { channel: "discord", identity: "owner", text: "hi" }),
      discord.add("run.started", { goal: "hi" }),
      discord.add("run.completed", { summary: "done" }),
    ];
    const { rerender } = log(chatRun, chatRun.length);
    await user.selectOptions(typeFilter(), "channel");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);

    const local = twoAgentRun();
    rerender(
      <EventLog
        events={local}
        cursor={local.length}
        agents={["supervisor", "researcher"]}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    expect(typeFilter().value).toBe("all");
    expect(screen.getAllByRole("listitem")).toHaveLength(local.length);
  });

  it("falls back to every type when the scrubber moves before the filtered family's first event", async () => {
    /* Same shape, reached by scrubbing rather than by switching runs. */
    const user = userEvent.setup();
    const events = twoAgentRun();
    const firstTool = events.findIndex((event) => event.type.startsWith("tool."));
    const { rerender } = log(events);
    await user.selectOptions(typeFilter(), "tool");

    rerender(
      <EventLog
        events={events}
        cursor={firstTool}
        agents={["supervisor", "researcher"]}
        selectedAgent={null}
        onSelectAgent={vi.fn()}
      />,
    );

    expect(typeFilter().value).toBe("all");
    expect(screen.getAllByRole("listitem")).toHaveLength(firstTool);
  });
});
