import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";
import { ICON_NAMES, ICONS } from "./paths";

const SRC = join(import.meta.dirname, "..", "..");

function sources(folder = SRC): string[] {
  return readdirSync(folder).flatMap((entry) => {
    const path = join(folder, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe("Icon", () => {
  it("draws one style: stroked in the text's colour on Lucide's grid", () => {
    const { container } = render(<Icon name="house" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg?.classList.contains("icon")).toBe(true);
    expect(svg?.getAttribute("data-icon")).toBe("house");
    expect(svg?.querySelectorAll("path").length).toBe(ICONS.house.length);
    // Nothing in the markup names a colour: the stylesheet strokes it.
    expect(svg?.outerHTML).not.toMatch(/#[0-9a-f]{3,6}|rgb\(/i);
  });

  it("keeps a 1.5 px stroke at every size it is drawn at", () => {
    for (const size of [16, 20, 24] as const) {
      const { container } = render(<Icon name="check" size={size} />);
      const svg = container.querySelector("svg");
      expect(svg?.getAttribute("width")).toBe(String(size));
      // Stroke width is in grid units: on screen it is width × size ÷ 24.
      expect((Number(svg?.getAttribute("stroke-width")) * size) / 24).toBeCloseTo(1.5);
    }
  });

  it("is hidden from a screen reader beside a word, and an image when it stands alone", () => {
    const { container } = render(<Icon name="clock" />);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    render(<Icon name="stamp" label="Approved" />);
    expect(screen.getByRole("img", { name: "Approved" })).toBeDefined();
  });

  it("marks the filled variant for the selected row", () => {
    const { container } = render(<Icon name="house" filled className="rail__icon" />);
    expect(container.querySelector("svg")?.getAttribute("class")).toBe("icon icon--filled rail__icon");
  });
});

describe("the vendored icons", () => {
  it("carry Lucide's licence beside them", () => {
    const licence = readFileSync(join(import.meta.dirname, "LICENSE"), "utf8");
    expect(licence).toContain("ISC License");
    expect(licence).toContain("Lucide");
  });

  it("are only the ones the interface uses", () => {
    // D6: the icons in use are vendored, not the whole set.
    const code = sources()
      .filter((path) => !path.endsWith(join("icons", "paths.ts")))
      .map((path) => readFileSync(path, "utf8"))
      .join("\n");
    expect(ICON_NAMES.filter((name) => !code.includes(`"${name}"`))).toEqual([]);
  });

  it("hold only shapes, never a script or a link", () => {
    for (const name of ICON_NAMES) {
      for (const [shape, attributes] of ICONS[name]) {
        expect(["path", "circle", "rect", "line", "polyline", "polygon", "ellipse"]).toContain(shape);
        expect(Object.keys(attributes).filter((key) => /^on|href/i.test(key))).toEqual([]);
      }
    }
  });
});
