import type { BudgetResponse } from "@agentbase/schemas";
import { useState } from "react";

import { CommandPalette } from "../../components/CommandPalette";
import { Rail, type Section } from "../../components/Rail";
import { Toolbar } from "../../components/Toolbar";
import { paletteCommands, type PaletteActions } from "../../lib/palette";
import { SECTION_LABEL } from "../../lib/sections";

import { SPACES } from "./fixtures";

/**
 * The window's frame, drawn as the shell draws it: the rail, the toolbar and
 * an empty section, at the smallest window the app allows (800 by 600) and
 * at a wide one with everything the toolbar can carry. The palette page
 * opens the command palette over it, with made-up runs, agents and notes.
 */

const BUDGET: BudgetResponse = {
  period: "2026-11",
  spent_micros: 4_210_000,
  cap_micros: 20_000_000,
  percent_used: 21,
  spent_display: "$4.21",
  cap_display: "$20.00",
  space_spent_micros: 3_100_000,
  space_spent_display: "$3.10",
};

const NOTHING = () => undefined;

interface FrameProps {
  label: string;
  width: number;
  height: number;
  busy: boolean;
  /** Draw macOS's overlaid title bar, with stand-ins for its three controls. */
  overlay?: boolean;
  folded?: boolean;
}

function Frame({ label, width, height, busy, overlay = false, folded = false }: FrameProps) {
  const [section, setSection] = useState<Section>("runs");
  const titleBar = overlay ? "overlay" : "native";
  return (
    <figure className="wb-frame">
      <figcaption className="wb-frame__label">{label}</figcaption>
      <div className="wb-frame__window" style={{ width, height }} data-titlebar={titleBar}>
        {overlay && (
          <span className="wb-traffic" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
        )}
        <div className={`app${folded ? " app--rail-collapsed" : ""}`}>
          <Rail
            section={section}
            onSelect={setSection}
            spaces={SPACES}
            currentSpaceId="space-main"
            onSelectSpace={NOTHING}
            onSpaceCreated={NOTHING}
            badges={busy ? { runs: 2, knowledge: 1 } : {}}
            onToggleCollapsed={NOTHING}
            collapsed={folded}
            titleBar={titleBar}
          />
          <div className="app__main">
            <Toolbar
              title={section === "home" ? "Main" : SECTION_LABEL[section]}
              waiting={busy ? 2 : 0}
              onOpenWaiting={NOTHING}
              setup={busy ? { reason: "Add an API key in Settings.", onFinish: NOTHING } : null}
              model={{ label: "Sonnet 5.5", title: "Tasks in this space use Anthropic's Sonnet 5.5." }}
              meter={{ budget: BUDGET, spaceName: "Main", runLimitMicros: 2_000_000 }}
              onOpenPalette={NOTHING}
              titleBar={titleBar}
            />
            <main className="app__body wb-shell__body">
              <p>{SECTION_LABEL[section]} is drawn here.</p>
            </main>
          </div>
        </div>
      </div>
    </figure>
  );
}

export function ShellPage() {
  return (
    <div className="wb-frames">
      <Frame label="The smallest window, 800 by 600" width={800} height={600} busy={false} />
      <Frame label="Wide, with questions waiting and setup to finish" width={1080} height={600} busy />
      <Frame label="macOS inside the app: the title bar is an overlay" width={1000} height={600} busy={false} overlay />
      <Frame label="macOS, the rail folded" width={800} height={600} busy={false} overlay folded />
    </div>
  );
}

const ACTIONS: PaletteActions = {
  section: NOTHING,
  startRun: NOTHING,
  schedule: NOTHING,
  newSpace: NOTHING,
  toggleRail: NOTHING,
  theme: NOTHING,
  tour: NOTHING,
  portfolio: NOTHING,
  marketWatch: NOTHING,
  space: NOTHING,
  run: NOTHING,
  agent: NOTHING,
  note: NOTHING,
};

const COMMANDS = paletteCommands({
  spaces: SPACES,
  currentSpaceId: "space-main",
  runs: [
    ["Morning research", "Collect the overnight headlines for the handbook"],
    [null, "Review chapter two against the style guide"],
    ["Weekly summary", "Summarise the week's reviews"],
  ].map(([title, goal], index) => ({
    id: `run-${String(index)}`,
    space_id: "space-main",
    goal: goal ?? "",
    title: title ?? null,
    status: "completed",
    origin: "ui",
    origin_ref: null,
    created_at: "2026-11-10T08:00:00Z",
    finished_at: "2026-11-10T08:04:00Z",
  })),
  agents: [],
  notes: [],
  railOpen: true,
  theme: "system",
  actions: ACTIONS,
});

export function PalettePage() {
  return (
    <div className="wb-frames">
      <Frame label="Behind the palette" width={800} height={600} busy={false} />
      <CommandPalette open commands={COMMANDS} onClose={NOTHING} />
    </div>
  );
}
