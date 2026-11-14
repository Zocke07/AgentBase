import type { AgentDef, ToolResponse } from "@agentbase/schemas";
import { useState } from "react";

import { modelLabel } from "../lib/format";
import { restingDesk, toolsOnDesk, toolsSummary } from "../state/floorPlan";

import { Skeleton } from "./Skeleton";
import { DeskFigure } from "./office/Room";
import { VIGNETTE_SPOT, vignetteView } from "./office/vignette";
import { useContextMenu } from "./ui/ContextMenu";
import { Switch } from "./ui/controls";

/**
 * The roster as a floor plan (Phase 20, brief 7.13): a desk card for each
 * definition, drawn with the office's own figure, with its role, its
 * model, its tools by risk and whether the supervisor may use it. A card
 * opens the editor in the inspector. Deletion confirms, and renders a
 * built-in's 409 instead of hiding the control.
 */

/** The part of the drawing a card shows. */
const VIEW = vignetteView(124, 112, 92);

export interface AgentListProps {
  agents: readonly AgentDef[];
  /** Roster fetch in progress; `agents` retains last known data. */
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onToggleEnabled: (agent: AgentDef) => void;
  onDelete: (agent: AgentDef) => void;
  error: string | null;
  /** Row with in-flight request; disable its controls. */
  busyId: string | null;
  /** The tools this space offers, for each card's risk dots. */
  tools?: readonly ToolResponse[] | undefined;
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
  tools = [],
}: AgentListProps) {
  const [confirming, setConfirming] = useState<string | null>(null);
  // The row's own actions, from a right-click or the keyboard's menu key.
  const context = useContextMenu("Agent", (element) => {
    const agent = agents.find((candidate) => candidate.id === element.dataset.agentId);
    if (agent === undefined) return [];
    const busy = busyId === agent.id;
    return [
      {
        id: "edit",
        label: "Edit",
        onSelect: () => {
          onSelect(agent.id);
        },
      },
      {
        id: "enabled",
        label: agent.enabled === false ? "Make available to the supervisor" : "Make unavailable to the supervisor",
        disabled: busy,
        onSelect: () => {
          onToggleEnabled(agent);
        },
      },
      { id: "gap", separator: true },
      {
        id: "delete",
        label: "Delete…",
        danger: true,
        disabled: busy,
        onSelect: () => {
          setConfirming(agent.id);
        },
      },
    ];
  });

  return (
    <section className="roster" data-testid="agent-list">
      <header className="roster__head">
        <div>
          <h2>The agents in this space</h2>
          <p className="roster__hint">
            An available agent is one the supervisor can put to work. Pick a desk to edit its agent.
          </p>
        </div>
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
          <Skeleton label="Loading the agents" lines={4} />
        ) : (
          <p className="roster__empty">No agent definitions yet.</p>
        ))}

      <ul className="floor" aria-label="Agents in this space">
        {agents.map((agent) => {
          const available = agent.enabled !== false;
          const busy = busyId === agent.id;
          const onDesk = toolsOnDesk(agent, tools);
          return (
            <li
              key={agent.id}
              className={`floor__card${agent.id === selectedId ? " floor__card--selected" : ""}${
                available ? "" : " floor__card--away"
              }`}
              data-testid={`agent-row-${agent.name}`}
            >
              <button
                type="button"
                className="floor__open"
                data-agent-id={agent.id}
                aria-current={agent.id === selectedId ? "true" : undefined}
                onClick={() => {
                  onSelect(agent.id);
                }}
                {...context.trigger}
              >
                <svg className="floor__figure" viewBox={VIEW} aria-hidden="true" focusable="false">
                  <DeskFigure desk={restingDesk(agent)} spot={VIGNETTE_SPOT} />
                </svg>
                <span className="floor__name">
                  {agent.name}
                  {agent.is_builtin === true && <span className="floor__builtin">built-in</span>}
                </span>
                <span className="floor__role" title={agent.role}>
                  {agent.role}
                </span>
              </button>

              <div className="floor__facts">
                <span className="floor__model" title={agent.model ?? undefined}>
                  {agent.model === undefined || agent.model === null ? "The space's model" : modelLabel(agent.model)}
                </span>
                <span className="floor__tools" title={onDesk.map((tool) => `${tool.name}: ${tool.risk} risk`).join("\n")}>
                  <span className="floor__dots" aria-hidden="true">
                    {onDesk.map((tool) => (
                      <span key={tool.name} className={`floor__dot floor__dot--${tool.risk}`} />
                    ))}
                  </span>
                  {toolsSummary(onDesk)}
                  {agent.max_steps === undefined ? "" : ` · ${String(agent.max_steps)} steps`}
                </span>
              </div>

              <div className="floor__actions">
                <span className="floor__available">
                  <Switch
                    checked={available}
                    disabled={busy}
                    label={`Available to the supervisor: ${agent.name}`}
                    testId={`toggle-${agent.name}`}
                    onChange={() => {
                      onToggleEnabled(agent);
                    }}
                  />
                  <span aria-hidden="true">{available ? "Available" : "Not available"}</span>
                </span>

                {confirming === agent.id ? (
                  <span className="roster__confirm">
                    <span>Delete {agent.name}?</span>
                    <button
                      type="button"
                      className="button button--small button--danger"
                      disabled={busy}
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
                    className="button button--small floor__delete"
                    disabled={busy}
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
          );
        })}
      </ul>
      {context.menu}
    </section>
  );
}
