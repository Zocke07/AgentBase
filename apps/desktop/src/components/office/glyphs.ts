import type { ToolFamily } from "../../lib/tools";
import type { Face, SlipState, Stamp } from "../../state/office";
import type { IconName } from "../icons/Icon";

/**
 * The glyph for each thing the office says in words. A state is never a
 * colour alone: it has its word in the model and its glyph here, and
 * `glyphs.test.ts` holds both lists complete.
 */

/** The object on a desk while a tool of this family runs. */
export const FAMILY_ICON: Readonly<Record<ToolFamily, IconName>> = {
  delegation: "send",
  reading: "file-text",
  writing: "pencil",
  knowledge: "book-open",
  network: "globe",
  market: "trending-up",
  computation: "calculator",
  shell: "terminal",
  unknown: "box",
};

/** What a face shows beside its word. `tool` takes the family's glyph instead. */
export const FACE_ICON: Readonly<Record<Face, IconName>> = {
  dot: "user-round",
  asking: "ellipsis",
  thinking: "ellipsis",
  tool: "box",
  question: "circle-help",
  tick: "check",
  knot: "triangle-alert",
  alert: "triangle-alert",
};

export const STAMP_ICON: Readonly<Record<Stamp["kind"], IconName>> = {
  policy: "stamp",
  precedent: "stamp",
  allowed: "stamp",
  denied: "x",
  expired: "clock",
  sandbox: "shield-x",
  refused: "x",
};

/** How a slip's state colours its edge: a status, or none. */
export const SLIP_TONE: Readonly<Record<SlipState, "none" | "info" | "warn" | "good" | "bad">> = {
  requested: "none",
  waiting: "warn",
  working: "info",
  done: "good",
  failed: "bad",
  missed: "none",
  refused: "bad",
};
