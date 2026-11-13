import type { SpaceResponse } from "@agentbase/schemas";

import { SECTION_ORDER, type Section } from "../lib/sections";

import { BrandMark } from "./BrandMark";
import { SpaceSwitcher } from "./SpaceSwitcher";
import { Icon, type IconName } from "./icons/Icon";

/**
 * Left rail with product, space switcher, current-space sections, and pinned
 * app Settings. Use buttons: no router, and sections remain mounted under
 * `hidden`.
 */

export type { Section } from "../lib/sections";

export interface RailProps {
  section: Section;
  onSelect: (section: Section) => void;
  spaces: readonly SpaceResponse[];
  currentSpaceId: string | null;
  onSelectSpace: (id: string) => void;
  onSpaceCreated: (space: SpaceResponse) => void;
  /** Glanceable section count, such as approvals or memory decisions. */
  badges?: Partial<Record<Section, number>> | undefined;
  /** Icon-only mode with names in tooltips; toggle lives at rail foot. */
  collapsed?: boolean | undefined;
  onToggleCollapsed?: (() => void) | undefined;
  /** Narrow-window drawer over page content. */
  drawer?: boolean | undefined;
}


const SECTIONS: readonly { id: Section; label: string; icon: IconName }[] = [
  { id: "home", label: "Home", icon: "house" },
  { id: "automations", label: "Automations", icon: "calendar-clock" },
  { id: "runs", label: "Runs", icon: "play" },
  { id: "agents", label: "Agents", icon: "users" },
  { id: "knowledge", label: "Knowledge", icon: "book-open" },
  { id: "usage", label: "Usage", icon: "circle-dollar-sign" },
  { id: "space", label: "Space settings", icon: "folder-cog" },
];

export function Rail({
  section,
  onSelect,
  spaces,
  currentSpaceId,
  onSelectSpace,
  onSpaceCreated,
  badges,
  collapsed = false,
  onToggleCollapsed,
  drawer = false,
}: RailProps) {
  const entry = (id: Section, label: string, icon: IconName) => {
    const badge = badges?.[id] ?? 0;
    const shortcut = SECTION_ORDER.indexOf(id) + 1;
    return (
      <button
        key={id}
        type="button"
        className={`rail__item${section === id ? " rail__item--active" : ""}`}
        aria-current={section === id ? "page" : undefined}
        title={`${label} (Ctrl/Cmd+${String(shortcut)})`}
        data-tour={`rail-${id}`}
        onClick={() => {
          onSelect(id);
        }}
      >
        {/* The selected row's icon is filled, as a Mac sidebar's is. */}
        <Icon name={icon} filled={section === id} />
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
    <nav
      className={`rail${collapsed ? " rail--collapsed" : ""}${drawer ? " rail--drawer" : ""}`}
      aria-label="Sections"
      data-testid="rail"
    >
      <div className="rail__brand">
        <BrandMark className="rail__logo" />
        <span className="rail__name">AgentBase</span>
      </div>

      <SpaceSwitcher
        spaces={spaces}
        currentId={currentSpaceId}
        onSelect={onSelectSpace}
        onCreated={onSpaceCreated}
        compact={collapsed}
      />

      <div className="rail__sections">{SECTIONS.map(({ id, label, icon }) => entry(id, label, icon))}</div>

      <div className="rail__bottom">
        {entry("settings", "Settings", "settings")}
        {onToggleCollapsed !== undefined && (
          <button
            type="button"
            className="rail__item rail__toggle"
            title={`${collapsed ? "Show" : "Hide"} the sidebar (Ctrl/Cmd+B)`}
            aria-label={collapsed ? "Show the sidebar" : "Hide the sidebar"}
            aria-pressed={collapsed}
            data-testid="rail-toggle"
            onClick={onToggleCollapsed}
          >
            <Icon name="panel-left" />
            <span>{collapsed ? "Show" : "Hide"} the sidebar</span>
          </button>
        )}
      </div>
    </nav>
  );
}
