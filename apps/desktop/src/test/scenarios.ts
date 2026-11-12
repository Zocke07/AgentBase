import type { Event, EventType } from "@agentbase/schemas";

import { LogBuilder, twoAgentRun } from "./log";

/**
 * Scenario logs: one run per shape the interface has to draw. They feed the
 * workbench, the replay identity test and the screenshot tests, so a state
 * that matters is drawn from the same events everywhere.
 *
 * Every scenario is written here from made-up content, with `LogBuilder`'s
 * fixed timestamps. None is copied from a real run: the default space's logs
 * hold a person's portfolio. Where a real run's shape matters (which events a
 * policy answer emits, what a refused call looks like), the scenario mirrors
 * the orchestrator's event order and payload keys.
 */

export interface Scenario {
  /** Stable, used in URLs and screenshot names. */
  readonly id: string;
  readonly title: string;
  /** What this run shows that the others do not. */
  readonly about: string;
  readonly events: readonly Event[];
}

type Payload = Record<string, unknown>;

const SUPERVISOR = "supervisor";
const SONNET = "claude-sonnet-5-5";
const HAIKU = "claude-haiku-5-5";

interface Worker {
  readonly name: string;
  readonly role: string;
  readonly tools: readonly string[];
  readonly model?: string;
}

interface StartOptions {
  /** Who started it: `ui`, `schedule`, `automation`, `monitor`, `discord`. */
  readonly origin?: string;
  /** Risk levels the policy answers; empty asks for everything. */
  readonly levels?: readonly string[];
  readonly hosts?: readonly string[];
  readonly supervised?: boolean;
  readonly knowledge?: readonly Payload[];
  readonly maxAgents?: number;
}

/** An agent, by name or by its roster entry. */
type Agent = string | Worker;

const nameOf = (agent: Agent): string => (typeof agent === "string" ? agent : agent.name);

/** How a call got past the gate: by the policy's word, or without a question. */
interface Gate {
  readonly risk: "low" | "medium" | "high";
  /** The backend's phrase for the action: "read the feed at example.com". */
  readonly summary: string;
  readonly host?: string;
}

/**
 * One run's events in the order the orchestrator emits them. Each method is
 * one thing an agent does; the payload keys match `events/types.py`.
 */
class Script {
  readonly events: Event[] = [];
  private readonly log: LogBuilder;
  private calls = 0;
  private approvals = 0;
  private readonly steps = new Map<string, number>();
  private readonly models = new Map<string, string>();

  constructor(runId: string) {
    this.log = new LogBuilder(runId);
  }

  emit(type: EventType, payload: Payload = {}, agent: Agent | null = null): this {
    this.events.push(this.log.add(type, payload, agent === null ? null : nameOf(agent)));
    return this;
  }

  start(goal: string, options: StartOptions = {}): this {
    return this.emit("run.started", {
      goal,
      limits: {
        max_steps_per_agent: 20,
        max_agents_per_run: options.maxAgents ?? 5,
        max_run_seconds: 900,
        max_run_cost_micros: 2_000_000,
      },
      space: { id: "space-main", name: "Main" },
      approval: {
        levels: options.levels ?? ["low", "medium"],
        tool_policies: {},
        hosts: options.hosts ?? [],
        question_seconds: options.origin === "schedule" ? 120 : null,
        supervised: options.supervised ?? false,
        origin: options.origin ?? "ui",
      },
      ...(options.knowledge === undefined ? {} : { knowledge: options.knowledge }),
    });
  }

  /** The supervisor takes its desk. */
  lead(model = SONNET): this {
    this.models.set(SUPERVISOR, model);
    return this.emit(
      "agent.spawned",
      {
        role: "Plans the work and delegates it",
        definition_id: null,
        definition_name: null,
        system_prompt: "You are the supervisor. Plan the work and delegate it.",
        allowed_tools: [],
        auto_approve: [],
        max_steps: 20,
        provider: "anthropic",
        model,
      },
      SUPERVISOR,
    );
  }

  /** The start of a model call, left open: the agent is waiting on its model. */
  ask(who: Agent): this {
    const agent = nameOf(who);
    const step = (this.steps.get(agent) ?? 0) + 1;
    this.steps.set(agent, step);
    return this.emit("agent.thinking", { step }, agent).emit(
      "llm.request",
      { provider: "anthropic", model: this.models.get(agent) ?? SONNET, step, attempt: 1, messages: [] },
      agent,
    );
  }

  /** Text arriving from the model, a few words at a time. */
  stream(who: Agent, said: string): this {
    const agent = nameOf(who);
    const words = said.split(" ");
    for (let index = 0; index < words.length; index += 3) {
      const piece = words.slice(index, index + 3).join(" ");
      this.emit("llm.token", { text: index === 0 ? piece : ` ${piece}` }, agent);
    }
    return this;
  }

  /** The model's answer, with the call's usage. */
  answer(who: Agent, said = "", stop: "tool_use" | "end_turn" = "tool_use"): this {
    const agent = nameOf(who);
    const step = this.steps.get(agent) ?? 1;
    const fast = this.models.get(agent) === HAIKU;
    const input = 1_200 + 650 * step;
    const output = 60 + Math.ceil(said.length / 4);
    return this.emit(
      "llm.response",
      {
        text: said,
        input_tokens: input,
        output_tokens: output,
        cost_micros: fast ? input + output * 5 : input * 2 + output * 10,
        stop_reason: stop,
        thinking: null,
        tool_calls: [],
      },
      agent,
    );
  }

  /** One whole model call: asked, streamed when it said anything, answered. */
  think(agent: Agent, said = "", stop: "tool_use" | "end_turn" = "tool_use"): this {
    this.ask(agent);
    if (said !== "") this.stream(agent, said);
    return this.answer(agent, said, stop);
  }

  /** The supervisor puts a roster agent to work. Returns the call to close. */
  delegate(worker: Worker, task: string): string {
    const { name } = worker;
    const model = worker.model ?? SONNET;
    const callId = this.request(SUPERVISOR, "spawn_agent", { agent: name, task });
    this.emit("tool.called", { tool: "spawn_agent", args: { agent: name, task }, call_id: callId }, SUPERVISOR);
    this.models.set(name, model);
    this.emit(
      "agent.spawned",
      {
        role: worker.role,
        definition_id: `def-${name}`,
        definition_name: name,
        system_prompt: `You are ${name}. ${worker.role}.`,
        allowed_tools: [...worker.tools],
        auto_approve: ["low", "medium"],
        max_steps: 12,
        provider: "anthropic",
        model,
      },
      name,
    );
    this.emit("agent.handoff", { to: name, task }, SUPERVISOR);
    return callId;
  }

  /** A worker reports back and its desk goes quiet; the delegation closes. */
  report(who: Agent, callId: string, said: string, reason = "finished"): this {
    const worker = nameOf(who);
    return this.emit("agent.message", { to: SUPERVISOR, text: said }, worker)
      .emit("agent.completed", { reason, steps: this.steps.get(worker) ?? 0 }, worker)
      .emit("tool.result", { tool: "spawn_agent", call_id: callId, result: said, agent: worker }, SUPERVISOR);
  }

  request(agent: Agent, tool: string, args: Payload): string {
    this.calls += 1;
    const callId = `call-${String(this.calls)}`;
    this.emit("tool.requested", { tool, args, call_id: callId }, agent);
    return callId;
  }

  private question(who: Agent, tool: string, args: Payload, gate: Gate, extra: Payload): string {
    const agent = nameOf(who);
    this.approvals += 1;
    const approvalId = `ap-${String(this.approvals)}`;
    this.emit(
      "approval.requested",
      {
        approval_id: approvalId,
        tool,
        args,
        risk: gate.risk,
        prompt: `Agent "${agent}" wants to ${gate.summary}: Allow / Deny`,
        summary: gate.summary,
        ...extra,
      },
      agent,
    );
    return approvalId;
  }

  /** The gate answers by policy: no person is asked, and the log says why. */
  byPolicy(agent: Agent, tool: string, args: Payload, callId: string, gate: Gate): this {
    const approvalId = this.question(agent, tool, args, gate, {
      automatic: true,
      rule: "level",
      ...(gate.host === undefined ? {} : { host: gate.host, hosts: [gate.host] }),
    });
    return this.emit("approval.resolved", { approval_id: approvalId, tool, status: "approved", automatic: true }, agent).emit(
      "tool.approved",
      { tool, call_id: callId, approval_id: approvalId, automatic: true, summary: gate.summary },
      agent,
    );
  }

  /** The gate asks a person. Returns the question, still open. */
  askPerson(agent: Agent, tool: string, args: Payload, gate: Gate): string {
    return this.question(agent, tool, args, gate, {});
  }

  /** A whole call the policy allowed: requested, answered, run, returned. */
  call(agent: Agent, tool: string, args: Payload, result: string, gate: Gate): this {
    const callId = this.request(agent, tool, args);
    this.byPolicy(agent, tool, args, callId, gate);
    return this.emit("tool.called", { tool, args, call_id: callId }, agent).emit(
      "tool.result",
      { tool, call_id: callId, result },
      agent,
    );
  }

  /** A call the policy allowed that ran and failed. */
  failedCall(agent: Agent, tool: string, args: Payload, error: string, gate: Gate): this {
    const callId = this.request(agent, tool, args);
    this.byPolicy(agent, tool, args, callId, gate);
    return this.emit("tool.called", { tool, args, call_id: callId }, agent).emit(
      "tool.error",
      { tool, call_id: callId, error },
      agent,
    );
  }

  /** The supervisor's last words and the run's end. */
  finish(summary: string, memoryPath?: string): this {
    return this.emit("agent.message", { to: "user", text: summary }, SUPERVISOR)
      .emit("agent.completed", { reason: "finished", steps: this.steps.get(SUPERVISOR) ?? 0 }, SUPERVISOR)
      .emit("run.completed", { summary, ...(memoryPath === undefined ? {} : { memory_path: memoryPath }) });
  }
}

const READ: Gate = { risk: "low", summary: "read a file in this space" };
const WRITE: Gate = { risk: "medium", summary: "write a file in this space" };

const NEWS: Worker = {
  name: "news-scanner",
  role: "Collects the day's headlines into a fixed schema",
  tools: ["read_feed", "read_market", "write_file"],
  model: HAIKU,
};
const MOVERS: Worker = {
  name: "market-movers",
  role: "Fetches prices and ranks the day's movers",
  tools: ["read_prices", "read_file"],
  model: HAIKU,
};
const CALENDAR: Worker = {
  name: "event-calendar",
  role: "Lists upcoming releases and auctions",
  tools: ["http_get", "write_file"],
  model: HAIKU,
};
const PORTFOLIO: Worker = {
  name: "portfolio-review",
  role: "Values the holdings from saved prices",
  tools: ["compute_portfolio", "read_file", "write_file"],
  model: HAIKU,
};
const RESEARCHER: Worker = {
  name: "researcher",
  role: "Gathers source material",
  tools: ["read_file", "list_dir", "search_knowledge", "http_get", "write_file", "run_shell"],
};
const WRITER: Worker = {
  name: "writer",
  role: "Drafts the report",
  tools: ["read_file", "write_file", "propose_memory"],
};

// --- the scenarios ----------------------------------------------------------

/**
 * A scheduled morning collection: four collectors in turn, every call
 * answered by policy, network calls naming the listed host they reached.
 */
function morningCollection(): Event[] {
  const run = new Script("run-morning");
  run
    .start("Collect the session's news, prices, calendar and portfolio value.", {
      origin: "schedule",
      hosts: ["news.google.com", "query1.finance.yahoo.com", "api.fiscaldata.treasury.gov", "feeds.finance.yahoo.com"],
      knowledge: [
        {
          citation: "[[notes/Collection checklist#Order]]",
          path: "notes/Collection checklist.md",
          heading: "Order",
          score: 12,
          matched_terms: ["collect", "session"],
          reasons: ["title", "terms"],
          estimated_tokens: 180,
        },
        {
          citation: "[[notes/Sources#Feeds]]",
          path: "notes/Sources.md",
          heading: "Feeds",
          score: 9,
          matched_terms: ["news"],
          reasons: ["terms"],
          estimated_tokens: 140,
        },
      ],
    })
    .lead()
    .think(SUPERVISOR, "Four collections, one after another, starting with the news.");

  const news = run.delegate(NEWS, "Collect today's headlines for the watchlist into raw/news-2026-09-10.jsonl.");
  run
    .think(NEWS, "Reading the two feeds first.")
    .call(NEWS, "read_feed", { url: "https://news.google.com/rss/search?q=EXAMPLE" }, '{"entries": 18, "feed": "Example search"}', {
      risk: "medium",
      summary: "read the feed at news.google.com",
      host: "news.google.com",
    })
    .call(NEWS, "read_market", {}, '{"gainers": 5, "losers": 5, "written": ["raw/market/screeners-2026-09-10.json"]}', {
      risk: "medium",
      summary: "read market-wide movers and headlines",
      host: "feeds.finance.yahoo.com",
    })
    .think(NEWS)
    .call(NEWS, "write_file", { path: "raw/news-2026-09-10.jsonl" }, "Wrote 6,412 characters to raw/news-2026-09-10.jsonl.", WRITE)
    .think(NEWS, "Saved 18 headlines.", "end_turn")
    .report(NEWS, news, "Saved 18 headlines to raw/news-2026-09-10.jsonl.");

  run.think(SUPERVISOR);
  const movers = run.delegate(MOVERS, "Fetch prices for the watchlist and rank the session's movers.");
  run
    .think(MOVERS)
    .call(
      MOVERS,
      "read_prices",
      {},
      '{"session": "2026-09-09", "new_session": true, "symbols": 6, "written": ["raw/prices/summary.csv", "raw/movers-2026-09-09.json"]}',
      { risk: "medium", summary: "fetch daily prices for 6 symbols", host: "query1.finance.yahoo.com" },
    )
    .think(MOVERS, "Six symbols priced; the session is new.", "end_turn")
    .report(MOVERS, movers, "Priced 6 symbols for the 2026-09-09 session.");

  run.think(SUPERVISOR);
  const calendar = run.delegate(CALENDAR, "List the coming week's Treasury auctions.");
  run
    .think(CALENDAR)
    .call(
      CALENDAR,
      "http_get",
      { url: "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/upcoming_auctions" },
      '{"data": [{"security_type": "Bill", "security_term": "4-Week", "auction_date": "2026-09-15"}]}',
      { risk: "medium", summary: "fetch a page from api.fiscaldata.treasury.gov", host: "api.fiscaldata.treasury.gov" },
    )
    .think(CALENDAR)
    .call(CALENDAR, "write_file", { path: "raw/calendar-2026-09-10.json" }, "Wrote 512 characters to raw/calendar-2026-09-10.json.", WRITE)
    .think(CALENDAR, "One auction next week.", "end_turn")
    .report(CALENDAR, calendar, "One auction listed in raw/calendar-2026-09-10.json.");

  run.think(SUPERVISOR);
  const portfolio = run.delegate(PORTFOLIO, "Value the holdings for the session and write the review.");
  run
    .think(PORTFOLIO)
    .call(
      PORTFOLIO,
      "compute_portfolio",
      {},
      '{"as_of": "2026-09-09", "total_value": "5000.00", "written": ["portfolio/computed.json", "portfolio/weights.csv"]}',
      { risk: "medium", summary: "value the holdings from saved prices" },
    )
    .think(PORTFOLIO)
    .call(PORTFOLIO, "write_file", { path: "portfolio/review-2026-09-09.md" }, "Wrote 1,204 characters to portfolio/review-2026-09-09.md.", WRITE)
    .think(PORTFOLIO, "The review is written.", "end_turn")
    .report(PORTFOLIO, portfolio, "Valued the book and wrote portfolio/review-2026-09-09.md.");

  run
    .think(SUPERVISOR, "All four collections are saved.", "end_turn")
    .finish("Collected news, prices, the calendar and the portfolio value for the 2026-09-09 session.", "memory/runs/run-morning.md");
  return run.events;
}

/** A stepped-through run that stops on a `run_shell` question nobody has answered. */
function shellQuestion(): Event[] {
  const run = new Script("run-shell-question");
  run.start("Count the lines in every note.", { supervised: true, levels: [] }).lead().think(SUPERVISOR);
  run.delegate(RESEARCHER, "Count the lines of each Markdown file.");
  run.think(RESEARCHER, "A shell one-liner will count them.");
  const args = { command: "wc -l *.md" };
  run.request(RESEARCHER, "run_shell", args);
  run.askPerson(RESEARCHER, "run_shell", args, { risk: "high", summary: "run the command `wc -l *.md`" });
  return run.events;
}

/** A read outside the space's folder: refused by the sandbox, with nobody asked. */
function sandboxDenial(): Event[] {
  const run = new Script("run-sandbox");
  run.start("Summarise the notes in this space.").lead().think(SUPERVISOR);
  const research = run.delegate(RESEARCHER, "Read the notes and list their subjects.");
  run.think(RESEARCHER);
  const args = { path: "../../other-space/notes.md" };
  const refused = run.request(RESEARCHER, "read_file", args);
  run
    .emit(
      "tool.denied",
      { tool: "read_file", args, call_id: refused, reason: "That path is outside this space's folder.", blocked_by: "sandbox" },
      RESEARCHER,
    )
    .think(RESEARCHER)
    .call(RESEARCHER, "list_dir", { path: "." }, "notes/Field guide.md\nnotes/Reading list.md", READ)
    .think(RESEARCHER, "Two notes, on field work and reading.", "end_turn")
    .report(RESEARCHER, research, "Two notes: a field guide and a reading list.")
    .think(SUPERVISOR, "", "end_turn")
    .finish("The space holds two notes: a field guide and a reading list.");
  return run.events;
}

/** A lookup that found nothing: listed, but not a failure, and the work went on. */
function missedLookup(): Event[] {
  const run = new Script("run-missed-lookup");
  run.start("Write up last week's findings.").lead().think(SUPERVISOR);
  const research = run.delegate(RESEARCHER, "Find last week's findings in the notes.");
  run
    .think(RESEARCHER)
    .failedCall(
      RESEARCHER,
      "read_file",
      { path: "notes/findings.md" },
      "There is no file at notes/findings.md. The folder notes/ holds: Field guide.md, Reading list.md.",
      READ,
    )
    .think(RESEARCHER)
    .call(RESEARCHER, "read_file", { path: "notes/Field guide.md" }, "# Field guide\n\nThree findings from the week.", READ)
    .think(RESEARCHER, "The findings are in the field guide.", "end_turn")
    .report(RESEARCHER, research, "Three findings, from notes/Field guide.md.")
    .think(SUPERVISOR, "", "end_turn")
    .finish("Last week's three findings are written up from the field guide.");
  return run.events;
}

/**
 * A worker that fails the same way three times and is stopped. The run does
 * not fail for it: the supervisor hears why, finishes, and says what it
 * could not do (`orchestrator/__init__.py`, `_finish`).
 */
function stuckWorker(): Event[] {
  const run = new Script("run-stuck");
  run.start("Fetch the release notes and summarise them.", { hosts: ["example.com"] }).lead().think(SUPERVISOR);
  const research = run.delegate(RESEARCHER, "Fetch the release notes page.");
  const error = "The server answered 503 Service Unavailable.";
  for (let attempt = 0; attempt < 3; attempt += 1) {
    run.think(RESEARCHER).failedCall(RESEARCHER, "http_get", { url: "https://example.com/releases" }, error, {
      risk: "medium",
      summary: "fetch a page from example.com",
      host: "example.com",
    });
  }
  const stopped =
    "researcher stopped: http_get failed the same way 3 times in a row (The server answered 503 Service Unavailable.). It needs a different approach, not another try.";
  run
    .emit("agent.completed", { reason: "stuck", steps: 3, error }, RESEARCHER)
    .emit("tool.result", { tool: "spawn_agent", call_id: research, result: stopped, agent: RESEARCHER.name }, SUPERVISOR)
    .think(SUPERVISOR, "The page cannot be reached, so there is nothing to summarise.", "end_turn")
    .finish("The release notes could not be fetched: the server answered 503 three times, so nothing was summarised.");
  return run.events;
}

/** The monthly budget passes 80% during the run; the run still completes. */
function budgetWarning(): Event[] {
  const run = new Script("run-budget");
  run.start("Draft the monthly report.").lead().think(SUPERVISOR);
  const draft = run.delegate(WRITER, "Draft the report from the notes.");
  run
    .think(WRITER)
    .call(WRITER, "read_file", { path: "notes/Field guide.md" }, "# Field guide\n\nThree findings from the week.", READ)
    .think(WRITER, "Drafting the report now.")
    .emit("budget.warning", {
      spent_micros: 16_400_000,
      cap_micros: 20_000_000,
      percent: 82,
      reason: "Used $16.40 of the $20.00 monthly budget.",
    })
    .call(WRITER, "write_file", { path: "reports/monthly.md" }, "Wrote 2,310 characters to reports/monthly.md.", WRITE)
    .think(WRITER, "The draft is saved.", "end_turn")
    .report(WRITER, draft, "Drafted reports/monthly.md.")
    .think(SUPERVISOR, "", "end_turn")
    .finish("The monthly report is drafted in reports/monthly.md.");
  return run.events;
}

/** The monthly budget is spent: the next model call is refused and the run fails. */
function overBudget(): Event[] {
  const run = new Script("run-over-budget");
  const reason = "The monthly budget of $20.00 is spent ($20.02). Raise it in Settings to run more this month.";
  run.start("Summarise the week's notes.").lead().think(SUPERVISOR);
  run.delegate(WRITER, "Summarise the notes.");
  run
    .think(WRITER)
    .emit("budget.exceeded", { reason, cap_micros: 20_000_000, spent_micros: 20_020_000 })
    .emit("run.failed", { reason });
  return run.events;
}

/** The model is retried once, then refuses: the run fails with the reason. */
function failedRun(): Event[] {
  const run = new Script("run-failed");
  run.start("Review the week's decisions.", { origin: "schedule" }).lead();
  run
    .ask(SUPERVISOR)
    .emit(
      "llm.error",
      { error: "The model is at capacity. Trying again in 60 seconds.", will_retry: true, retry_after_seconds: 60, attempt: 1 },
      SUPERVISOR,
    )
    .emit("llm.request", { provider: "anthropic", model: SONNET, step: 1, attempt: 2, messages: [] }, SUPERVISOR)
    .emit(
      "llm.error",
      { error: "The provider refused the key: authentication failed.", will_retry: false, retry_after_seconds: null, attempt: 2 },
      SUPERVISOR,
    )
    .emit("run.failed", { reason: "The provider refused the key: authentication failed." });
  return run.events;
}

/** A person stops the run while a worker is mid-call. */
function cancelledRun(): Event[] {
  const run = new Script("run-cancelled");
  run.start("Read every note and build an index.").lead().think(SUPERVISOR);
  run.delegate(RESEARCHER, "List every note.");
  run.think(RESEARCHER).call(RESEARCHER, "list_dir", { path: "." }, "notes/Field guide.md\nnotes/Reading list.md", READ);
  run.ask(RESEARCHER).stream(RESEARCHER, "Reading the first note");
  run.emit("run.cancelled", { reason: "Stopped from the window." });
  return run.events;
}

/** A run asked for in Discord: the origin, and the reply's first delivery. */
function discordOrigin(): Event[] {
  const run = new Script("run-discord");
  run
    .emit("channel.inbound", {
      channel: "discord",
      external_user_id: "100200300",
      text: "List the open questions.",
      thread_ref: "channel-1/message-9",
      ts: "2026-09-10T12:00:00+00:00",
      trigger: "slash_command",
      display_name: "Sam",
      identity: "sam",
    })
    .start("List the open questions.", { origin: "discord" })
    .lead()
    // The chat reply is recorded once, when its first version is delivered.
    .emit("channel.outbound", { channel: "discord", thread_ref: "channel-1/message-9", kind: "report", ts: "2026-09-10T12:00:03+00:00" })
    .think(SUPERVISOR);
  const research = run.delegate(RESEARCHER, "Find the open questions in the notes.");
  run
    .think(RESEARCHER)
    .call(
      RESEARCHER,
      "search_knowledge",
      { query: "open questions", limit: 5 },
      "[[notes/Field guide#Open questions]] Two questions remain.",
      { risk: "low", summary: "search this space's notes" },
    )
    .think(RESEARCHER, "Two open questions.", "end_turn")
    .report(RESEARCHER, research, "Two open questions, both in the field guide.")
    .think(SUPERVISOR, "", "end_turn")
    .finish("Two questions are open, both in the field guide.");
  return run.events;
}

/** A handoff to an agent that never took a desk, as an older log can hold. */
function ghostHandoff(): Event[] {
  const run = new Script("run-ghost");
  run.start("Check the draft and publish it.").lead().think(SUPERVISOR);
  const draft = run.delegate(WRITER, "Tidy the draft.");
  run
    .think(WRITER, "The draft reads cleanly.", "end_turn")
    .report(WRITER, draft, "The draft is tidy.")
    .think(SUPERVISOR)
    .emit("agent.handoff", { to: "publisher", task: "Publish the draft." }, SUPERVISOR)
    .think(SUPERVISOR, "Nobody on the roster publishes.", "end_turn")
    .finish("The draft is tidy. There is no publisher on this roster, so it was not published.");
  return run.events;
}

/** A crowded room: `desks` agents in all, most finished, one still working. */
function crowd(desks: number): Event[] {
  const run = new Script(`run-${String(desks)}-desks`);
  run.start("Review every chapter of the handbook.", { maxAgents: desks }).lead().think(SUPERVISOR);
  const workers = desks - 1;
  for (let index = 1; index <= workers; index += 1) {
    const worker: Worker = {
      name: `reviewer-${String(index).padStart(2, "0")}`,
      role: `Reviews chapter ${String(index)}`,
      tools: ["read_file", "write_file"],
      model: index % 3 === 0 ? SONNET : HAIKU,
    };
    const callId = run.delegate(worker, `Review chapter ${String(index)} and note what to fix.`);
    run.think(worker).call(worker, "read_file", { path: `handbook/chapter-${String(index)}.md` }, `# Chapter ${String(index)}`, READ);
    if (index === workers) {
      // The last desk is still at work when the log ends.
      run.ask(worker).stream(worker, "Two sections need a clearer example");
      break;
    }
    run
      .think(worker, "One fix noted.", "end_turn")
      .report(worker, callId, `Chapter ${String(index)}: one fix noted.`)
      .think(SUPERVISOR);
  }
  return run.events;
}

/** Every scenario, in the order the workbench lists them. */
export const SCENARIOS: readonly Scenario[] = [
  {
    id: "two-agents",
    title: "Two agents",
    about: "A supervisor and one worker, with a sandbox refusal and a question a person allowed.",
    events: twoAgentRun(),
  },
  {
    id: "morning-collection",
    title: "Morning collection",
    about: "A scheduled chain stage: four collectors, every call answered by policy, network calls naming their host.",
    events: morningCollection(),
  },
  {
    id: "shell-question",
    title: "A question waiting",
    about: "A stepped-through run stopped on a high-risk shell command nobody has answered.",
    events: shellQuestion(),
  },
  {
    id: "sandbox-denial",
    title: "Sandbox refusal",
    about: "A read outside the space's folder, refused before anyone was asked.",
    events: sandboxDenial(),
  },
  {
    id: "missed-lookup",
    title: "Missed lookup",
    about: "A read that found no file: listed, not a failure, and the work went on.",
    events: missedLookup(),
  },
  {
    id: "stuck-worker",
    title: "Stuck worker",
    about: "A worker stopped after failing the same way three times; the supervisor finished without it.",
    events: stuckWorker(),
  },
  {
    id: "budget-warning",
    title: "Budget warning",
    about: "The monthly budget passes 80% while the run is going.",
    events: budgetWarning(),
  },
  {
    id: "over-budget",
    title: "Over budget",
    about: "The monthly budget is spent mid-run, and the run fails before another model call.",
    events: overBudget(),
  },
  {
    id: "failed-run",
    title: "Failed run",
    about: "A model call retried once, then refused: the run failed with the reason.",
    events: failedRun(),
  },
  {
    id: "cancelled-run",
    title: "Cancelled run",
    about: "A person stopped the run while a worker was mid-call.",
    events: cancelledRun(),
  },
  {
    id: "discord-origin",
    title: "Started from Discord",
    about: "A run asked for in a chat channel, with the reply sent back.",
    events: discordOrigin(),
  },
  {
    id: "ghost-handoff",
    title: "Ghost handoff",
    about: "A handoff to an agent that never joined the run.",
    events: ghostHandoff(),
  },
  {
    id: "twelve-desks",
    title: "Twelve desks",
    about: "A supervisor and eleven workers, the last still working.",
    events: crowd(12),
  },
  {
    id: "twenty-desks",
    title: "Twenty desks",
    about: "A supervisor and nineteen workers, the last still working.",
    events: crowd(20),
  },
];

export function scenario(id: string): Scenario {
  const found = SCENARIOS.find((candidate) => candidate.id === id);
  if (found === undefined) throw new Error(`There is no scenario called ${id}.`);
  return found;
}
