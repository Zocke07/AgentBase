import type { Event, EventType } from "@agentspace/schemas";
import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import { EMPTY_RUN, pendingApprovals, reduce, reduceAll } from "./reducer";



/**
 * The run reducer — the UI's half of BUILD_SPEC §2.
 *
 * "Every agent action is an append-only event. The UI is a pure projection of
 * the event log." This function is that projection, and everything the
 * dashboard shows is derived here and nowhere else. The tests below are
 * therefore about two separate claims:
 *
 *  - it is a *fold*: the same events in the same order give the same state,
 *    however they were delivered. That is what makes live and replay the same
 *    rendering path rather than two paths that agree today.
 *  - it renders the log *honestly*: what an agent claimed and what it actually
 *    did are separate fields, because CLAUDE.md records three live runs where
 *    they disagreed.
 */

const ALL_EVENT_TYPES: EventType[] = [
  "run.started",
  "run.completed",
  "run.failed",
  "run.paused",
  "run.cancelled",
  "agent.spawned",
  "agent.thinking",
  "agent.message",
  "agent.handoff",
  "agent.completed",
  "llm.request",
  "llm.token",
  "llm.response",
  "llm.error",
  "tool.requested",
  "tool.approved",
  "tool.denied",
  "tool.called",
  "tool.result",
  "tool.error",
  "approval.requested",
  "approval.resolved",
  "budget.warning",
  "budget.exceeded",
  "channel.inbound",
  "channel.outbound",
];

// --- it is a fold -----------------------------------------------------------

describe("the reducer as a fold", () => {
  it("gives the same state whether events arrive one at a time or all at once", () => {
    const events = twoAgentRun();

    const incremental = events.reduce(reduce, EMPTY_RUN);
    const bulk = reduceAll(events);

    expect(incremental).toEqual(bulk);
  });

  it("gives the same state whatever the delivery chunking", () => {
    /* SSE decides its own frame boundaries and a reconnect re-reads a range, so
       the client legitimately receives the same log in different batch sizes. */
    const events = twoAgentRun();
    const expected = reduceAll(events);

    for (const size of [1, 2, 3, 7, events.length]) {
      let state = EMPTY_RUN;
      for (let index = 0; index < events.length; index += size) {
        state = reduceAll(events.slice(index, index + size), state);
      }
      expect(state).toEqual(expected);
    }
  });

  it("never mutates the state it was given", () => {
    const events = twoAgentRun();
    const start = reduceAll(events.slice(0, 10));
    const before = structuredClone(start);

    reduceAll(events.slice(10), start);

    expect(start).toEqual(before);
  });

  it("is a pure function of the events, with no clock in it", () => {
    /* The whole "pixel-identical replay" criterion rests on this. A reducer
       that stamped `Date.now()` anywhere would produce a different state on
       every fold, and no amount of care in the components could recover it. */
    const events = twoAgentRun();

    expect(JSON.stringify(reduceAll(events))).toEqual(JSON.stringify(reduceAll(events)));
  });

  it("folds a prefix to exactly the state that prefix produced live", () => {
    /* Replay scrubbing is this property. Position N of the scrubber must show
       what the user saw when event N arrived, or the scrubber is a different
       view of the run rather than the same one. */
    const events = twoAgentRun();

    let live = EMPTY_RUN;
    let applied = 0;
    for (const event of events) {
      live = reduce(live, event);
      applied += 1;
      expect(reduceAll(events.slice(0, applied))).toEqual(live);
    }
  });
});

// --- it handles every event type -------------------------------------------

describe("the event contract", () => {
  it("recognises every type in the §4 list", () => {
    /* Phase 2's lesson in a new place: a named SSE event silently bypassed the
       client for any type it had not registered, and the failure was invisible.
       An unrecognised type must reach the reducer and be *reported*, never
       dropped, so 26 types and a client that knows 25 is a visible fact. */
    for (const type of ALL_EVENT_TYPES) {
      const log = new LogBuilder();
      const state = reduce(EMPTY_RUN, log.add(type, {}, "supervisor"));
      expect(state.unrecognised).toEqual([]);
    }
  });

  it("reports an unrecognised type loudly rather than dropping it", () => {
    const log = new LogBuilder();
    const rogue = { ...log.add("run.started"), type: "agent.teleported" as EventType };

    const state = reduce(EMPTY_RUN, rogue);

    expect(state.unrecognised).toEqual(["agent.teleported"]);
  });

  it("survives a payload with every field missing", () => {
    /* Payloads are `dict[str, Any]` on the wire. A reducer that assumed a field
       was present would take the dashboard down on a malformed event instead of
       rendering the rest of a run that is otherwise fine. */
    for (const type of ALL_EVENT_TYPES) {
      const log = new LogBuilder();
      expect(() => reduce(EMPTY_RUN, log.add(type, {}, null))).not.toThrow();
    }
  });
});

// --- it renders the log honestly -------------------------------------------

describe("what an agent claimed versus what it did", () => {
  it("keeps the terminal summary as a claim, not as an outcome", () => {
    /* CLAUDE.md, three separate live runs: a run completed with "saved to
       notes.txt" having made no file call at all. The summary is a model's
       assertion; the `tool.called` events are what happened. The reducer keeps
       them in different fields so the UI cannot accidentally present one as
       the other. */
    const state = reduceAll(twoAgentRun());

    expect(state.claim).toEqual({
      kind: "summary",
      text: "Quarterly report summarised and saved to notes.txt.",
    });
    expect(state.toolCalls.map((call) => call.tool)).toEqual(["spawn_agent", "write_file"]);
  });

  it("records a failure reason as a claim of the same kind", () => {
    const log = new LogBuilder();
    const state = reduceAll([log.add("run.failed", { reason: "This run hit its time limit." })]);

    expect(state.status).toBe("failed");
    expect(state.claim).toEqual({ kind: "reason", text: "This run hit its time limit." });
  });

  it("counts only executed calls as tool calls", () => {
    /* A requested call, a denied call and an executed call are three different
       facts. Only the last one touched anything. */
    const state = reduceAll(twoAgentRun());

    expect(state.requested).toHaveLength(3);
    expect(state.denials).toHaveLength(1);
    expect(state.toolCalls).toHaveLength(2);
  });
});

describe("denials", () => {
  it("carries blocked_by so a traversal attempt is not a declined write", () => {
    /* CLAUDE.md: "The user said no" and "the agent tried to leave the
       workspace" are the same event type and very different things to see. */
    const state = reduceAll(twoAgentRun());

    expect(state.denials[0]).toMatchObject({
      agent: "researcher",
      tool: "read_file",
      blockedBy: "sandbox",
    });
  });

  it("leaves blockedBy null when the user simply declined", () => {
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("tool.denied", { tool: "write_file", reason: "The user denied this call." }, "worker"),
    ]);

    expect(state.denials[0]?.blockedBy).toBeNull();
  });
});

describe("approvals", () => {
  it("keeps the whole history, not only what is outstanding", () => {
    /* CLAUDE.md, watched live: a denial stops a call, not a run. The supervisor
       spawned a second worker and asked the same question again. A dialog that
       only ever shows the outstanding question makes that look like one event. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("approval.requested", { approval_id: "a1", tool: "write_file", risk: "medium", prompt: "First ask" }, "escaper"),
      log.add("approval.resolved", { approval_id: "a1", tool: "write_file", status: "denied" }, "escaper"),
      log.add("approval.requested", { approval_id: "a2", tool: "write_file", risk: "medium", prompt: "Second ask" }, "escaper-2"),
      log.add("approval.resolved", { approval_id: "a2", tool: "write_file", status: "denied" }, "escaper-2"),
    ]);

    expect(state.approvals.map((approval) => approval.status)).toEqual(["denied", "denied"]);
    expect(state.approvals.map((approval) => approval.agent)).toEqual(["escaper", "escaper-2"]);
  });

  it("renders the prompt the log recorded rather than composing one", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.approvals[0]?.prompt).toBe(
      'Agent "researcher" wants to create notes.txt (31 characters) — Allow / Deny',
    );
  });

  it("marks an approval pending until its resolution arrives", () => {
    const events = twoAgentRun();
    const uptoRequest = events.findIndex((event) => event.type === "approval.requested") + 1;

    const waiting = reduceAll(events.slice(0, uptoRequest));

    expect(waiting.approvals[0]?.status).toBe("pending");
    expect(pendingApprovals(waiting)).toHaveLength(1);
  });

  it("distinguishes a policy's yes from a person's yes", () => {
    /* `tool.approved` carries `automatic` precisely so "what did this run do
       without asking me" stays answerable. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("approval.requested", { approval_id: "a1", tool: "read_file", risk: "low", prompt: "Read?", automatic: true }, "w"),
      log.add("approval.resolved", { approval_id: "a1", tool: "read_file", status: "approved", automatic: true }, "w"),
    ]);

    expect(state.approvals[0]).toMatchObject({ status: "approved", automatic: true });
  });

  it("does not treat a policy's question as one a person must answer", () => {
    /* The gate emits `approval.requested {automatic: true}` and then, as a
       separate event, `approval.resolved`. Between the two the call is not
       waiting on anybody — the policy already said yes — so nothing here may
       report it as pending, or the dialog appears for one render live and for
       as long as the scrubber sits there on replay. The record still exists,
       so "what did this run do without asking me" stays answerable. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("agent.thinking", { step: 1 }, "w"),
      log.add("approval.requested", { approval_id: "a1", tool: "read_file", risk: "low", prompt: "Read?", automatic: true }, "w"),
    ]);

    expect(pendingApprovals(state)).toHaveLength(0);
    expect(state.approvals).toHaveLength(1);
    expect(state.approvals[0]).toMatchObject({ automatic: true });
    expect(state.agents.w?.activity).not.toBe("waiting");
  });
});

describe("agents", () => {
  it("builds a node per agent from agent.spawned alone", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.agentOrder).toEqual(["supervisor", "researcher"]);
    expect(state.agents.researcher).toMatchObject({
      role: "Gathers source material",
      definitionName: "researcher",
      provider: "ollama",
      model: "qwen3:4b",
      allowedTools: ["read_file", "write_file"],
      maxSteps: 6,
    });
  });

  it("records the system prompt, because it is why two runs differed", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.agents.researcher?.systemPrompt).toBe("You find things out.");
  });

  it("does not treat llm.token as a sign of life", () => {
    /* CLAUDE.md: deltas arrive 1-10 at a time from Anthropic, and a whole run
       against a real Ollama model emitted zero of them. An agent that streamed
       nothing is not an idle agent. */
    const log = new LogBuilder();
    const thinking = reduceAll([
      log.add("agent.spawned", { role: "r" }, "w"),
      log.add("agent.thinking", { step: 1 }, "w"),
    ]);

    expect(thinking.agents.w?.activity).toBe("thinking");
    expect(thinking.agents.w?.streamedText).toBe("");
  });

  it("accumulates streamed text in arrival order", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.agents.researcher?.streamedText).toBe("Reading the report.");
  });

  it("keeps the streamed text of the current model call, not of every call ever made", () => {
    /* One agent makes several model calls per run. Concatenating all of their
       output into one string, with no boundary, renders step 4's answer glued
       to the end of step 1's. What a person watching wants is what the model
       is saying *now*. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("llm.request", { step: 1 }, "w"),
      log.add("llm.token", { text: "first " }, "w"),
      log.add("llm.token", { text: "answer" }, "w"),
      log.add("llm.response", { input_tokens: 1, output_tokens: 1 }, "w"),
      log.add("llm.request", { step: 2 }, "w"),
      log.add("llm.token", { text: "second" }, "w"),
    ]);

    expect(state.agents.w?.streamedText).toBe("second");
  });

  it("reports what an agent is doing at every point of a tool call, not only at its start", () => {
    /* §5 Phase 7 asks for "live status colour". The old machine had four
       transitions and every other event left the label where it was, so an
       agent running a thirty-second shell command read "calling the model" and
       an agent whose approval had been granted read "waiting for approval"
       until its next thinking event. Each row is one event and the activity it
       must leave behind. */
    const log = new LogBuilder();
    const steps: [Event, string][] = [
      [log.add("agent.spawned", { role: "r" }, "w"), "spawned"],
      [log.add("agent.thinking", { step: 1 }, "w"), "thinking"],
      [log.add("llm.request", { step: 1 }, "w"), "calling"],
      [log.add("llm.response", { input_tokens: 1, output_tokens: 1 }, "w"), "thinking"],
      [log.add("tool.requested", { tool: "write_file", call_id: "c1" }, "w"), "thinking"],
      [log.add("approval.requested", { approval_id: "a1", tool: "write_file", risk: "medium", prompt: "?" }, "w"), "waiting"],
      [log.add("approval.resolved", { approval_id: "a1", tool: "write_file", status: "approved" }, "w"), "thinking"],
      [log.add("tool.approved", { tool: "write_file", call_id: "c1", approval_id: "a1" }, "w"), "thinking"],
      [log.add("tool.called", { tool: "write_file", call_id: "c1" }, "w"), "executing"],
      [log.add("tool.result", { tool: "write_file", call_id: "c1", result: "ok" }, "w"), "thinking"],
      [log.add("llm.request", { step: 2 }, "w"), "calling"],
      [log.add("llm.error", { error: "boom" }, "w"), "thinking"],
      [log.add("tool.called", { tool: "run_shell", call_id: "c2" }, "w"), "executing"],
      [log.add("tool.error", { tool: "run_shell", call_id: "c2", error: "timed out" }, "w"), "thinking"],
      [log.add("tool.requested", { tool: "read_file", call_id: "c3" }, "w"), "thinking"],
      [log.add("tool.denied", { tool: "read_file", call_id: "c3", reason: "no" }, "w"), "thinking"],
      [log.add("agent.completed", { reason: "finished", steps: 2 }, "w"), "completed"],
    ];

    let state = EMPTY_RUN;
    for (const [event, expected] of steps) {
      state = reduce(state, event);
      expect(state.agents.w?.activity, `after ${event.type}`).toBe(expected);
    }
  });

  it("remembers an agent's last error until it does something else", () => {
    /* The node is tinted while this is set: an agent that hit an error and
       is thinking about it looked exactly like one that was merely thinking. */
    const log = new LogBuilder();
    const errored = reduceAll([log.add("llm.error", { error: "rate limited" }, "w")]);
    expect(errored.agents.w?.lastError).toBe("rate limited");

    const recovered = reduce(errored, log.add("llm.request", { step: 2 }, "w"));
    expect(recovered.agents.w?.lastError).toBeNull();
  });

  it("names the tool an agent is running", () => {
    const log = new LogBuilder();
    const running = reduceAll([log.add("tool.called", { tool: "run_shell", call_id: "c1" }, "w")]);
    expect(running.agents.w?.currentTool).toBe("run_shell");

    const done = reduce(running, log.add("tool.result", { tool: "run_shell", call_id: "c1", result: "" }, "w"));
    expect(done.agents.w?.currentTool).toBeNull();
  });

  it("marks an agent completed with the reason the log gives", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.agents.researcher).toMatchObject({
      activity: "completed",
      finishedReason: "finished",
      steps: 2,
    });
  });

  it("shows an agent as waiting while its approval is outstanding", () => {
    const events = twoAgentRun();
    const uptoRequest = events.findIndex((event) => event.type === "approval.requested") + 1;

    const waiting = reduceAll(events.slice(0, uptoRequest));

    expect(waiting.agents.researcher?.activity).toBe("waiting");
  });

  it("creates a node for an agent that only ever appears as an agent_id", () => {
    /* Defensive, and not hypothetically: `agent.spawned` is emitted by the
       supervisor for its workers, and a log truncated by a resume can start
       mid-run. A missing node would drop every subsequent event for it. */
    const log = new LogBuilder();
    const state = reduceAll([log.add("agent.thinking", { step: 3 }, "orphan")]);

    expect(state.agents.orphan?.steps).toBe(3);
  });
});

describe("handoffs", () => {
  it("records each one as an edge with its task", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.handoffs).toEqual([
      { from: "supervisor", to: "researcher", task: "Find the figures", seq: 9 },
    ]);
  });
});

describe("tokens and budget", () => {
  it("totals usage from llm.response", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.inputTokens).toBe(900);
    expect(state.outputTokens).toBe(100);
  });

  it("totals what the run cost from llm.response", () => {
    /* The ledger's figure travels in the event, so a replay can say what a
       run cost without a side query — and an unwrapped provider, which sends
       null, adds nothing rather than breaking the fold. */
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("llm.response", { input_tokens: 1, output_tokens: 1, cost_micros: 1200 }, "a"),
      log.add("llm.response", { input_tokens: 1, output_tokens: 1, cost_micros: 800 }, "a"),
      log.add("llm.response", { input_tokens: 1, output_tokens: 1, cost_micros: null }, "a"),
    ]);

    expect(state.costMicros).toBe(2000);
  });

  it("takes the latest budget figures from budget events", () => {
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("budget.warning", { spent_micros: 800, cap_micros: 1000, percent: 80, reason: "80%" }),
      log.add("budget.exceeded", { spent_micros: 1000, cap_micros: 1000, reason: "over" }),
    ]);

    expect(state.budget).toMatchObject({ spentMicros: 1000, capMicros: 1000 });
    expect(state.budgetExceeded).toBe(true);
  });
});

describe("run identity", () => {
  it("takes the goal and limits from run.started", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.goal).toBe("Summarise the quarterly report");
    expect(state.limits).toMatchObject({ max_agents_per_run: 4 });
  });

  it("keeps when the run started and when its latest event was, from their own ts", () => {
    /* The summary shows a duration from these. Both come from the log, so a
       replay shows the same duration the live view did — never a clock. */
    const events = twoAgentRun();
    const state = reduceAll(events);

    expect(state.startedTs).toBe(events[0]?.ts);
    expect(state.latestTs).toBe(events.at(-1)?.ts);
    expect(reduceAll(events.slice(0, 5)).latestTs).toBe(events[4]?.ts);
  });

  it("tracks the run id and head sequence from the events themselves", () => {
    const events = twoAgentRun();
    const state = reduceAll(events);

    expect(state.runId).toBe("run-1");
    expect(state.lastSeq).toBe(events.length);
  });

  it("starts from a state that renders as an empty run", () => {
    expect(EMPTY_RUN.agentOrder).toEqual([]);
    expect(EMPTY_RUN.status).toBe("pending");
    expect(EMPTY_RUN.claim).toBeNull();
  });
});

describe("errors", () => {
  it("keeps llm and tool errors where the log panel can show them", () => {
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("llm.error", { error: "provider refused" }, "w"),
      log.add("tool.error", { tool: "read_file", error: "no such file" }, "w"),
    ]);

    expect(state.errors).toEqual([
      { agent: "w", kind: "llm", message: "provider refused", seq: 1 },
      { agent: "w", kind: "tool", message: "no such file", seq: 2 },
    ]);
  });
});

describe("a partial log", () => {
  it("reduces a run that never reached a terminal event", () => {
    const events: Event[] = twoAgentRun().slice(0, 12);

    const state = reduceAll(events);

    expect(state.status).toBe("running");
    expect(state.claim).toBeNull();
  });
});

describe("channel-originated runs", () => {
  it("records where a run came from, and as which internal identity", () => {
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("channel.inbound", {
        channel: "discord",
        external_user_id: "4210",
        text: "Summarise q3.md",
        thread_ref: "channel-1",
        trigger: "command",
        display_name: "Owner",
        identity: "owner",
      }),
      log.add("run.started", { goal: "Summarise q3.md" }),
    ]);

    expect(state.origin).toEqual({
      channel: "discord",
      identity: "owner",
      displayName: "Owner",
      threadRef: "channel-1",
      trigger: "command",
    });
    // The rest of the fold is untouched: a Discord run is an ordinary run.
    expect(state.goal).toBe("Summarise q3.md");
    expect(state.status).toBe("running");
  });

  it("leaves a run started from this window with no origin", () => {
    const state = reduceAll(twoAgentRun());

    expect(state.origin).toBeNull();
  });

  it("does not let channel.outbound change anything about the run", () => {
    // It records that the run was reported to a conversation, which is a fact
    // about delivery rather than about what the agents did. A graph that moved
    // when a chat message was edited would be projecting the wrong thing.
    const events = twoAgentRun();
    const log = new LogBuilder();
    const extra = log.add("channel.outbound", {
      channel: "discord",
      thread_ref: "channel-1",
      edits: 7,
    });

    const before = reduceAll(events);
    const after = reduceAll([...events, { ...extra, seq: events.length + 1 }]);

    // Bookkeeping that every event moves — the count, the head, the latest
    // stamp — is masked; everything about the *run* must be untouched.
    expect({ ...after, eventCount: 0, lastSeq: 0, latestTs: null }).toEqual({
      ...before,
      eventCount: 0,
      lastSeq: 0,
      latestTs: null,
    });
  });

  it("reports neither channel event as unrecognised", () => {
    const log = new LogBuilder();
    const state = reduceAll([
      log.add("channel.inbound", { channel: "telegram", identity: "owner" }),
      log.add("channel.outbound", { channel: "telegram", edits: 1 }),
    ]);

    expect(state.unrecognised).toEqual([]);
  });
});
