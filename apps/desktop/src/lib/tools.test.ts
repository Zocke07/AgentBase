import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { CONTROL_TOOLS, FAMILY_LABEL, FETCHING_TOOLS, TOOL_FAMILIES, toolFamily, toolInfo, TOOLS } from "./tools";

/**
 * Two lists that must agree: the tools the sidecar declares, and the table
 * the interface presents them from. The backend's sources are read as text,
 * so a tool added there without an entry here fails this test.
 */
const BACKEND = join(import.meta.dirname, "..", "..", "..", "backend", "src", "agentbase");

function declared(folder: string, pattern: RegExp): string[] {
  return readdirSync(folder)
    .filter((file) => file.endsWith(".py"))
    .flatMap((file) => [...readFileSync(join(folder, file), "utf8").matchAll(pattern)].map((match) => match[1] ?? ""));
}

const BUILT_IN = declared(join(BACKEND, "tools", "builtin"), /^ {4}name = "([a-z_]+)"$/gm);
const CONTROL = declared(join(BACKEND, "orchestrator"), /^ {4}name="(spawn_agent|handoff|finish)",$/gm);

describe("the tool table", () => {
  it("reads the backend's tools at all", () => {
    // A guard on the reader: a pattern that matched nothing would pass below.
    expect(BUILT_IN.length).toBeGreaterThanOrEqual(15);
    expect(BUILT_IN).toContain("read_file");
    expect(BUILT_IN).toContain("run_shell");
    expect([...CONTROL].sort()).toEqual([...CONTROL_TOOLS].sort());
  });

  it("has an entry, with a family, for every built-in tool and control call", () => {
    expect([...BUILT_IN, ...CONTROL].filter((name) => TOOLS[name] === undefined)).toEqual([]);
    for (const name of [...BUILT_IN, ...CONTROL]) expect(toolFamily(name), name).not.toBe("unknown");
  });

  it("names no tool the backend does not have", () => {
    const known = new Set([...BUILT_IN, ...CONTROL]);
    expect(Object.keys(TOOLS).filter((name) => !known.has(name))).toEqual([]);
  });

  it("marks as fetching exactly the tools that name a host for the gate", () => {
    // In the backend a network tool puts its host in the prepared payload.
    const hosts = readdirSync(join(BACKEND, "tools", "builtin"))
      .filter((file) => file.endsWith(".py"))
      .flatMap((file) => {
        const source = readFileSync(join(BACKEND, "tools", "builtin", file), "utf8");
        // One class per `name = "..."`; the text up to the next is its body.
        return source.split(/^class /m).flatMap((body) => {
          const name = /^ {4}name = "([a-z_]+)"$/m.exec(body)?.[1];
          return name !== undefined && body.includes('"host":') ? [name] : [];
        });
      });
    expect([...FETCHING_TOOLS].sort()).toEqual([...new Set(hosts)].sort());
  });

  it("gives an unknown tool its own name and the unknown family", () => {
    expect(toolInfo("mystery_tool")).toMatchObject({ chip: "mystery_tool", family: "unknown", fetches: false, reportsWritten: false });
  });

  it("treats a name a model made up as unknown, even one every object has", () => {
    // A tool name is whatever the model sent.
    for (const name of ["constructor", "toString", "valueOf", "hasOwnProperty", "__proto__"]) {
      expect(toolInfo(name), name).toEqual({ chip: name, family: "unknown", fetches: false, reportsWritten: false });
    }
  });

  it("trusts a result's written list only from deterministic pipeline tools", () => {
    const trusted = Object.keys(TOOLS).filter((name) => TOOLS[name]?.reportsWritten === true);
    expect(trusted.sort()).toEqual(
      ["check_limits", "compute_portfolio", "read_company_reports", "read_market", "read_prices", "score_predictions", "track_forecasts"].sort(),
    );
    // Never a tool that returns read or fetched text.
    for (const name of ["read_file", "http_get", "read_feed", "search_knowledge", "run_shell"]) {
      expect(toolInfo(name).reportsWritten, name).toBe(false);
    }
  });

  it("has words for every family", () => {
    for (const family of TOOL_FAMILIES) expect(FAMILY_LABEL[family]).not.toBe("");
    // Every family but `unknown` has at least one tool.
    const used = new Set(Object.values(TOOLS).map((info) => info.family));
    expect(TOOL_FAMILIES.filter((family) => family !== "unknown" && !used.has(family))).toEqual([]);
  });
});
