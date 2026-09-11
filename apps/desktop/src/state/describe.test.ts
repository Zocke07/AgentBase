import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import { callPhrase, nowLine, sentenceFor } from "./describe";
import { KNOWN_EVENT_TYPES, reduceAll } from "./reducer";

/**
 * The plain-language layer is a pure function of the log, and these tests
 * pin the two properties that matter about it: every event type gets a real
 * sentence, and the sentences say what the log says — never more.
 */

describe("a sentence for every event", () => {
  it("renders every known event type as something other than its raw name", () => {
    /* A type that fell through to the default would show its raw name, which
       is what the chip beside it already shows. */
    const log = new LogBuilder();
    for (const type of KNOWN_EVENT_TYPES) {
      const event = log.add(type, { tool: "write_file", args: { path: "a.txt" } }, "writer");
      expect(sentenceFor(event), type).not.toBe(type);
      expect(sentenceFor(event), type).not.toBe("");
    }
  });

  it("renders an unknown type as its raw name, claiming nothing", () => {
    const log = new LogBuilder();
    const event = { ...log.add("run.started"), type: "space.renamed" as never };
    expect(sentenceFor(event)).toBe("space.renamed");
  });

  it("names the agent, the tool and the path a person would recognise", () => {
    const [, , , , , requested] = twoAgentRun();
    if (requested === undefined) throw new Error("fixture changed");
    expect(sentenceFor(requested)).toBe("supervisor wants to spawn researcher.");
  });

  it("tells the three refusals apart", () => {
    /* CLAUDE.md: an allowlist refusal, a sandbox violation and a person's
       "no" are all `tool.denied`, and a log that collapsed them would render
       a prompt-injected agent probing the boundary like a declined write. */
    const log = new LogBuilder();
    const args = { path: "../../secrets" };
    const sandbox = log.add(
      "tool.denied",
      { tool: "read_file", args, reason: "That path is outside the workspace.", blocked_by: "sandbox" },
      "researcher",
    );
    const person = log.add(
      "tool.denied",
      { tool: "read_file", args, reason: "The user denied permission.", approval_id: "ap-1" },
      "researcher",
    );
    const allowlist = log.add(
      "tool.denied",
      { tool: "read_file", args, reason: "'researcher' is not permitted to call 'read_file'." },
      "researcher",
    );

    expect(sentenceFor(sandbox)).toContain("The sandbox stopped researcher from reading ../../secrets");
    expect(sentenceFor(person)).toContain("researcher was not allowed to read ../../secrets");
    expect(sentenceFor(allowlist)).toContain("researcher is not permitted to read ../../secrets");
  });

  it("words a terminal summary as the supervisor's claim, not as what happened", () => {
    /* Four live runs have announced work the log shows never happened. */
    const done = twoAgentRun().at(-1);
    if (done === undefined) throw new Error("fixture changed");
    const sentence = sentenceFor(done);
    expect(sentence).toContain("the supervisor says");
    expect(sentence).toContain("saved to notes.txt");
  });

  it("quotes the sidecar's own summary for an approval rather than rebuilding it from the arguments", () => {
    const log = new LogBuilder();
    const asked = log.add(
      "approval.requested",
      { tool: "write_file", args: { path: "notes.txt" }, summary: "overwrite the file notes.txt (31 characters)" },
      "writer",
    );
    expect(sentenceFor(asked)).toBe("writer wants to overwrite the file notes.txt (31 characters) — waiting for you.");

    const byPolicy = log.add(
      "approval.requested",
      { tool: "read_file", args: { path: "a.txt" }, summary: "read the file a.txt", automatic: true },
      "writer",
    );
    expect(sentenceFor(byPolicy)).toBe("writer wants to read the file a.txt — allowed by policy.");
  });

  it("truncates what a model wrote so a row stays a row", () => {
    const log = new LogBuilder();
    const long = log.add("agent.message", { to: "supervisor", text: "x".repeat(500) }, "writer");
    expect(sentenceFor(long).length).toBeLessThan(160);
    expect(sentenceFor(long)).toContain("…");
  });

  it("falls back to the raw call for a tool it has no verb for", () => {
    expect(callPhrase("summon_dragon", { name: "Smaug" }).infinitive).toBe("call summon_dragon(name=Smaug)");
  });
});

describe("the Now line", () => {
  const run = twoAgentRun();
  const at = (cursor: number) => nowLine(reduceAll(run.slice(0, cursor)));
  const indexOf = (type: string, nth = 0) =>
    run.findIndex((event, index) => event.type === type && run.slice(0, index).filter((e) => e.type === type).length === nth);

  it("says nothing is happening before the run starts", () => {
    expect(at(0)).toBe("Waiting for the run to start.");
  });

  it("puts a question waiting on the person above everything else", () => {
    const asked = indexOf("approval.requested");
    expect(at(asked + 1)).toBe("researcher is waiting for your approval.");
  });

  it("names the tool an agent is running", () => {
    const called = indexOf("tool.called", 1);
    expect(at(called + 1)).toBe("researcher is running write_file.");
  });

  it("says who is asking the model", () => {
    const requested = indexOf("llm.request");
    expect(at(requested + 1)).toBe("supervisor is asking the model.");
  });

  it("reads a supervisor's open spawn as waiting on the worker, not as running a tool", () => {
    /* The supervisor's `spawn_agent` stays open for as long as the worker
       works, so for most of a run two agents are "executing" and only one of
       them is doing anything a person would call running a tool. */
    const handed = indexOf("agent.handoff");
    expect(at(handed + 1)).toBe("supervisor is waiting on researcher.");
  });

  it("counts what the run did once it has ended", () => {
    expect(at(run.length)).toBe("The run completed: 2 agents, 2 tool calls, 1 denied.");
  });

  it("reads the same at a cursor whether folded in one go or one event at a time", () => {
    /* The property the identity test depends on, stated for this function. */
    let incremental = reduceAll([]);
    for (const [index, event] of run.entries()) {
      incremental = reduceAll([event], incremental);
      expect(nowLine(incremental)).toBe(at(index + 1));
    }
  });
});
