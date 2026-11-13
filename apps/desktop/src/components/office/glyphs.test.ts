import { describe, expect, it } from "vitest";

import { TOOL_FAMILIES } from "../../lib/tools";
import { ICONS } from "../icons/paths";

import { FACE_ICON, FAMILY_ICON, SLIP_TONE, STAMP_ICON } from "./glyphs";

/** Brief 9.4: every reducer activity and every tool family has a pose or an object. */
describe("the office's glyphs", () => {
  it("has an object for every tool family, each its own", () => {
    for (const family of TOOL_FAMILIES) expect(ICONS[FAMILY_ICON[family]], family).toBeDefined();
    expect(new Set(TOOL_FAMILIES.map((family) => FAMILY_ICON[family])).size).toBe(TOOL_FAMILIES.length);
  });

  it("has a glyph for every face, stamp and slip state", () => {
    for (const icon of [...Object.values(FACE_ICON), ...Object.values(STAMP_ICON)]) expect(ICONS[icon]).toBeDefined();
    expect(Object.keys(FACE_ICON).sort()).toEqual(["alert", "asking", "dot", "knot", "question", "thinking", "tick", "tool"]);
    expect(Object.keys(STAMP_ICON).sort()).toEqual(["allowed", "denied", "expired", "policy", "precedent", "refused", "sandbox"]);
    expect(Object.keys(SLIP_TONE).sort()).toEqual(["done", "failed", "missed", "refused", "requested", "waiting", "working"]);
  });
});
