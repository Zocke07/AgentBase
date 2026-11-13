import { describe, expect, it } from "vitest";

import { LogBuilder, twoAgentRun } from "../test/log";
import { scenario, SCENARIOS } from "../test/scenarios";

import { motionMode, nextNotable, notableEvents, PLAYBACK_SPEEDS, playbackDelay, previousNotable } from "./timeline";

describe("notable events", () => {
  it("marks handoffs, the files a run wrote and its end, in order", () => {
    const events = twoAgentRun();
    const markers = notableEvents(events);
    expect(markers.map((marker) => marker.cursor)).toEqual([...markers.map((marker) => marker.cursor)].sort((a, b) => a - b));
    expect(markers.some((marker) => marker.kind === "handoff")).toBe(true);
    expect(markers.at(-1)).toMatchObject({ kind: "end", cursor: events.length });
    // Each mark sits where its event has just happened, and says it as the log does.
    for (const marker of markers) {
      expect(events[marker.cursor - 1]?.seq).toBe(marker.seq);
      expect(marker.label).not.toBe("");
    }
  });

  it("marks a question a person had to answer, never a policy's own answer", () => {
    expect(notableEvents(scenario("shell-question").events).filter((marker) => marker.kind === "question")).toHaveLength(1);
    expect(notableEvents(scenario("morning-collection").events).some((marker) => marker.kind === "question")).toBe(false);
  });

  it("marks a refusal, and a failure but not a call about to be retried", () => {
    expect(notableEvents(scenario("sandbox-denial").events).some((marker) => marker.kind === "denial")).toBe(true);
    const failed = notableEvents(scenario("failed-run").events).filter((marker) => marker.kind === "error");
    // One refused model call and the run's failure; the retried call is not a mark.
    expect(failed).toHaveLength(2);
  });

  it("marks a file written by write_file or a deterministic tool, not a read", () => {
    const log = new LogBuilder();
    const markers = notableEvents([
      log.add("tool.result", { tool: "read_file", result: "text" }, "a"),
      log.add("tool.result", { tool: "write_file", result: "ok" }, "a"),
      log.add("tool.result", { tool: "compute_portfolio", result: "{}" }, "a"),
      log.add("tool.result", { tool: "http_get", result: '{"written": ["x"]}' }, "a"),
    ]);
    expect(markers.map((marker) => [marker.cursor, marker.kind])).toEqual([
      [2, "file"],
      [3, "file"],
    ]);
  });

  it("finds something to mark in every scenario that ended", () => {
    for (const entry of SCENARIOS) {
      const ended = entry.events.some((event) => ["run.completed", "run.failed", "run.cancelled"].includes(event.type));
      if (ended) expect(notableEvents(entry.events).length, entry.id).toBeGreaterThan(0);
    }
  });

  it("steps to the next and the previous mark from anywhere", () => {
    const markers = notableEvents(twoAgentRun());
    const first = markers[0]?.cursor ?? 0;
    const second = markers[1]?.cursor ?? 0;
    expect(nextNotable(markers, 0)).toBe(first);
    expect(nextNotable(markers, first)).toBe(second);
    expect(previousNotable(markers, second)).toBe(first);
    expect(previousNotable(markers, first)).toBeNull();
    expect(nextNotable(markers, markers.at(-1)?.cursor ?? 0)).toBeNull();
  });
});

describe("whether a cursor move animates", () => {
  const events = twoAgentRun();

  it("is a step when it moves forward by a few events", () => {
    expect(motionMode(events, 4, 5)).toBe("step");
    expect(motionMode(events, 4, 7)).toBe("step");
  });

  it("settles on a jump, a step back and standing still", () => {
    expect(motionMode(events, 0, events.length)).toBe("settle");
    expect(motionMode(events, 9, 8)).toBe("settle");
    expect(motionMode(events, 5, 5)).toBe("settle");
  });

  it("counts a burst of streamed tokens as one step", () => {
    const log = new LogBuilder();
    const burst = [
      log.add("llm.request", {}, "a"),
      ...Array.from({ length: 40 }, () => log.add("llm.token", { text: "word " }, "a")),
      log.add("llm.response", { text: "" }, "a"),
    ];
    expect(motionMode(burst, 0, burst.length)).toBe("step");
    // Two bursts with three other events between them is more than a step.
    const two = [...burst, log.add("agent.thinking", {}, "a"), log.add("llm.request", {}, "a"), log.add("llm.token", { text: "x" }, "a")];
    expect(motionMode(two, 0, two.length)).toBe("settle");
  });
});

describe("playback", () => {
  it("offers 1x, 2x, 4x and 8x, each resting half as long as the one before", () => {
    expect([...PLAYBACK_SPEEDS]).toEqual([1, 2, 4, 8]);
    const event = twoAgentRun()[0];
    const delays = PLAYBACK_SPEEDS.map((speed) => playbackDelay(event, speed));
    for (let index = 1; index < delays.length; index += 1) expect(delays[index]).toBe(Math.round((delays[index - 1] ?? 0) / 2));
  });

  it("runs streamed tokens quicker than other events", () => {
    const log = new LogBuilder();
    expect(playbackDelay(log.add("llm.token", {}, "a"), 1)).toBeLessThan(playbackDelay(log.add("tool.called", {}, "a"), 1));
    expect(playbackDelay(undefined, 1)).toBeGreaterThan(0);
  });
});
