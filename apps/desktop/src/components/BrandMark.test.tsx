import { readFileSync } from "node:fs";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandMark } from "./BrandMark";

const css = readFileSync("src/index.css", "utf8");

describe("AgentBase brand mark", () => {
  it("uses a dedicated contrasting palette and stays crisp in the light rail", () => {
    render(<BrandMark className="rail__logo" />);

    expect(screen.getByTestId("brand-mark").classList).toContain("rail__logo");
    expect(css).toContain("--brand-lead: #b8501e");
    expect(css).toContain("--brand-base: #277e99");
    expect(css).toContain("--brand-links: #66718d");
    expect(css).toMatch(/\.brand-mark\s*\{[^}]*filter: none;/s);
  });

  it("uses the brighter packaged-icon palette in the dark theme", () => {
    expect(css).toContain("--brand-lead: #ff8f52");
    expect(css).toContain("--brand-base: #6bc1d4");
    expect(css).toContain("--brand-links: #74809e");
  });
});
