import type {
  AgentDef,
  CreateAgentRequest,
  ProviderCatalogueResponse,
  SpaceResponse,
  ToolResponse,
  UpdateAgentRequest,
} from "@agentbase/schemas";
import { useEffect, useState } from "react";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { useFetched } from "../state/useFetched";

import { AgentEditor } from "./AgentEditor";
import { AgentList } from "./AgentList";



/**
 * Roster and adjacent editor. Re-throw save `ApiError` to `AgentEditor` for
 * named-input rendering.
 */

const NO_TOOLS: ToolResponse[] = [];
const NO_CATALOGUE: ProviderCatalogueResponse = { providers: [], models: {}, catalog: {} };

export interface AgentsViewProps {
  /** Space run provider, resolving editor `inherit`. */
  workspaceProvider: string | null;
  /** Roster space; new definitions join it. Null before load. */
  spaceId?: string | null;
  /** All spaces for moving/copying definitions. */
  spaces?: readonly SpaceResponse[];
}

export function AgentsView({ workspaceProvider, spaceId = null, spaces = [] }: AgentsViewProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<"none" | "new" | "existing">("none");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Hold destructive navigation until unsaved editor changes are resolved.
  const [dirty, setDirty] = useState(false);
  const [held, setHeld] = useState<(() => void) | null>(null);

  /** Run `action` now or after unsaved-changes confirmation. */
  const guarded = (action: () => void) => {
    if (dirty && editing !== "none") setHeld(() => action);
    else action();
  };

  // Share Home roster store so toggles synchronize.
  const agents = useRoster((state) => state.agents);
  const rosterLoading = useRoster((state) => state.loading);
  const rosterError = useRoster((state) => state.error);
  const reloadRoster = useRoster((state) => state.load);
  const ensureRoster = useRoster((state) => state.ensure);
  const tools = useFetched(api.listTools, NO_TOOLS);
  const catalogue = useFetched(api.listProviders, NO_CATALOGUE);

  useEffect(() => {
    ensureRoster();
  }, [ensureRoster]);

  const selected = agents.find((agent) => agent.id === selectedId) ?? null;
  // Report every dependency fetch; failed `/tools` must not allow unexplained
  // empty-allowlist saves.
  const error = actionError ?? rosterError ?? tools.error ?? catalogue.error;

  // Let editor render server errors on named fields.
  const create = async (body: CreateAgentRequest) => {
    const created = await api.createAgent(spaceId === null ? body : { ...body, space_id: spaceId });
    setSelectedId(created.id);
    void reloadRoster();
    setEditing("none");
  };

  // Move changes roster; copy creates a row. Reload this roster and clear moved
  // definition editing.
  const [transferError, setTransferError] = useState<string | null>(null);
  const transfer = async (agent: AgentDef, toSpaceId: string, copy: boolean) => {
    setTransferError(null);
    setBusyId(agent.id);
    try {
      if (copy) await api.copyAgent(agent.id, toSpaceId);
      else await api.updateAgent(agent.id, { space_id: toSpaceId });
      if (!copy && selectedId === agent.id) {
        setSelectedId(null);
        setEditing("none");
      }
      void reloadRoster();
    } catch (failure) {
      setTransferError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusyId(null);
    }
  };
  const otherSpaces = spaces.filter((space) => space.id !== spaceId && space.archived !== true);

  const patch = async (changes: UpdateAgentRequest) => {
    if (selected === null) return;
    await api.updateAgent(selected.id, changes);
    void reloadRoster();
    setEditing("none");
  };

  const toggleEnabled = async (agent: AgentDef) => {
    setActionError(null);
    setBusyId(agent.id);
    try {
      await api.updateAgent(agent.id, { enabled: !(agent.enabled ?? true) });
      void reloadRoster();
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (agent: AgentDef) => {
    setActionError(null);
    setBusyId(agent.id);
    try {
      await api.deleteAgent(agent.id);
      if (selectedId === agent.id) {
        setSelectedId(null);
        setEditing("none");
      }
      void reloadRoster();
    } catch (failure) {
      // Display deliberate §5 Phase 5 built-in deletion 409 refusal.
      setActionError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="agents-view">
      <AgentList
        agents={agents}
        loading={rosterLoading}
        selectedId={selectedId}
        error={error}
        busyId={busyId}
        onSelect={(id) => {
          guarded(() => {
            setSelectedId(id);
            setEditing("existing");
          });
        }}
        onCreate={() => {
          guarded(() => {
            setSelectedId(null);
            setEditing("new");
          });
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
          <>
            {held !== null && (
              <div className="editor__unsaved" role="alert" data-testid="unsaved">
                <span>This agent has unsaved changes.</span>
                <button
                  type="button"
                  className="button button--small button--danger"
                  onClick={() => {
                    const action = held;
                    setHeld(null);
                    setDirty(false);
                    action();
                  }}
                >
                  Discard
                </button>
                <button
                  type="button"
                  className="button button--small"
                  onClick={() => {
                    setHeld(null);
                  }}
                >
                  Keep editing
                </button>
              </div>
            )}
          {editing === "existing" && selected !== null && otherSpaces.length > 0 && (
            <div className="transfer" data-testid="transfer">
              <span className="transfer__label">This agent lives in this space.</span>
              <label>
                Move to
                <select
                  value=""
                  disabled={busyId === selected.id}
                  onChange={(changed) => {
                    if (changed.target.value !== "") void transfer(selected, changed.target.value, false);
                  }}
                  aria-label="Move to space"
                  data-testid="move-to"
                >
                  <option value="">…</option>
                  {otherSpaces.map((space) => (
                    <option key={space.id} value={space.id}>
                      {space.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Copy to
                <select
                  value=""
                  disabled={busyId === selected.id}
                  onChange={(changed) => {
                    if (changed.target.value !== "") void transfer(selected, changed.target.value, true);
                  }}
                  aria-label="Copy to space"
                  data-testid="copy-to"
                >
                  <option value="">…</option>
                  {otherSpaces.map((space) => (
                    <option key={space.id} value={space.id}>
                      {space.name}
                    </option>
                  ))}
                </select>
              </label>
              {transferError !== null && (
                <span className="field-error" role="alert">
                  {transferError}
                </span>
              )}
            </div>
          )}
          <AgentEditor
            // Remount for each definition to reset form from its row.
            key={editing === "new" ? "new" : (selected?.id ?? "new")}
            agent={editing === "existing" ? selected : null}
            tools={tools.data}
            catalogue={catalogue.data}
            workspaceProvider={workspaceProvider}
            onCreate={create}
            onPatch={patch}
            onDirtyChange={setDirty}
            onCancel={() => {
              guarded(() => {
                setEditing("none");
              });
            }}
          />
          </>
        )}
      </div>
    </div>
  );
}
