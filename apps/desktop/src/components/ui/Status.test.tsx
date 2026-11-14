import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Status } from "./Status";

describe("Status", () => {
  it("gives every status its own glyph beside the word, hidden from a screen reader", () => {
    const kinds = ["pending", "running", "paused", "completed", "failed", "cancelled"];
    const glyphs = kinds.map((kind) => {
      const { container, unmount } = render(<Status kind={kind}>{kind}</Status>);
      const badge = container.querySelector(".status");
      const svg = badge?.querySelector("svg");
      expect(badge?.className).toBe(`status status--${kind}`);
      expect(badge?.textContent).toBe(kind);
      expect(svg?.getAttribute("aria-hidden")).toBe("true");
      const drawn = svg?.innerHTML ?? "";
      unmount();
      return drawn;
    });
    // Told apart without colour: no two statuses share a glyph.
    expect(new Set(glyphs).size).toBe(kinds.length);
  });

  it("reads a status this build does not know as waiting", () => {
    const { container } = render(<Status kind="queued">queued</Status>);
    expect(container.querySelector(".status")?.className).toBe("status status--pending");
  });
});
