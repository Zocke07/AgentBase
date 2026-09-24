import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MermaidDiagram } from "./MermaidDiagram";

const renderDiagram = vi.fn().mockResolvedValue({
  svg: '<svg xmlns="http://www.w3.org/2000/svg" onload="bad()"><script>bad()</script><foreignObject>bad</foreignObject><a href="https://example.com"><text>outside</text></a><text>safe</text></svg>',
});

vi.mock("mermaid", () => ({
  default: { initialize: vi.fn(), render: renderDiagram },
}));

describe("Mermaid diagrams", () => {
  it("sanitizes Mermaid SVG after strict rendering", async () => {
    render(<MermaidDiagram source="flowchart LR\nA --> B" title="Flow" />);
    const target = screen.getByTestId("mermaid-diagram");
    await waitFor(() => { expect(target.querySelector("svg")).not.toBeNull(); });
    expect(target.querySelector("script")).toBeNull();
    expect(target.querySelector("foreignObject")).toBeNull();
    expect(target.querySelector("svg")?.hasAttribute("onload")).toBe(false);
    expect(target.querySelector("a")?.hasAttribute("href")).toBe(false);
    expect(target.textContent).toContain("safe");
  });
});
