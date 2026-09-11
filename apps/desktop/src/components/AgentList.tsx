import type { AgentDef } from "@agentspace/schemas";

/**
 * The roster — §5 Phase 7's `AgentList.tsx`: "every defined agent, its role,
 * model, and tool count. Enable/disable toggle. Create and delete."
 *
 * The list shows every definition, enabled or not, because this is the editor's
 * view of them. A *run* sees only the enabled ones — the registry filters at
 * load time — so the toggle here is what decides whether the supervisor can
 * draw on an agent at all, and hiding disabled rows would make that invisible.
 *
 * Delete is offered on every row and refused by the server for built-ins with a
 * 409. That refusal is rendered rather than pre-empted by hiding the button:
 * §5 Phase 5 guards the delete path deliberately, and a user who tries deserves
 * to be told why rather than to find a missing control.
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
}: AgentListProps) {
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
                {agent.model ?? "workspace model"} ·{" "}
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
                  onChange={() => {
                    onToggleEnabled(agent);
                  }}
                  aria-label={`Available to the supervisor: ${agent.name}`}
                  data-testid={`toggle-${agent.name}`}
                />
                <span>{agent.enabled === false ? "disabled" : "enabled"}</span>
              </label>

              <button
                type="button"
                className="button button--small button--danger"
                onClick={() => {
                  onDelete(agent);
                }}
                data-testid={`delete-${agent.name}`}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
