import type {
  AgentDef,
  CreateAgentRequest,
  ProviderCatalogueResponse,
  SpaceResponse,
  ToolResponse,
  UpdateAgentRequest,
} from "@agentbase/schemas";
import { useCallback, useEffect, useState } from "react";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { useFetched } from "../state/useFetched";

import { AgentEditor } from "./AgentEditor";
import { AgentList } from "./AgentList";



/**
 * The agents section: the roster, and the editor beside it. An `ApiError`
 * from a save is re-thrown to `AgentEditor`, which puts it on the offending input.
 */

const NO_TOOLS: ToolResponse[] = [];
const NO_CATALOGUE: ProviderCatalogueResponse = { providers: [], models: {} };

export interface AgentsViewProps {
  /** The provider a run in this space uses, so the editor knows what "inherit" means. */
  workspaceProvider: string | null;
  /** The space whose roster this is; a new definition joins it. Null before the list loads. */
  spaceId?: string | null;
  /** Every space, for moving or copying a definition to another. */
  spaces?: readonly SpaceResponse[];
}

export function AgentsView({ workspaceProvider, spaceId = null, spaces = [] }: AgentsViewProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<"none" | "new" | "existing">("none");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // The editor says when its form differs from what it opened with; a click
  // that would throw that away is held until the user says which they meant.
  const [dirty, setDirty] = useState(false);
  const [held, setHeld] = useState<(() => void) | null>(null);

  /** Run `action` now, or hold it behind the unsaved-changes question. */
  const guarded = (action: () => void) => {
    if (dirty && editing !== "none") setHeld(() => action);
    else action();
  };

  const loadTools = useCallback(() => api.listTools(), []);
  const loadCatalogue = useCallback(() => api.listProviders(), []);

  // The roster is shared with the Home screen, which has its own toggle for
  // each agent; one store, so a change on either side shows on both.
  const agents = useRoster((state) => state.agents);
  const rosterLoading = useRoster((state) => state.loading);
  const rosterError = useRoster((state) => state.error);
  const reloadRoster = useRoster((state) => state.load);
  const ensureRoster = useRoster((state) => state.ensure);
  const tools = useFetched(loadTools, NO_TOOLS);
  const catalogue = useFetched(loadCatalogue, NO_CATALOGUE);

  useEffect(() => {
    ensureRoster();
  }, [ensureRoster]);

  const selected = agents.find((agent) => agent.id === selectedId) ?? null;
  // Every fetch this tab depends on reports here. A failed `/tools` used to
  // render an editor with no checkboxes and no explanation, and a save from
  // that state would have sent an empty allowlist.
  const error = actionError ?? rosterError ?? tools.error ?? catalogue.error;

  // No try/catch in either: the editor renders the failure inline against the
  // field the server named. See the module note.
  const create = async (body: CreateAgentRequest) => {
    const created = await api.createAgent(spaceId === null ? body : { ...body, space_id: spaceId });
    setSelectedId(created.id);
    void reloadRoster();
    setEditing("none");
  };

  // Moving a definition changes which roster it is on; copying makes a new
  // row on another roster. Either way this space's roster is re-read, and a
  // moved definition is no longer here to edit.
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
      // A built-in refuses deletion with a 409 and a message saying so. Showing
      // it is the point: §5 Phase 5 guards the delete path deliberately.
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
            // Remount on a different definition so the form state starts from
            // the row being edited rather than the one before it.
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
