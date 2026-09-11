import type { AgentDef, CreateAgentRequest, ToolResponse } from "@agentspace/schemas";
import { useCallback, useState } from "react";

import * as api from "../lib/api";
import type { ProviderCatalogue } from "../lib/api";
import { useFetched } from "../state/useFetched";

import { AgentEditor } from "./AgentEditor";
import { AgentList } from "./AgentList";



/**
 * The agent tab: the roster, and the editor beside it.
 *
 * Together with `RunsView` this is the second half of §5 Phase 7's acceptance
 * criterion — "a new agent can be created, edited, and run without leaving the
 * app". Creating and editing happen here; running happens next door, because a
 * definition the supervisor can draw on is one that is simply *enabled*.
 *
 * An `ApiError` thrown by a save is deliberately re-thrown to `AgentEditor`,
 * which is what puts the message on the offending input. Catching it here would
 * be the toast §5 Phase 7 explicitly rules out.
 */

const NO_AGENTS: AgentDef[] = [];
const NO_TOOLS: ToolResponse[] = [];
const NO_CATALOGUE: ProviderCatalogue = { providers: [], models: [] };

export function AgentsView() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<"none" | "new" | "existing">("none");
  const [actionError, setActionError] = useState<string | null>(null);

  const loadAgents = useCallback(() => api.listAgents(), []);
  const loadTools = useCallback(() => api.listTools(), []);
  const loadCatalogue = useCallback(() => api.listProviders(), []);

  const roster = useFetched(loadAgents, NO_AGENTS);
  const tools = useFetched(loadTools, NO_TOOLS);
  const catalogue = useFetched(loadCatalogue, NO_CATALOGUE);

  const agents = roster.data;
  const selected = agents.find((agent) => agent.id === selectedId) ?? null;
  // Every fetch this tab depends on reports here. A failed `/tools` used to
  // render an editor with no checkboxes and no explanation — and a save from
  // that state would have sent an empty allowlist.
  const error = actionError ?? roster.error ?? tools.error ?? catalogue.error;

  const save = async (body: CreateAgentRequest) => {
    // No try/catch: the editor renders the failure inline against the field the
    // server named. See the module note.
    if (editing === "existing" && selected !== null) {
      await api.updateAgent(selected.id, body);
    } else {
      const created = await api.createAgent(body);
      setSelectedId(created.id);
    }
    roster.reload();
    setEditing("none");
  };

  const toggleEnabled = async (agent: AgentDef) => {
    setActionError(null);
    try {
      await api.updateAgent(agent.id, { enabled: !(agent.enabled ?? true) });
      roster.reload();
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  const remove = async (agent: AgentDef) => {
    setActionError(null);
    try {
      await api.deleteAgent(agent.id);
      if (selectedId === agent.id) {
        setSelectedId(null);
        setEditing("none");
      }
      roster.reload();
    } catch (failure) {
      // A built-in refuses deletion with a 409 and a message saying so. Showing
      // it is the point — §5 Phase 5 guards the delete path deliberately.
      setActionError(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <div className="agents-view">
      <AgentList
        agents={agents}
        loading={roster.loading}
        selectedId={selectedId}
        error={error}
        onSelect={(id) => {
          setSelectedId(id);
          setEditing("existing");
        }}
        onCreate={() => {
          setSelectedId(null);
          setEditing("new");
        }}
        onToggleEnabled={(agent) => void toggleEnabled(agent)}
        onDelete={(agent) => void remove(agent)}
      />

      <div className="agents-view__editor">
        {editing === "none" ? (
          <p className="agents-view__placeholder">
            Pick an agent to edit it, or create a new one. An agent that is
            enabled here is one the supervisor can put to work.
          </p>
        ) : (
          <AgentEditor
            // Remount on a different definition so the form state starts from
            // the row being edited rather than the one before it.
            key={editing === "new" ? "new" : (selected?.id ?? "new")}
            agent={editing === "existing" ? selected : null}
            tools={tools.data}
            providers={catalogue.data.providers.map((provider) => provider.name)}
            models={catalogue.data.models}
            onSave={save}
            onCancel={() => {
              setEditing("none");
            }}
          />
        )}
      </div>
    </div>
  );
}
