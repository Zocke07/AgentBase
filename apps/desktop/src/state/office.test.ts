import type { Event } from "@agentbase/schemas";
import { describe, expect, it } from "vitest";

import { TOOL_FAMILIES, TOOLS } from "../lib/tools";
import { LogBuilder, twoAgentRun } from "../test/log";
import { scenario, SCENARIOS } from "../test/scenarios";

import { officeOf, stampLabel, stampReason, type Desk, type Face, type OfficeModel, type Stamp } from "./office";
import { reduceAll, type Activity } from "./reducer";

/**
 * The office is a projection of the fold, so these tests are about three
 * claims: it is pure (the same prefix gives the same room, however it
 * arrived), it is honest (nothing in the room lacks a source in the log, and
 * a claim never passes for evidence), and things that come and go last for a
 * span of events.
 */

const room = (events: readonly Event[]): OfficeModel => officeOf(reduceAll(events));
const at = (id: string, cursor?: number): OfficeModel => {
  const { events } = scenario(id);
  return room(cursor === undefined ? events : events.slice(0, cursor));
};
const everyone = (office: OfficeModel): Desk[] => (office.lead === null ? [...office.desks] : [office.lead, ...office.desks]);
const desk = (office: OfficeModel, name: string): Desk => {
  const found = everyone(office).find((entry) => entry.name === name);
  if (found === undefined) throw new Error(`no desk for ${name}`);
  return found;
};
/** The cursor just after the first event that matches. */
const after = (events: readonly Event[], match: (event: Event) => boolean): number => {
  const index = events.findIndex(match);
  if (index < 0) throw new Error("the log has no such event");
  return index + 1;
};

describe("the office as a projection", () => {
  it.each(SCENARIOS.map((entry) => [entry.id, entry] as const))("%s: every prefix gives a room, the same room twice", (_id, entry) => {
    for (let cursor = 0; cursor <= entry.events.length; cursor += 1) {
      const prefix = entry.events.slice(0, cursor);
      // Folded in one go, and folded event by event from a shared base.
      expect(officeOf(reduceAll(prefix))).toEqual(officeOf(prefix.reduce((state, event) => reduceAll([event], state), reduceAll([]))));
    }
  });

  it("is an empty, unlit room before anything has happened", () => {
    const office = room([]);
    expect(office).toMatchObject({ lit: false, dimmed: false, lead: null, desks: [], folders: [], focus: null, announcement: null });
    expect(office.board).toMatchObject({ goal: null, status: "pending", claim: null, documents: [] });
    expect(office.clock).toEqual({ elapsedSeconds: null, limitSeconds: null });
  });

  it("puts the supervisor at the lead desk and workers in the order they appeared", () => {
    const office = at("morning-collection");
    expect(office.lead?.name).toBe("supervisor");
    expect(office.lead?.lead).toBe(true);
    expect(office.desks.map((entry) => entry.name)).toEqual(["news-scanner", "market-movers", "event-calendar", "portfolio-review"]);
  });

  it.each(SCENARIOS.map((entry) => [entry.id, entry] as const))("%s: a desk never changes place once it has one", (_id, entry) => {
    let placed: string[] = [];
    for (let cursor = 1; cursor <= entry.events.length; cursor += 1) {
      const names = room(entry.events.slice(0, cursor)).desks.map((item) => item.name);
      expect(names.slice(0, placed.length)).toEqual(placed);
      placed = names;
    }
  });
});

describe("every state has a face and words", () => {
  const FACES: Readonly<Record<Activity, readonly Face[]>> = {
    spawned: ["dot"],
    calling: ["asking"],
    thinking: ["thinking", "alert"],
    executing: ["tool"],
    waiting: ["question"],
    completed: ["tick", "knot"],
  };

  it("draws each reducer activity as its own face, with a label", () => {
    const seen = new Set<Face>();
    for (const entry of SCENARIOS) {
      for (let cursor = 1; cursor <= entry.events.length; cursor += 1) {
        for (const item of everyone(room(entry.events.slice(0, cursor)))) {
          if (item.ghost) continue;
          expect(FACES[item.activity], `${entry.id} at ${String(cursor)}: ${item.name}`).toContain(item.face);
          expect(item.stateLabel).not.toBe("");
          expect(item.accessibleName).toContain(item.name);
          seen.add(item.face);
        }
      }
    }
    // Between them the scenarios reach every face.
    expect([...seen].sort()).toEqual(["alert", "asking", "dot", "knot", "question", "thinking", "tick", "tool"]);
  });

  it("names the tool family at work, for every family", () => {
    for (const [name, info] of Object.entries(TOOLS)) {
      const log = new LogBuilder();
      const office = room([
        log.add("run.started", { goal: "g" }),
        log.add("agent.spawned", { role: "Does one thing" }, "worker"),
        log.add("llm.request", { step: 1 }, "worker"),
        log.add("llm.response", { text: "" }, "worker"),
        log.add("tool.requested", { tool: name, args: {}, call_id: "c1" }, "worker"),
        log.add("tool.called", { tool: name, args: {}, call_id: "c1" }, "worker"),
      ]);
      const worker = desk(office, "worker");
      expect(worker).toMatchObject({ face: "tool", family: info.family });
      expect(worker.slips).toMatchObject([{ tool: name, family: info.family, state: "working" }]);
    }
    expect(TOOL_FAMILIES).toContain("unknown");
  });

  it("shows a stuck worker as a knot, not a tick", () => {
    expect(desk(at("stuck-worker"), "researcher")).toMatchObject({ activity: "completed", face: "knot", stateLabel: "Stuck" });
  });

  it("gives a tick only to an agent that finished: out of steps is a stop", () => {
    const ended = (reason: string) => {
      const log = new LogBuilder();
      return room([log.add("run.started", { goal: "g" }), log.add("agent.spawned", {}, "worker"), log.add("agent.completed", { reason }, "worker")]);
    };
    expect(desk(ended("finished"), "worker")).toMatchObject({ face: "tick", stateLabel: "Done" });
    expect(desk(ended("handoff"), "worker")).toMatchObject({ face: "tick", stateLabel: "Handed on" });
    expect(desk(ended("max_steps"), "worker")).toMatchObject({ face: "knot", stateLabel: "Ran out of steps" });
    expect(desk(ended("timeout"), "worker")).toMatchObject({ face: "knot", stateLabel: "Stopped" });
    expect(ended("finished").announcement?.text).toBe("worker finished.");
    expect(ended("max_steps").announcement?.text).toBe("worker stopped: ran out of steps.");
  });

  it("shows a desk that needs the viewer as a question, whatever failed before it", () => {
    // Two calls from one answer: the first fails, the second asks.
    const log = new LogBuilder();
    const office = room([
      log.add("run.started", { goal: "g" }),
      log.add("llm.request", { step: 1 }, "worker"),
      log.add("llm.response", { text: "" }, "worker"),
      log.add("tool.requested", { tool: "http_get", args: { url: "https://example.org/a" }, call_id: "c1" }, "worker"),
      log.add("tool.called", { tool: "http_get", args: { url: "https://example.org/a" }, call_id: "c1" }, "worker"),
      log.add("tool.error", { tool: "http_get", call_id: "c1", error: "The site refused the request." }, "worker"),
      log.add("tool.requested", { tool: "run_shell", args: { command: "ls" }, call_id: "c2" }, "worker"),
      log.add("approval.requested", { approval_id: "a1", tool: "run_shell", risk: "high", prompt: "?" }, "worker"),
    ]);
    const worker = desk(office, "worker");
    expect(worker).toMatchObject({ activity: "waiting", face: "question", stateLabel: "Waiting for you" });
    // The failure is still on the desk, as a paper, not as the face.
    expect(worker.trouble?.kind).toBe("alarm");
  });

  it("marks a failure as an alarm and a missed lookup as a note", () => {
    // The model call was retried once and then refused for good: the retry
    // leaves no mark, the refusal does.
    expect(at("failed-run").lead).toMatchObject({ face: "alert", stateLabel: "Hit an error", trouble: { kind: "alarm" } });

    const missed = scenario("missed-lookup").events;
    const noted = everyone(room(missed.slice(0, after(missed, (event) => event.type === "tool.error"))));
    const calm = noted.find((item) => item.trouble !== null);
    expect(calm?.trouble?.kind).toBe("note");
    // A note is not an alarm: the face stays what the agent is doing.
    expect(calm?.face).not.toBe("alert");
    expect(calm?.slips.at(-1)?.state).toBe("missed");
  });

  it("seats nobody at a desk whose agent never started", () => {
    const office = at("ghost-handoff");
    const ghosts = office.desks.filter((item) => item.ghost);
    expect(ghosts.length).toBeGreaterThan(0);
    for (const ghost of ghosts) expect(ghost).toMatchObject({ stateLabel: "Not started", slips: [], results: 0, latestSeq: 0 });
  });
});

describe("slips and stamps", () => {
  const stamps = (office: OfficeModel): Stamp["kind"][] =>
    everyone(office).flatMap((item) => item.slips.flatMap((slip) => (slip.stamp === null ? [] : [slip.stamp.kind])));

  it("stamps a policy answer with its rule and the host it reached", () => {
    const { events } = scenario("morning-collection");
    const cursor = after(events, (event) => event.type === "tool.called" && event.payload?.tool === "read_feed");
    const slip = everyone(room(events.slice(0, cursor))).flatMap((item) => item.slips).find((item) => item.tool === "read_feed");
    expect(slip).toMatchObject({ state: "working", stamp: { kind: "policy", rule: "level" }, label: "Allowed by policy", family: "network" });
    expect(slip?.host).toBe("news.google.com");
    if (slip?.stamp === undefined || slip.stamp === null) throw new Error("no stamp");
    expect(stampReason(slip.stamp, slip)).toBe("medium risk runs on its own, reaching news.google.com");
  });

  it("shows a question as waiting, in its risk, and counts it at the reception", () => {
    const office = at("shell-question");
    const researcher = desk(office, "researcher");
    expect(researcher).toMatchObject({ face: "question", stateLabel: "Waiting for you" });
    expect(researcher.slips.at(-1)).toMatchObject({ tool: "run_shell", family: "shell", state: "waiting", risk: "high", stamp: null });
    expect(office.reception).toMatchObject({ waiting: 1, waitingRisk: "high" });
  });

  it("shows a sandbox refusal as a barrier, in the gate's words", () => {
    const { events } = scenario("sandbox-denial");
    const cursor = after(events, (event) => event.type === "tool.denied");
    const slips = everyone(room(events.slice(0, cursor))).flatMap((item) => item.slips);
    expect(slips.at(-1)).toMatchObject({ state: "refused", stamp: { kind: "sandbox" }, label: "Outside this space's folder" });
  });

  it("keeps a slip until its agent's next model call, then clears the desk", () => {
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      log.add("llm.request", { step: 1 }, "writer"),
      log.add("llm.response", { text: "" }, "writer"),
      log.add("tool.requested", { tool: "read_file", args: { path: "a.md" }, call_id: "c1" }, "writer"),
      log.add("tool.called", { tool: "read_file", args: { path: "a.md" }, call_id: "c1" }, "writer"),
      log.add("tool.result", { tool: "read_file", call_id: "c1", result: "text" }, "writer"),
      log.add("tool.requested", { tool: "read_file", args: { path: "b.md" }, call_id: "c2" }, "writer"),
      log.add("tool.error", { tool: "read_file", call_id: "c2", error: "No such file." }, "writer"),
      log.add("agent.thinking", { step: 2 }, "writer"),
      log.add("llm.request", { step: 2 }, "writer"),
    ];
    const states = (cursor: number) => desk(room(events.slice(0, cursor)), "writer").slips.map((slip) => `${slip.action}: ${slip.state}`);
    expect(states(3)).toEqual([]);
    expect(states(4)).toEqual(["read a.md: requested"]);
    expect(states(5)).toEqual(["read a.md: working"]);
    expect(states(6)).toEqual(["read a.md: done"]);
    // Two calls from one answer: each keeps what became of it.
    expect(states(8)).toEqual(["read a.md: done", "read b.md: missed"]);
    expect(states(9)).toEqual(["read a.md: done", "read b.md: missed"]);
    expect(states(10)).toEqual([]);
    expect(desk(room(events.slice(0, 9)), "writer")).toMatchObject({ results: 1, trouble: { kind: "note" } });
  });

  it("stamps a rule's refusal as not allowed, never as a person's no", () => {
    const refusedBy = (approval: Record<string, unknown>) => {
      const log = new LogBuilder();
      const office = room([
        log.add("run.started", { goal: "g" }),
        log.add("llm.request", { step: 1 }, "worker"),
        log.add("tool.requested", { tool: "run_shell", args: { command: "ls" }, call_id: "c1" }, "worker"),
        log.add("approval.requested", { approval_id: "a1", tool: "run_shell", risk: "high", prompt: "?", ...approval }, "worker"),
        log.add("approval.resolved", { approval_id: "a1", status: "denied" }, "worker"),
        log.add("tool.denied", { tool: "run_shell", reason: "no" }, "worker"),
      ]);
      return desk(office, "worker").slips.at(-1);
    };
    // A tool that is never allowed: nobody was asked.
    expect(refusedBy({ automatic: true, policy: true })).toMatchObject({ state: "refused", stamp: { kind: "refused" }, label: "Not allowed" });
    // A person who was asked and said no.
    expect(refusedBy({})).toMatchObject({ state: "refused", stamp: { kind: "denied" }, label: "Denied" });
  });

  it("reads a pending fetch's host as the fetch itself would", () => {
    const hostFor = (url: string) => {
      const log = new LogBuilder();
      const office = room([
        log.add("run.started", { goal: "g" }),
        log.add("llm.request", { step: 1 }, "worker"),
        log.add("tool.requested", { tool: "http_get", args: { url }, call_id: "c1" }, "worker"),
      ]);
      return desk(office, "worker").slips.at(-1)?.host;
    };
    expect(hostFor("https://news.example.org/feed?x=1")).toBe("news.example.org");
    // Text before an @ is a user name, not where the request goes.
    expect(hostFor("https://api.example.com:443@evil.test/x")).toBe("evil.test");
    expect(hostFor("not a url")).toBeNull();
  });

  it("puts every stamp kind into words", () => {
    const kinds: Stamp[] = [
      { kind: "policy", rule: "tool", host: null },
      { kind: "precedent" },
      { kind: "allowed", scope: "call" },
      { kind: "allowed", scope: "run" },
      { kind: "denied" },
      { kind: "expired" },
      { kind: "sandbox" },
      { kind: "refused" },
    ];
    const labels = kinds.map(stampLabel);
    expect(labels.every((label) => label !== "")).toBe(true);
    expect(new Set(labels).size).toBe(labels.length);
    expect(stampReason({ kind: "policy", rule: "tool", host: null }, { tool: "write_file", risk: "medium" })).toBe(
      "write_file is always allowed",
    );
    expect(stampReason({ kind: "denied" }, { tool: "write_file", risk: "medium" })).toBeNull();
  });

  it("reaches person, policy and refusal stamps across the scenarios", () => {
    const seen = new Set(SCENARIOS.flatMap((entry) => entry.events.flatMap((_, index) => stamps(room(entry.events.slice(0, index + 1))))));
    expect(seen.has("policy")).toBe(true);
    expect(seen.has("sandbox")).toBe(true);
  });
});

describe("folders last for a span of events", () => {
  const events = twoAgentRun();
  const handoff = after(events, (event) => event.type === "agent.handoff");
  const phaseAt = (cursor: number) => {
    const office = room(events.slice(0, cursor));
    return {
      flying: office.folders.map((folder) => folder.phase),
      inbox: desk(office, "researcher").inbox.length,
      returned: office.lead?.returned ?? 0,
    };
  };

  it("is arriving from the handoff until the receiver's next event", () => {
    expect(phaseAt(handoff)).toMatchObject({ flying: ["arriving"], inbox: 0 });
    const receiverActs = events.findIndex((event, index) => index >= handoff && event.agent_id === "researcher");
    for (let cursor = handoff; cursor <= receiverActs; cursor += 1) expect(phaseAt(cursor).flying).toEqual(["arriving"]);
    expect(phaseAt(receiverActs + 1)).toMatchObject({ flying: [], inbox: 1 });
  });

  it("lies on the receiver's desk while it works, then returns to the sender", () => {
    const completed = after(events, (event) => event.type === "agent.completed" && event.agent_id === "researcher");
    expect(phaseAt(completed - 1)).toMatchObject({ flying: [], inbox: 1 });
    expect(phaseAt(completed)).toMatchObject({ flying: ["returning"], inbox: 0, returned: 0 });

    const senderActs = events.findIndex((event, index) => index >= completed && event.agent_id === "supervisor");
    expect(phaseAt(senderActs + 1)).toMatchObject({ flying: [], inbox: 0, returned: 1 });
  });

  it("carries the task it was given", () => {
    const office = room(events.slice(0, handoff));
    expect(office.folders[0]).toMatchObject({ from: "supervisor", to: "researcher" });
    expect(office.folders[0]?.task).not.toBe("");
  });

  it("treats a worker's handoff as a request, not as work delivered", () => {
    // The sidecar starts a worker and then hands it its work; a worker that
    // hands off only asks, completes, and the supervisor decides.
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      log.add("agent.spawned", {}, "supervisor"),
      log.add("agent.spawned", {}, "researcher"),
      log.add("agent.handoff", { to: "researcher", task: "Find it" }, "supervisor"),
      log.add("agent.thinking", { step: 1 }, "researcher"),
      log.add("agent.completed", { reason: "finished" }, "researcher"),
      log.add("tool.result", { tool: "spawn_agent", result: "found" }, "supervisor"),
      log.add("agent.spawned", {}, "writer"),
      log.add("agent.handoff", { to: "writer", task: "Write it" }, "supervisor"),
      log.add("agent.thinking", { step: 1 }, "writer"),
      // The writer asks for the researcher, who finished long ago.
      log.add("agent.handoff", { to: "researcher", task: "Check a figure" }, "writer"),
      log.add("agent.completed", { reason: "handoff" }, "writer"),
    ];
    const office = room(events);
    // Nothing is left in flight at the finished researcher's desk.
    expect(office.folders.filter((folder) => folder.to === "researcher")).toEqual([]);
    expect(desk(office, "researcher").inbox).toEqual([]);
    // A request is never counted as work that came back to the one who asked.
    expect(desk(office, "writer").returned).toBe(0);
    expect(desk(office, "writer")).toMatchObject({ face: "tick", stateLabel: "Handed on" });
    // The supervisor's own delegation to the writer is on its way back.
    expect(office.folders).toMatchObject([{ kind: "delegated", to: "writer", phase: "returning" }]);
  });

  it("stays arriving at an empty chair when nobody ever starts", () => {
    const office = at("ghost-handoff");
    const ghost = office.desks.find((item) => item.ghost);
    expect(office.folders.some((folder) => folder.to === ghost?.name && folder.phase === "arriving")).toBe(true);
  });
});

describe("claims and evidence stay apart", () => {
  it("shows streaming text as a thought, only while the model call is open", () => {
    const events = twoAgentRun();
    const token = after(events, (event) => event.type === "llm.token");
    const speaker = events[token - 1]?.agent_id ?? "";
    expect(desk(room(events.slice(0, token)), speaker).bubble?.kind).toBe("thought");
    const answered = events.findIndex((event, index) => index >= token && event.type === "llm.response" && event.agent_id === speaker);
    expect(desk(room(events.slice(0, answered + 1)), speaker).bubble).toBeNull();
  });

  it("shows only the end of a long stream", () => {
    const log = new LogBuilder();
    const office = room([
      log.add("run.started", { goal: "g" }),
      log.add("llm.request", { step: 1 }, "writer"),
      log.add("llm.token", { text: `${"word ".repeat(60)}the end` }, "writer"),
    ]);
    const bubble = desk(office, "writer").bubble;
    expect(bubble?.text.endsWith("the end")).toBe(true);
    expect(bubble?.text.startsWith("…")).toBe(true);
    expect(bubble?.text.length).toBeLessThanOrEqual(81);
  });

  it("keeps what a finished agent said until its work is back with the sender", () => {
    // The sidecar reports and completes in the same breath: `agent.message`,
    // then the speaker's own `agent.completed`. The words must outlast that.
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      log.add("agent.spawned", {}, "supervisor"),
      log.add("agent.spawned", {}, "writer"),
      log.add("agent.handoff", { to: "writer", task: "Write it up" }, "supervisor"),
      log.add("llm.request", { step: 1 }, "writer"),
      log.add("llm.response", { text: "" }, "writer"),
      log.add("agent.message", { text: "The draft is ready." }, "writer"),
      log.add("agent.completed", { reason: "finished", steps: 1 }, "writer"),
      log.add("tool.result", { tool: "spawn_agent", result: "done" }, "supervisor"),
    ];
    const said = { kind: "speech", text: "The draft is ready." };
    expect(desk(room(events.slice(0, 7)), "writer").bubble).toEqual(said);
    // Still up once it has completed, while the folder is on its way back.
    expect(desk(room(events.slice(0, 8)), "writer").bubble).toEqual(said);
    expect(room(events.slice(0, 8)).folders.map((folder) => folder.phase)).toEqual(["returning"]);
    // Down once the supervisor has it.
    expect(desk(room(events), "writer").bubble).toBeNull();
  });

  it("takes an agent's words down when it asks its model again", () => {
    const log = new LogBuilder();
    const events = [
      log.add("run.started", { goal: "g" }),
      log.add("agent.spawned", {}, "writer"),
      log.add("agent.message", { text: "Halfway there." }, "writer"),
      log.add("agent.spawned", {}, "reviewer"),
      log.add("agent.thinking", { step: 2 }, "writer"),
      log.add("llm.request", { step: 2 }, "writer"),
    ];
    // Another desk acting, or its own next step starting, leaves them up.
    expect(desk(room(events.slice(0, 5)), "writer").bubble).toEqual({ kind: "speech", text: "Halfway there." });
    expect(desk(room(events), "writer").bubble?.kind).toBe("thought");
  });

  it("puts the run's summary on the board as a claim, and files as evidence", () => {
    const office = room(twoAgentRun());
    expect(office.board.status).toBe("completed");
    expect(office.board.claim?.kind).toBe("summary");
    // The fixture's summary claims more than its tool calls did: the board
    // lists only what a tool actually wrote.
    for (const document of office.board.documents) expect(document.path).not.toBe("");
    expect(at("morning-collection").board).toMatchObject({ memoryPath: "memory/runs/run-morning.md" });
  });
});

describe("the rest of the room", () => {
  it("says where the run came from", () => {
    expect(at("two-agents").reception).toMatchObject({ origin: "Started by you", source: "window", waiting: 0, waitingRisk: null });
    expect(at("morning-collection").reception).toMatchObject({ origin: "From schedule", source: "schedule" });
    expect(at("discord-origin").reception).toMatchObject({ origin: "From Discord", source: "discord" });
    expect(at("discord-origin").reception.sender).not.toBeNull();
  });

  it("hands the lead desk one book per retrieved excerpt", () => {
    expect(at("morning-collection").library).toHaveLength(2);
    expect(at("two-agents").library).toEqual([]);
  });

  it("reads the clock from the log's own timestamps, against the run's limit", () => {
    const events = twoAgentRun();
    // LogBuilder stamps one second per event.
    expect(room(events).clock).toEqual({ elapsedSeconds: events.length - 1, limitSeconds: 900 });
    expect(room(events.slice(0, 1)).clock.elapsedSeconds).toBe(0);
  });

  it("turns the meter amber on a warning and red when the limit is reached", () => {
    expect(at("two-agents").meter.level).toBe("ok");
    expect(at("budget-warning").meter).toMatchObject({ level: "warn" });
    expect(at("budget-warning").meter.percent).not.toBeNull();
    expect(at("over-budget").meter.level).toBe("over");
  });

  it("dims the room for a cancelled run, and says how each run ended", () => {
    expect(at("cancelled-run")).toMatchObject({ dimmed: true, status: "cancelled" });
    expect(at("cancelled-run").board.statusLabel).toBe("cancelled");
    expect(at("failed-run")).toMatchObject({ dimmed: false, status: "failed" });
    expect(at("two-agents").lit).toBe(true);
  });

  it("names an event type this build does not know, on the board", () => {
    const log = new LogBuilder();
    const office = room([log.add("run.started", { goal: "g" }), { ...log.add("run.started"), type: "agent.dreamed" as Event["type"] }]);
    expect(office.board.unrecognised).toEqual(["agent.dreamed"]);
  });

  it("follows the desk with the latest event", () => {
    const events = twoAgentRun();
    for (let cursor = 2; cursor <= events.length; cursor += 1) {
      const latest = events.slice(0, cursor).findLast((event) => event.agent_id !== null)?.agent_id ?? null;
      expect(room(events.slice(0, cursor)).focus).toBe(latest);
    }
  });

  it("says a budget warning apart from completions, so neither talks over the other", () => {
    const log = new LogBuilder();
    const office = room([
      log.add("run.started", { goal: "g" }),
      log.add("agent.spawned", {}, "researcher"),
      log.add("agent.completed", { reason: "finished" }, "researcher"),
      log.add("agent.spawned", {}, "writer"),
      log.add("budget.warning", { percent: 82, spent_micros: 1, cap_micros: 2 }),
    ]);
    expect(office.announcement?.text).toBe("researcher finished.");
    expect(office.meter.announcement).toBe("Spending is close to the monthly limit.");
    expect(at("two-agents").meter.announcement).toBeNull();
    expect(at("over-budget").meter.announcement).toBe("The monthly limit is reached.");
  });

  it("announces a completion and the run's end once each, by a key that changes", () => {
    const events = twoAgentRun();
    const keys = events.map((_, index) => room(events.slice(0, index + 1)).announcement?.key ?? null);
    const distinct = keys.filter((key, index) => key !== null && key !== keys[index - 1]);
    // One per agent that finished, then the run's own end.
    expect(distinct.at(-1)).toBe("run-completed");
    expect(distinct.filter((key) => key?.startsWith("done-")).length).toBe(2);
    expect(room(events).announcement?.text).toBe("The run completed.");
  });

  it("stays legible with twelve and twenty desks", () => {
    // Counting the lead desk.
    expect(everyone(at("twelve-desks"))).toHaveLength(12);
    expect(everyone(at("twenty-desks"))).toHaveLength(20);
  });
});
