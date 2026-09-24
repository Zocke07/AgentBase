import type { AgentDef } from "@agentbase/schemas";
import { useState } from "react";

/**
 * The roster: every definition, enabled or not, with the toggle that decides
 * whether the supervisor may draw on it. Delete asks first, is offered on
 * every row, and renders the server's 409 for a built-in rather than hiding
 * the button.
 */

export interface AgentListProps {
  agents: readonly AgentDef[];
  /** The roster is being fetched; `agents` is whatever was last known. */
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onToggleEnabled: (agent: AgentDef) => void;
  onDelete: (agent: AgentDef) => void;
  error: string | null;
  /** The row whose request is in flight; its controls are disabled meanwhile. */
  busyId: string | null;
}

export function AgentList({
  agents,
  loading,
  selectedId,
  onSelect,
  onCreate,
  onToggleEnabled,
  onDelete,
  error,
  busyId,
}: AgentListProps) {
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <section className="roster" data-testid="agent-list">
      <header className="roster__head">
        <h2>Agents</h2>
        <button type="button" className="button button--primary" onClick={onCreate}>
          New agent
        </button>
      </header>

      {error !== null && (
        <p className="roster__error" role="alert" data-testid="roster-error">
          {error}
        </p>
      )}

      {agents.length === 0 &&
        (loading ? (
          <p className="roster__empty">Loading…</p>
        ) : (
          <p className="roster__empty">No agent definitions yet.</p>
        ))}

      <ul className="roster__list">
        {agents.map((agent) => (
          <li
            key={agent.id}
            className={`roster__item${agent.id === selectedId ? " roster__item--selected" : ""}${
              agent.enabled === false ? " roster__item--disabled" : ""
            }`}
            data-testid={`agent-row-${agent.name}`}
          >
            <button
              type="button"
              className="roster__open"
              onClick={() => {
                onSelect(agent.id);
              }}
            >
              <span className="roster__name">
                {agent.name}
                {agent.is_builtin === true && <span className="roster__builtin">built-in</span>}
              </span>
              <span className="roster__role">{agent.role}</span>
              <span className="roster__meta">
                {agent.model ?? "space model"} ·{" "}
                {(agent.allowed_tools ?? []).length === 0
                  ? "no tools"
                  : `${String((agent.allowed_tools ?? []).length)} tools`}
                {agent.max_steps === undefined ? "" : ` · ${String(agent.max_steps)} steps`}
              </span>
            </button>

            <div className="roster__actions">
              <label className="roster__toggle">
                <input
                  type="checkbox"
                  checked={agent.enabled ?? true}
                  disabled={busyId === agent.id}
                  onChange={() => {
                    onToggleEnabled(agent);
                  }}
                  aria-label={`Available to the supervisor: ${agent.name}`}
                  data-testid={`toggle-${agent.name}`}
                />
                <span>{agent.enabled === false ? "disabled" : "enabled"}</span>
              </label>

              {confirming === agent.id ? (
                <span className="roster__confirm">
                  <span>Delete {agent.name}?</span>
                  <button
                    type="button"
                    className="button button--small button--danger"
                    disabled={busyId === agent.id}
                    onClick={() => {
                      setConfirming(null);
                      onDelete(agent);
                    }}
                    aria-label={`Delete ${agent.name}`}
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      setConfirming(null);
                    }}
                  >
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="button button--small button--danger"
                  disabled={busyId === agent.id}
                  onClick={() => {
                    setConfirming(agent.id);
                  }}
                  aria-label={`Delete ${agent.name}…`}
                  data-testid={`delete-${agent.name}`}
                >
                  Delete
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
