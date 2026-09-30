import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";

import { callPhrase, nowLine, policySentence, sentenceFor } from "./describe";
import { KNOWN_EVENT_TYPES, reduceAll } from "./reducer";

/**
 * The plain-language layer is a pure function of the log, and these tests
 * pin the two properties that matter about it: every event type gets a real
 * sentence, and the sentences say what the log says, never more.
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

  it("says why an agent stopped, in words", () => {
    const log = new LogBuilder();
    const steps = log.add("agent.completed", { reason: "max_steps", steps: 20 }, "researcher");
    const stuck = log.add("agent.completed", { reason: "stuck", steps: 4, error: "write_file needs a 'path'" }, "researcher");

    expect(sentenceFor(steps)).toBe("researcher ran out of steps after 20 steps.");
    expect(sentenceFor(stuck)).toBe("researcher stopped after failing the same way three times after 4 steps.");
  });

  it("words a terminal summary as the supervisor's claim, not as what happened", () => {
    /* Four live runs have announced work the log shows never happened. */
    const done = twoAgentRun().at(-1);
    if (done === undefined) throw new Error("fixture changed");
    const sentence = sentenceFor(done);
    expect(sentence).toContain("The supervisor says");
    expect(sentence).toContain("saved to notes.txt");
  });

  it("quotes the sidecar's own summary for an approval rather than rebuilding it from the arguments", () => {
    const log = new LogBuilder();
    const asked = log.add(
      "approval.requested",
      { tool: "write_file", args: { path: "notes.txt" }, summary: "overwrite the file notes.txt (31 characters)" },
      "writer",
    );
    expect(sentenceFor(asked)).toBe("writer wants to overwrite the file notes.txt (31 characters): waiting for you.");

    const byPolicy = log.add(
      "approval.requested",
      { tool: "read_file", args: { path: "a.txt" }, summary: "read the file a.txt", automatic: true },
      "writer",
    );
    expect(sentenceFor(byPolicy)).toBe("writer wants to read the file a.txt: allowed by policy.");

    /* A denial sticks for the run: the same call again is settled by the
       earlier answer, and neither event may read as though a person was
       asked or a policy allowed it. */
    const repeat = log.add(
      "approval.requested",
      { tool: "write_file", args: { path: "notes.txt" }, summary: "overwrite the file notes.txt (2 characters)", automatic: true, precedent: "ap-1" },
      "writer-2",
    );
    expect(sentenceFor(repeat)).toBe(
      "writer-2 wants to overwrite the file notes.txt (2 characters): already denied earlier in this run.",
    );
    const repeatSettled = log.add(
      "approval.resolved",
      { approval_id: "ap-2", tool: "write_file", status: "denied", automatic: true, precedent: "ap-1" },
      "writer-2",
    );
    expect(sentenceFor(repeatSettled)).toBe("Your earlier answer denied writer-2's write_file call again.");
  });

  it("says which rule answered a call nobody was asked about", () => {
    /* With autonomy the default, most calls answer themselves; the log is
       where a person reads why each one ran, or did not. */
    const log = new LogBuilder();
    const byLevel = log.add(
      "approval.requested",
      {
        tool: "read_feed",
        summary: "read up to 20 complete entries from https://news.google.com/rss",
        risk: "medium",
        automatic: true,
        rule: "level",
        host: "news.google.com",
      },
      "news-scanner",
    );
    expect(sentenceFor(byLevel)).toBe(
      "news-scanner wants to read up to 20 complete entries from https://news.google.com/rss: allowed by policy (medium risk runs on its own, and news.google.com is a listed site).",
    );
    const byTool = log.add(
      "approval.requested",
      { tool: "write_file", summary: "create the file a.md (1 characters)", risk: "medium", automatic: true, rule: "tool" },
      "writer",
    );
    expect(sentenceFor(byTool)).toContain("allowed by policy (write_file is always allowed)");
    const never = log.add(
      "approval.requested",
      { tool: "http_get", summary: "fetch https://x.test/ over the internet", automatic: true, policy: "deny" },
      "writer",
    );
    expect(sentenceFor(never)).toBe("writer wants to fetch https://x.test/ over the internet: never allowed here.");
    const refused = log.add(
      "approval.resolved",
      { tool: "http_get", status: "denied", automatic: true, policy: "deny" },
      "writer",
    );
    expect(sentenceFor(refused)).toBe("Policy refused writer's http_get call.");
    const forRun = log.add(
      "approval.requested",
      { tool: "write_file", summary: "create the file b.md (1 characters)", automatic: true, precedent: "ap-1", rule: "run" },
      "writer",
    );
    expect(sentenceFor(forRun)).toBe("writer wants to create the file b.md (1 characters): allowed by your yes for this run.");
    const forRunSettled = log.add(
      "approval.resolved",
      { tool: "write_file", status: "approved", automatic: true, precedent: "ap-1" },
      "writer",
    );
    expect(sentenceFor(forRunSettled)).toBe("Your yes for this run allowed writer's write_file call.");
    const unanswered = log.add(
      "approval.requested",
      { tool: "write_file", summary: "create the file c.md (1 characters)", automatic: true, precedent: "ap-2", rule: "unanswered" },
      "writer",
    );
    expect(sentenceFor(unanswered)).toContain("went unanswered earlier in this run");
    const unansweredSettled = log.add(
      "approval.resolved",
      { tool: "write_file", status: "denied", automatic: true, precedent: "ap-2", rule: "unanswered" },
      "writer",
    );
    expect(sentenceFor(unansweredSettled)).toBe(
      "writer's write_file call was refused again: nobody answered it earlier in this run.",
    );
  });

  it("truncates what a model wrote so a row stays a row", () => {
    const log = new LogBuilder();
    const long = log.add("agent.message", { to: "supervisor", text: "x".repeat(500) }, "writer");
    expect(sentenceFor(long).length).toBeLessThan(160);
    expect(sentenceFor(long)).toContain("…");
  });

  it("tells a model that reasoned and said nothing from one that said nothing", () => {
    /* Phase 5 watched a local model return empty content five times running
       with its whole response in a separate thinking field; the log said it
       had produced nothing. Now that `llm.response` carries `thinking`, the
       sentence says which of the two happened. */
    const log = new LogBuilder();
    const silent = log.add(
      "llm.response",
      { text: "", thinking: null, input_tokens: 40, output_tokens: 0, stop_reason: "end_turn", tool_calls: [] },
      "writer",
    );
    const thought = log.add(
      "llm.response",
      {
        text: "",
        thinking: "The user wants a file but I have no tool for it.",
        input_tokens: 40,
        output_tokens: 60,
        stop_reason: "end_turn",
        tool_calls: [],
      },
      "writer",
    );
    const answered = log.add(
      "llm.response",
      { text: "Done.", thinking: "Let me check.", input_tokens: 40, output_tokens: 6, stop_reason: "end_turn", tool_calls: [] },
      "writer",
    );

    expect(sentenceFor(silent)).toMatch(/said nothing/);
    expect(sentenceFor(silent)).not.toMatch(/reason/);
    expect(sentenceFor(thought)).toMatch(/reasoned .* said nothing|reasoned, then said nothing/);
    expect(sentenceFor(answered)).toMatch(/answered writer/);
    expect(sentenceFor(answered)).not.toMatch(/nothing/);
  });

  it("describes a feed read with its public URL", () => {
    const phrase = callPhrase("read_feed", {
      url: "https://news.example.test/rss",
      limit: 10,
    });

    expect(phrase.infinitive).toBe("read feed https://news.example.test/rss");
    expect(phrase.progressive).toBe("reading feed https://news.example.test/rss");
    expect(phrase.past).toBe("read feed https://news.example.test/rss");
  });

  it("describes a deterministic watchlist price read", () => {
    const phrase = callPhrase("read_prices", { symbols: ["AAPL", "2330.TW"] });

    expect(phrase.infinitive).toBe("read prices for AAPL, 2330.TW");
    expect(phrase.progressive).toBe("reading prices for AAPL, 2330.TW");
    expect(phrase.past).toBe("read prices for AAPL, 2330.TW");
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

describe("the approval policy a run acted under", () => {
  const base = {
    levels: ["low", "medium"],
    allowTools: [],
    denyTools: [],
    hosts: ["news.google.com", "stooq.com"],
    questionSeconds: null,
    supervised: false,
    origin: "ui",
  };

  it("names the levels, the sites and the one tool that always asks", () => {
    expect(policySentence(base)).toBe(
      "Low and medium risk ran on its own; fetches from news.google.com and stooq.com only; run_shell always asked.",
    );
  });

  it("says a scheduled run's question expired, and a stepped-through run asked first", () => {
    expect(policySentence({ ...base, questionSeconds: 120, denyTools: ["http_get"] })).toBe(
      "Low and medium risk ran on its own; fetches from news.google.com and stooq.com only; http_get never allowed; run_shell always asked. Nobody was watching, so a question expired after 120 seconds.",
    );
    expect(policySentence({ ...base, supervised: true })).toBe("Stepped through: every call asked first.");
    expect(policySentence({ ...base, levels: [] })).toBe("Every call asked first; run_shell always asked.");
    // A shell the policy refuses was never asked about.
    expect(policySentence({ ...base, denyTools: ["run_shell"] })).not.toContain("always asked");
  });

  it("recognises read_prices as a network call when its tool answer allows it", () => {
    expect(policySentence({ ...base, levels: [], allowTools: ["read_prices"] })).toContain(
      "fetches from news.google.com and stooq.com only",
    );
  });
});
