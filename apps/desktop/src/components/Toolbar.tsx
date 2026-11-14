import type { ReactNode } from "react";

import { currentPlatform, currentTitleBar, type TitleBar } from "../lib/platform";
import { withShortcut } from "../lib/shortcuts";

import { BudgetMeter, type BudgetMeterProps } from "./BudgetMeter";
import { IconButton } from "./ui/controls";

/**
 * The window's toolbar (Phase 20, brief 6.1): the section's title at the
 * left, then the section's own actions, then what belongs to the whole
 * window: questions waiting, unfinished setup, the space's model, the
 * month's spend and the way into the command palette.
 *
 * It draws what it is given and fetches nothing, so the workbench can draw
 * the shell with no sidecar.
 *
 * On macOS the title bar is the toolbar (decision D5): its empty space, and
 * the title, drag the window. A control inside it never does, because the
 * drag region is the element pressed, not its children.
 */

export interface ToolbarProps {
  title: string;
  /** The section's own buttons, between the title and the global items. */
  actions?: ReactNode;
  /** Questions waiting on someone, in any space. */
  waiting: number;
  onOpenWaiting: () => void;
  /** Why tasks cannot start yet, and where that is put right; null when they can. */
  setup: { reason: string; onFinish: () => void } | null;
  /** The model the space's tasks use, as a chip; null before it is known. */
  model: { label: string; title: string } | null;
  meter: BudgetMeterProps;
  onOpenPalette: () => void;
  /** The window's, unless the workbench draws another platform's. */
  titleBar?: TitleBar | undefined;
}

export function Toolbar({
  title,
  actions,
  waiting,
  onOpenWaiting,
  setup,
  model,
  meter,
  onOpenPalette,
  titleBar = currentTitleBar(),
}: ToolbarProps) {
  const platform = currentPlatform();
  // Windows keeps its own title bar, which already moves the window.
  const drag = titleBar === "overlay" ? { "data-tauri-drag-region": "" } : {};

  return (
    <header className="toolbar" data-testid="toolbar" {...drag}>
      <h1 className="toolbar__title" {...drag}>
        {title}
      </h1>
      {actions !== undefined && <div className="toolbar__actions">{actions}</div>}
      <div className="toolbar__global" {...drag}>
        {waiting > 0 && (
          <button type="button" className="toolbar__pill toolbar__pill--warn" onClick={onOpenWaiting}>
            {waiting} approval{waiting === 1 ? "" : "s"} waiting
          </button>
        )}
        {setup !== null && (
          // Show the way to put it right, not only that something is wrong.
          <button
            type="button"
            className="toolbar__pill toolbar__pill--warn toolbar__setup"
            title={setup.reason}
            onClick={setup.onFinish}
          >
            Finish setup
          </button>
        )}
        {model !== null && (
          <span className="toolbar__model" title={model.title} data-testid="header-model">
            <span className="toolbar__model-dot" aria-hidden="true" />
            {model.label}
          </span>
        )}
        <BudgetMeter {...meter} />
        <IconButton
          icon="search"
          label="Find anything"
          title={withShortcut("Find anything", "palette", platform)}
          size={16}
          testId="palette-button"
          onClick={onOpenPalette}
        />
      </div>
    </header>
  );
}
