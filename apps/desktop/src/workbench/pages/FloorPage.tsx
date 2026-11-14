import type { AgentDef, ToolResponse } from "@agentbase/schemas";
import { useState } from "react";

import { AgentList } from "../../components/AgentList";

/**
 * The Agents section's floor plan (brief 7.13): made-up agents as desk
 * cards, one the supervisor may not use (its chair pushed in), one with a
 * high-risk tool and one with none, and one selected.
 */

const agent = (name: string, role: string, extra: Partial<AgentDef> = {}): AgentDef => ({
  id: `agent-${name}`,
  space_id: "space-handbook",
  name,
  role,
  system_prompt: "",
  allowed_tools: [],
  enabled: true,
  created_at: "2026-11-10T08:00:00Z",
  updated_at: "2026-11-10T08:00:00Z",
  ...extra,
});

const AGENTS: readonly AgentDef[] = [
  agent("researcher", "Finds sources for a chapter and summarises them.", {
    model: "claude-haiku-5-5",
    allowed_tools: ["read_file", "http_get", "write_file"],
    max_steps: 12,
    is_builtin: true,
  }),
  agent("editor", "Checks a chapter against the style guide and suggests changes.", {
    allowed_tools: ["read_file", "write_file"],
  }),
  agent("builder", "Runs the handbook's build to check that every page renders.", {
    model: "claude-sonnet-5-5",
    allowed_tools: ["run_shell", "read_file"],
  }),
  agent("archivist", "Files finished chapters away. Not needed this month.", { enabled: false }),
];

const TOOLS: readonly ToolResponse[] = [
  { name: "read_file", description: "", risk: "low", available: true },
  { name: "write_file", description: "", risk: "medium", available: true },
  { name: "http_get", description: "", risk: "medium", available: true },
  { name: "run_shell", description: "", risk: "high", available: true },
];

const NOTHING = () => undefined;

export function FloorPage() {
  const [selected, setSelected] = useState<string | null>("agent-editor");
  return (
    <div className="wb-floor">
      <AgentList
        agents={AGENTS}
        loading={false}
        selectedId={selected}
        error={null}
        busyId={null}
        tools={TOOLS}
        onSelect={setSelected}
        onCreate={NOTHING}
        onToggleEnabled={NOTHING}
        onDelete={NOTHING}
      />
    </div>
  );
}
