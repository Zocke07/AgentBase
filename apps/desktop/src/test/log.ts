import type { Event, EventType } from "@agentbase/schemas";

/**
 * Builds event logs for tests, shaped like the sidecar's: `seq` dense and
 * 1-based, timestamps derived from `seq` rather than the clock.
 */
export class LogBuilder {
  private seq = 0;
  private id = 0;

  constructor(readonly runId = "run-1") {}

  add(type: EventType, payload: Record<string, unknown> = {}, agentId: string | null = null): Event {
    this.seq += 1;
    this.id += 1;
    return {
      id: this.id,
      run_id: this.runId,
      seq: this.seq,
      agent_id: agentId,
      type,
      payload,
      // 2026-09-10T12:00:00Z plus one second per event.
      ts: new Date(Date.UTC(2026, 8, 10, 12, 0, this.seq)).toISOString(),
    };
  }
}

/**
 * A complete two-agent run, awkward cases included: a sandbox denial, an
 * automatic approval, a streamed token, and a summary that claims more than
 * the tool calls support.
 */
export function twoAgentRun(): Event[] {
  const log = new LogBuilder();

  return [
    log.add("run.started", {
      goal: "Summarise the quarterly report",
      limits: { max_steps_per_agent: 10, max_agents_per_run: 4, max_run_seconds: 900 },
    }),
    log.add(
      "agent.spawned",
      {
        role: "Plans the work and delegates it",
        system_prompt: "You are the supervisor.",
        allowed_tools: [],
        auto_approve: [],
        max_steps: 10,
        provider: "ollama",
        model: "qwen3:4b",
      },
      "supervisor",
    ),
    log.add("agent.thinking", { step: 1 }, "supervisor"),
    log.add("llm.request", { provider: "ollama", model: "qwen3:4b", step: 1, messages: [] }, "supervisor"),
    log.add("llm.response", { text: "", input_tokens: 400, output_tokens: 40, cost_micros: 1200, stop_reason: "tool_use" }, "supervisor"),
    log.add("tool.requested", { tool: "spawn_agent", args: { agent: "researcher" }, call_id: "c1" }, "supervisor"),
    log.add("tool.called", { tool: "spawn_agent", args: { agent: "researcher" }, call_id: "c1" }, "supervisor"),
    log.add(
      "agent.spawned",
      {
        role: "Gathers source material",
        definition_id: "def-researcher",
        definition_name: "researcher",
        system_prompt: "You find things out.",
        allowed_tools: ["read_file", "write_file"],
        auto_approve: [],
        max_steps: 6,
        provider: "ollama",
        model: "qwen3:4b",
      },
      "researcher",
    ),
    log.add("agent.handoff", { to: "researcher", task: "Find the figures" }, "supervisor"),
    log.add("agent.thinking", { step: 1 }, "researcher"),
    log.add("llm.request", { provider: "ollama", model: "qwen3:4b", step: 1, messages: [] }, "researcher"),
    log.add("llm.token", { text: "Reading " }, "researcher"),
    log.add("llm.token", { text: "the report." }, "researcher"),
    log.add("llm.response", { text: "Reading the report.", input_tokens: 500, output_tokens: 60, cost_micros: 800, stop_reason: "tool_use" }, "researcher"),

    // A call that is refused at the sandbox, with nobody asked.
    log.add("tool.requested", { tool: "read_file", args: { path: "../../secrets" }, call_id: "c2" }, "researcher"),
    log.add(
      "tool.denied",
      {
        tool: "read_file",
        args: { path: "../../secrets" },
        call_id: "c2",
        reason: "That path is outside the workspace.",
        blocked_by: "sandbox",
      },
      "researcher",
    ),

    // A call that is asked about and allowed.
    log.add("agent.thinking", { step: 2 }, "researcher"),
    log.add("tool.requested", { tool: "write_file", args: { path: "notes.txt" }, call_id: "c3" }, "researcher"),
    log.add(
      "approval.requested",
      {
        approval_id: "ap-1",
        tool: "write_file",
        args: { path: "notes.txt" },
        risk: "medium",
        prompt: 'Agent "researcher" wants to create notes.txt (31 characters): Allow / Deny',
        summary: "create the file notes.txt (31 characters)",
      },
      "researcher",
    ),
    log.add("approval.resolved", { approval_id: "ap-1", tool: "write_file", status: "approved", automatic: false }, "researcher"),
    log.add("tool.approved", { tool: "write_file", call_id: "c3", approval_id: "ap-1", automatic: false, summary: "create the file notes.txt" }, "researcher"),
    log.add("tool.called", { tool: "write_file", args: { path: "notes.txt" }, call_id: "c3" }, "researcher"),
    log.add("tool.result", { tool: "write_file", call_id: "c3", result: "Wrote 31 characters to notes.txt." }, "researcher"),

    log.add("agent.message", { to: "supervisor", text: "Revenue up 12% QoQ; churn flat." }, "researcher"),
    log.add("agent.completed", { reason: "finished", steps: 2 }, "researcher"),
    log.add("agent.message", { to: "user", text: "Quarterly report summarised." }, "supervisor"),
    log.add("agent.completed", { reason: "finished", steps: 2 }, "supervisor"),
    log.add("run.completed", { summary: "Quarterly report summarised and saved to notes.txt." }),
  ];
}
