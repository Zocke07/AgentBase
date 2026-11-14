import type { ReactNode } from "react";

import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/paths";

/**
 * A status word with its glyph (brief 4.1): the hue says it at a glance,
 * the glyph says it without colour (forced colours, a colour-blind eye) and
 * the word says it to everyone. The glyph is hidden from screen readers;
 * the word is the name.
 */

export type StatusKind = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";

const GLYPH: Readonly<Record<StatusKind, IconName>> = {
  pending: "circle-dashed",
  running: "circle-dot",
  paused: "circle-pause",
  completed: "circle-check",
  failed: "circle-x",
  cancelled: "circle-slash",
};

const isKind = (kind: string): kind is StatusKind => Object.hasOwn(GLYPH, kind);

export function Status({ kind, children, testId }: { kind: string; children: ReactNode; testId?: string }) {
  // A status this build does not know reads as waiting, never as a crash.
  const known = isKind(kind) ? kind : "pending";
  return (
    <span className={`status status--${known}`} data-testid={testId}>
      <Icon name={GLYPH[known]} size={16} />
      {children}
    </span>
  );
}
