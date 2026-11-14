import { useEffect, useState } from "react";

import {
  applyEnvironment,
  effectiveTheme,
  MOTION_CHOICES,
  PLATFORM_CHOICES,
  THEME_CHOICES,
  TRANSPARENCY_CHOICES,
  type Environment,
} from "./environment";
import { PAGE_GROUPS, pageById, PAGES } from "./pages";

/**
 * The workbench: every part of the interface drawn from fixtures, with
 * switches for the conditions it must hold up under. It is a development
 * page (`just workbench`), served by Vite's dev server only; the app's build
 * does not include it, and nothing in it calls the sidecar.
 *
 * The page and the switches live in the URL's query, so any state can be
 * linked to: `workbench.html?page=office-shell-question&theme=dark&cursor=12`.
 */

export interface WorkbenchProps {
  initialPage: string | null;
  initialEnvironment: Environment;
  initialCursor?: number;
}

const LABELS: Readonly<Record<string, string>> = {
  system: "System",
  light: "Light",
  dark: "Dark",
  reduce: "Reduced",
  mac: "macOS",
  windows: "Windows",
};

function Choice<Value extends string>({
  label,
  value,
  choices,
  onChange,
}: {
  label: string;
  value: Value;
  choices: readonly Value[];
  onChange: (value: Value) => void;
}) {
  return (
    <label className="wb-choice">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => {
          const chosen = choices.find((choice) => choice === event.target.value);
          if (chosen !== undefined) onChange(chosen);
        }}
      >
        {choices.map((choice) => (
          <option key={choice} value={choice}>
            {LABELS[choice] ?? choice}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Workbench({ initialPage, initialEnvironment, initialCursor }: WorkbenchProps) {
  const [pageId, setPageId] = useState(() => pageById(initialPage).id);
  const [environment, setEnvironment] = useState(initialEnvironment);
  const page = pageById(pageId);
  // Where a run page opens: the linked cursor, for the page it was linked
  // for. Where its player stands now is kept apart, for the link alone, so
  // a moving cursor never re-opens the player.
  const [openAt, setOpenAt] = useState(page.layout === "fill" ? initialCursor : undefined);
  const [cursor, setCursor] = useState(openAt);

  // Applied before the state changes, so a page that measures the document
  // in a layout effect already sees the new attributes.
  const change = (next: Environment) => {
    applyEnvironment(next);
    setEnvironment(next);
  };

  // "System" follows the OS while the tab is open.
  const [, setSystemTheme] = useState(0);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      setSystemTheme((count) => count + 1);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  useEffect(() => {
    const query = new URLSearchParams({ page: pageId });
    if (environment.theme !== "system") query.set("theme", environment.theme);
    if (environment.motion !== "system") query.set("motion", environment.motion);
    if (environment.platform !== "mac") query.set("platform", environment.platform);
    if (environment.transparency !== "system") query.set("transparency", environment.transparency);
    if (cursor !== undefined) query.set("cursor", String(cursor));
    window.history.replaceState(null, "", `${window.location.pathname}?${query.toString()}`);
  }, [pageId, environment, cursor]);

  return (
    <div className="wb">
      <nav className="wb__nav" aria-label="Workbench pages">
        <p className="wb__name">Workbench</p>
        {PAGE_GROUPS.map((group) => (
          <div key={group} className="wb__group">
            <p className="wb__group-name" id={`wb-group-${group}`}>
              {group}
            </p>
            <ul aria-labelledby={`wb-group-${group}`}>
              {PAGES.filter((candidate) => candidate.group === group).map((candidate) => (
                <li key={candidate.id}>
                  <button
                    type="button"
                    className="wb__link"
                    aria-current={candidate.id === page.id ? "page" : undefined}
                    onClick={() => {
                      setPageId(candidate.id);
                      setOpenAt(undefined);
                      setCursor(undefined);
                    }}
                  >
                    {candidate.title}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="wb__main">
        <header className="wb__bar">
          <div className="wb__heading">
            <h1 className="wb__title">{page.title}</h1>
            <p className="wb__about">{page.about}</p>
          </div>
          <div className="wb__switches" role="group" aria-label="Conditions">
            <Choice
              label="Theme"
              value={environment.theme}
              choices={THEME_CHOICES}
              onChange={(theme) => {
                change({ ...environment, theme });
              }}
            />
            <Choice
              label="Motion"
              value={environment.motion}
              choices={MOTION_CHOICES}
              onChange={(motion) => {
                change({ ...environment, motion });
              }}
            />
            <Choice
              label="Platform"
              value={environment.platform}
              choices={PLATFORM_CHOICES}
              onChange={(platform) => {
                change({ ...environment, platform });
              }}
            />
            <Choice
              label="Transparency"
              value={environment.transparency}
              choices={TRANSPARENCY_CHOICES}
              onChange={(transparency) => {
                change({ ...environment, transparency });
              }}
            />
          </div>
        </header>

        {/* Focusable, so a page that scrolls can be scrolled from the keyboard. */}
        <main className="wb__page" data-testid="wb-page" data-page={page.id} tabIndex={0}>
          {page.render({
            theme: effectiveTheme(environment.theme),
            ...(openAt === undefined ? {} : { cursor: openAt }),
            onCursor: setCursor,
          })}
        </main>
      </div>
    </div>
  );
}
