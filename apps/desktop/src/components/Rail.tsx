import type { SpaceResponse } from "@agentspace/schemas";
import type { ReactNode } from "react";

import { SECTION_ORDER, type Section } from "../lib/sections";

import { SpaceSwitcher } from "./SpaceSwitcher";

/**
 * The left rail: the product's name, the space switcher, the current space's
 * sections (Home, Runs, Agents, Space settings) and, pinned to the bottom,
 * the app-wide Settings. Buttons, not links: there is no router, and every
 * section stays mounted behind `hidden`.
 */

export type { Section } from "../lib/sections";

export interface RailProps {
  section: Section;
  onSelect: (section: Section) => void;
  spaces: readonly SpaceResponse[];
  currentSpaceId: string | null;
  onSelectSpace: (id: string) => void;
  onSpaceCreated: (space: SpaceResponse) => void;
  /** A count worth a glance beside a section's name: approvals waiting, memories to decide on. */
  badges?: Partial<Record<Section, number>> | undefined;
}


const SECTIONS: readonly { id: Section; label: string; icon: ReactNode }[] = [
  {
    id: "home",
    label: "Home",
    icon: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M3 9.5 10 3l7 6.5V17h-4.5v-4.5h-5V17H3z" />
      </svg>
    ),
  },
  {
    id: "runs",
    label: "Runs",
    icon: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M5 3.5v13l10-6.5z" />
      </svg>
    ),
  },
  {
    id: "agents",
    label: "Agents",
    icon: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="7" cy="6.5" r="3" />
        <circle cx="14" cy="7.5" r="2.25" />
        <path d="M1.5 16a5.5 5.5 0 0 1 11 0zM12.5 15.5a4 4 0 0 1 6 0z" />
      </svg>
    ),
  },
  {
    id: "knowledge",
    label: "Knowledge",
    icon: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M3 3.5h5.2c.7 0 1.3.3 1.8.8.5-.5 1.1-.8 1.8-.8H17V16h-5.2c-.7 0-1.3.3-1.8.8-.5-.5-1.1-.8-1.8-.8H3zm6.2 2A1.8 1.8 0 0 0 8 5H4.5v9.5H8c.4 0 .8.1 1.2.3zm1.6 9.3c.4-.2.8-.3 1.2-.3h3.5V5H12c-.5 0-.9.2-1.2.5z" />
      </svg>
    ),
  },
  {
    id: "space",
    label: "Space settings",
    icon: (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M3 5.5A1.5 1.5 0 0 1 4.5 4h3.6l1.6 1.6h5.8A1.5 1.5 0 0 1 17 7.1V15a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 15z" />
      </svg>
    ),
  },
];

export function Rail({
  section,
  onSelect,
  spaces,
  currentSpaceId,
  onSelectSpace,
  onSpaceCreated,
  badges,
}: RailProps) {
  const entry = (id: Section, label: string, icon: ReactNode) => {
    const badge = badges?.[id] ?? 0;
    const shortcut = SECTION_ORDER.indexOf(id) + 1;
    return (
      <button
        key={id}
        type="button"
        className={`rail__item${section === id ? " rail__item--active" : ""}`}
        aria-current={section === id ? "page" : undefined}
        title={`${label} (Ctrl/Cmd+${String(shortcut)})`}
        onClick={() => {
          onSelect(id);
        }}
      >
        {icon}
        <span>{label}</span>
        {badge > 0 && (
          <span className="rail__badge" aria-label={`${String(badge)} waiting`}>
            {badge}
          </span>
        )}
      </button>
    );
  };

  return (
    <nav className="rail" aria-label="Sections" data-testid="rail">
      <div className="rail__brand">
        <span className="rail__logo" aria-hidden="true" />
        <span className="rail__name">AgentSpace</span>
      </div>

      <SpaceSwitcher
        spaces={spaces}
        currentId={currentSpaceId}
        onSelect={onSelectSpace}
        onCreated={onSpaceCreated}
      />

      <div className="rail__sections">{SECTIONS.map(({ id, label, icon }) => entry(id, label, icon))}</div>

      <div className="rail__bottom">
        {entry(
          "settings",
          "Settings",
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M10 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm7.2 4.5.1-1-1.6-1.2a5.6 5.6 0 0 0-.5-1.2l.7-1.9-.7-.7-1.9.7a5.6 5.6 0 0 0-1.2-.5L10.9 2H9.1L8 3.7a5.6 5.6 0 0 0-1.2.5L4.9 3.5l-.7.7.7 1.9a5.6 5.6 0 0 0-.5 1.2L2.8 9v1l1.6 1.2c.1.4.3.8.5 1.2l-.7 1.9.7.7 1.9-.7c.4.2.8.4 1.2.5L9.1 18h1.8l1.1-1.7c.4-.1.8-.3 1.2-.5l1.9.7.7-.7-.7-1.9c.2-.4.4-.8.5-1.2z" />
          </svg>,
        )}
      </div>
    </nav>
  );
}
