import type {
  AgentDef,
  CreateAgentRequest,
  ProviderCatalogueResponse,
  SpaceResponse,
  ToolResponse,
  UpdateAgentRequest,
} from "@agentbase/schemas";
import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../lib/api";
import { useRoster } from "../state/roster";
import { useFetched } from "../state/useFetched";
import { useMediaQuery } from "../state/useMediaQuery";
import { useStoredSize } from "../state/useStoredSize";

import { AgentEditor } from "./AgentEditor";
import { AgentList } from "./AgentList";
import { Inspector } from "./ui/Inspector";
import { Sheet } from "./ui/Sheet";



/**
 * The roster as a floor plan, with the editor in the inspector (Phase 20,
 * brief 7.13 and 6.3); below 1,100 px the editor opens as a sheet. Unsaved
 * changes hold any move away, closing included, until the person chooses.
 * Re-throw save `ApiError` to `AgentEditor` for named-input rendering.
 */

const NO_TOOLS: ToolResponse[] = [];

/** The inspector's width in the stylesheet (28rem), and the narrowest it goes. */
const INSPECTOR_WIDTH = 420;
const INSPECTOR_WIDTH_MIN = 340;
const NO_CATALOGUE: ProviderCatalogueResponse = { providers: [], models: {}, catalog: {} };

export interface AgentsViewProps {
  /** Space run provider, resolving editor `inherit`. */
  workspaceProvider: string | null;
  /** Roster space; new definitions join it. Null before load. */
  spaceId?: string | null;
  /** All spaces for moving/copying definitions. */
  spaces?: readonly SpaceResponse[];
  /** An agent to open, from the command palette; the nonce reopens the same one. */
  openRequest?: { id: string; nonce: number } | null | undefined;
}

export function AgentsView({ workspaceProvider, spaceId = null, spaces = [], openRequest = null }: AgentsViewProps) {
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
  // Outside the default space, the general tools only.
  const loadTools = useCallback(() => api.listTools(spaceId), [spaceId]);
  const tools = useFetched(loadTools, NO_TOOLS);
  const catalogue = useFetched(api.listProviders, NO_CATALOGUE);

  useEffect(() => {
    ensureRoster();
  }, [ensureRoster]);

  const selected = agents.find((agent) => agent.id === selectedId) ?? null;
  // The editor is the floor's inspector, or a sheet in a narrow window.
  const narrow = useMediaQuery("(max-width: 1100px)");
  const [inspectorWidth, setInspectorWidth] = useStoredSize("agents.inspector");
  const inspector = useRef<HTMLElement>(null);
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

  // Opened from elsewhere, as a press on its row would open it: unsaved
  // changes are asked about first.
  const [seenRequest, setSeenRequest] = useState(openRequest?.nonce ?? null);
  if (openRequest !== null && openRequest.nonce !== seenRequest) {
    setSeenRequest(openRequest.nonce);
    const open = () => {
      setSelectedId(openRequest.id);
      setEditing("existing");
    };
    if (dirty && editing !== "none") setHeld(() => open);
    else open();
  }
  // Reread which models a ChatGPT plan includes, as a press on a row does.
  const reloadCatalogue = catalogue.reload;
  useEffect(() => {
    if (seenRequest !== null) reloadCatalogue();
  }, [seenRequest, reloadCatalogue]);

  const editorTitle = editing === "new" ? "New agent" : `Edit ${selected?.name ?? "the agent"}`;
  const closeEditor = () => {
    guarded(() => {
      setEditing("none");
    });
  };
  const editor = (
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
        titled={false}
        // Remount for each definition to reset form from its row.
        key={editing === "new" ? "new" : (selected?.id ?? "new")}
        agent={editing === "existing" ? selected : null}
        tools={tools.data}
        catalogue={catalogue.data}
        workspaceProvider={workspaceProvider}
        onCreate={create}
        onPatch={patch}
        onDirtyChange={setDirty}
        onCancel={closeEditor}
      />
    </>
  );

  return (
    <div
      className={`agents-view${editing !== "none" && !narrow ? " agents-view--inspecting" : ""}`}
      onKeyDown={(event) => {
        // Escape closes the editor from anywhere in the section, the desk
        // that opened it included; unsaved changes still ask first.
        if (event.key !== "Escape" || event.defaultPrevented || editing === "none") return;
        // A menu or sheet rendered from here into the body (a desk's
        // context menu) has its own Escape, which closes only it.
        if (!(event.target instanceof Node) || !event.currentTarget.contains(event.target)) return;
        event.preventDefault();
        closeEditor();
      }}
    >
      <AgentList
        agents={agents}
        loading={rosterLoading}
        selectedId={selectedId}
        error={error}
        busyId={busyId}
        tools={tools.data}
        onSelect={(id) => {
          guarded(() => {
            setSelectedId(id);
            setEditing("existing");
            // Reread which models a ChatGPT plan includes: access may have changed.
            catalogue.reload();
          });
        }}
        onCreate={() => {
          guarded(() => {
            setSelectedId(null);
            setEditing("new");
            catalogue.reload();
          });
        }}
        onToggleEnabled={(agent) => void toggleEnabled(agent)}
        onDelete={(agent) => void remove(agent)}
      />

      {editing !== "none" &&
        (narrow ? (
          // Too narrow for the floor and the editor side by side (brief 6.3).
          <Sheet open title={editorTitle} onClose={closeEditor} size="large" testId="agents-inspector">
            {editor}
          </Sheet>
        ) : (
          <Inspector
            label="Agent editor"
            className="agents-view__inspector"
            testId="agents-inspector"
            panelRef={inspector}
            title={editorTitle}
            subtitle={editing === "existing" ? selected?.role : undefined}
            onClose={closeEditor}
            closeLabel="Close the editor"
            width={inspectorWidth}
            onResize={setInspectorWidth}
            defaultWidth={INSPECTOR_WIDTH}
            minWidth={INSPECTOR_WIDTH_MIN}
            maxWidth={() => Math.max(INSPECTOR_WIDTH_MIN, Math.round(window.innerWidth * 0.6))}
            measure={() => inspector.current?.offsetWidth ?? INSPECTOR_WIDTH}
            resizeLabel="Resize the agent editor"
          >
            {editor}
          </Inspector>
        ))}
    </div>
  );
}
