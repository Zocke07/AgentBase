import { describe, expect, it } from "vitest";

import { changedNothing, KNOWN_EVENT_TYPES, pendingApprovals, reduceAll, type RunView } from "../state/reducer";

import { scenario, SCENARIOS } from "./scenarios";

/**
 * The scenarios are fixtures other tests and the workbench trust, so each is
 * held to what it says it shows. A scenario that drifted would leave a state
 * undrawn while every screenshot still passed.
 */

const fold = (id: string): RunView => reduceAll(scenario(id).events);

describe("scenario logs", () => {
  it.each(SCENARIOS.map((entry) => [entry.id, entry] as const))("%s is shaped like a sidecar's log", (_id, entry) => {
    expect(entry.events.map((event) => event.seq)).toEqual(entry.events.map((_, index) => index + 1));
    expect(new Set(entry.events.map((event) => event.run_id)).size).toBe(1);
    // The reducer knows every type a scenario uses: none is drawn as unrecognised.
    expect(reduceAll(entry.events).unrecognised).toEqual([]);
  });

  it("has unique ids, usable in a file name", () => {
    const ids = SCENARIOS.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9-]+$/);
  });

  it("uses every event type the orchestrator emits", () => {
    const used = new Set(SCENARIOS.flatMap((entry) => entry.events.map((event) => event.type)));
    // `run.paused` is in the contract, but nothing in the sidecar emits it yet.
    expect(KNOWN_EVENT_TYPES.filter((type) => !used.has(type))).toEqual(["run.paused"]);
  });
});

describe("what each scenario shows", () => {
  it("morning collection: four collectors, every answer by policy, hosts named", () => {
    const view = fold("morning-collection");
    expect(view.status).toBe("completed");
    expect(view.agentOrder).toEqual(["supervisor", "news-scanner", "market-movers", "event-calendar", "portfolio-review"]);
    expect(view.approvalPolicy?.origin).toBe("schedule");
    expect(view.approvals.length).toBeGreaterThan(0);
    expect(view.approvals.every((approval) => approval.automatic && approval.rule === "level" && approval.status === "approved")).toBe(true);
    expect([...new Set(view.approvals.map((approval) => approval.host).filter((host) => host !== null))]).toEqual([
      "news.google.com",
      "feeds.finance.yahoo.com",
      "query1.finance.yahoo.com",
      "api.fiscaldata.treasury.gov",
    ]);
    expect(view.knowledge).toHaveLength(2);
    expect(view.memoryPath).toBe("memory/runs/run-morning.md");
  });

  it("a question waiting: one high-risk question open, its agent waiting", () => {
    const view = fold("shell-question");
    expect(view.status).toBe("running");
    expect(pendingApprovals(view)).toMatchObject([{ tool: "run_shell", risk: "high", agent: "researcher" }]);
    expect(view.agents.researcher?.activity).toBe("waiting");
    expect(view.approvalPolicy?.supervised).toBe(true);
  });

  it("sandbox refusal: refused by the sandbox with nobody asked", () => {
    const view = fold("sandbox-denial");
    expect(view.denials).toMatchObject([{ tool: "read_file", blockedBy: "sandbox" }]);
    expect(view.approvals.some((approval) => !approval.automatic)).toBe(false);
    expect(view.status).toBe("completed");
  });

  it("missed lookup: an error that changed nothing", () => {
    const view = fold("missed-lookup");
    expect(view.errors).toHaveLength(1);
    expect(view.errors.every((error) => changedNothing(error, view))).toBe(true);
    expect(view.status).toBe("completed");
  });

  it("stuck worker: stopped after three failures, and the supervisor finished without it", () => {
    const view = fold("stuck-worker");
    expect(view.agents.researcher?.finishedReason).toBe("stuck");
    expect(view.errors).toHaveLength(3);
    expect(view.errors.some((error) => changedNothing(error, view))).toBe(false);
    // A stuck worker does not fail the run; only a stuck supervisor does.
    expect(view.agents.supervisor?.finishedReason).toBe("finished");
    expect(view.status).toBe("completed");
  });

  it("budget warning: past 80%, not exceeded", () => {
    const view = fold("budget-warning");
    expect(view.budget).toEqual({ spentMicros: 16_400_000, capMicros: 20_000_000, percent: 82 });
    expect(view.budgetExceeded).toBe(false);
    expect(view.status).toBe("completed");
  });

  it("over budget: exceeded, and the run failed", () => {
    const view = fold("over-budget");
    expect(view.budgetExceeded).toBe(true);
    expect(view.status).toBe("failed");
  });

  it("failed run: a retry that is not an error, then one that is", () => {
    const view = fold("failed-run");
    expect(view.errors).toMatchObject([{ kind: "llm", agent: "supervisor" }]);
    expect(view.status).toBe("failed");
    expect(view.claim?.kind).toBe("reason");
  });

  it("cancelled run: stopped while a worker was asking its model", () => {
    const view = fold("cancelled-run");
    expect(view.status).toBe("cancelled");
    expect(view.agents.researcher?.activity).toBe("calling");
    expect(view.agents.researcher?.streamedText).toBe("Reading the first note");
  });

  it("started from Discord: the origin names the channel and the sender", () => {
    const view = fold("discord-origin");
    expect(view.origin).toMatchObject({ channel: "discord", identity: "sam", displayName: "Sam" });
    expect(view.status).toBe("completed");
    // The sidecar records a reply as "report" or a chat question as "approval".
    const outbound = scenario("discord-origin").events.filter((event) => event.type === "channel.outbound");
    expect(outbound.map((event) => event.payload?.kind)).toEqual(["report"]);
  });

  it("ghost handoff: a handoff to an agent that never joined", () => {
    const view = fold("ghost-handoff");
    expect(view.handoffs.map((handoff) => handoff.to)).toContain("publisher");
    expect(view.agents.publisher).toBeUndefined();
  });

  it.each([
    ["twelve-desks", 12],
    ["twenty-desks", 20],
  ])("%s: that many agents, the last still working", (id, desks) => {
    const view = fold(id);
    expect(view.agentOrder).toHaveLength(desks);
    const last = view.agents[view.agentOrder.at(-1) ?? ""];
    expect(last?.activity).toBe("calling");
    expect(view.agentOrder.filter((name) => view.agents[name]?.activity === "completed")).toHaveLength(desks - 2);
  });
});
