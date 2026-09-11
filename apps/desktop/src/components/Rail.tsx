import type { ReactNode } from "react";

/**
 * The left rail — BUILD_SPEC §5 Phase 11, "a sidebar, not tabs".
 *
 * Top to bottom: the product's name, then the sections of the workspace —
 * Home, Runs, Agents — and, pinned to the bottom, the app-wide Settings. The
 * gap under the name is deliberate: it is where the space switcher goes when
 * spaces land, and laying the rail out with room for it now means that step
 * adds a control rather than rearranging the frame.
 *
 * Every entry is a button, not a link: the shell has no router, and the
 * sections are all mounted at once behind `hidden` so a visit to one does not
 * unmount another's stream.
 */

export type Section = "home" | "runs" | "agents" | "settings";

export interface RailProps {
  section: Section;
  onSelect: (section: Section) => void;
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
];

export function Rail({ section, onSelect }: RailProps) {
  const entry = (id: Section, label: string, icon: ReactNode) => (
    <button
      key={id}
      type="button"
      className={`rail__item${section === id ? " rail__item--active" : ""}`}
      aria-current={section === id ? "page" : undefined}
      onClick={() => {
        onSelect(id);
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );

  return (
    <nav className="rail" aria-label="Sections" data-testid="rail">
      <div className="rail__brand">
        <span className="rail__logo" aria-hidden="true" />
        <span className="rail__name">AgentSpace</span>
      </div>

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
