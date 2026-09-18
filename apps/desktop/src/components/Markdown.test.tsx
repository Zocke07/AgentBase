import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("follows a wikilink with its heading and filters on a tag", async () => {
    const user = userEvent.setup();
    const onLink = vi.fn();
    const onTag = vi.fn();
    render(<Markdown source="See [[decisions/storage#Choice|the choice]] #architecture" onLink={onLink} onTag={onTag} />);

    await user.click(screen.getByRole("button", { name: "the choice" }));
    await user.click(screen.getByRole("button", { name: "#architecture" }));

    expect(onLink).toHaveBeenCalledWith("decisions/storage", "Choice");
    expect(onTag).toHaveBeenCalledWith("architecture");
  });

  it("renders links and tags as plain text when nothing handles them", () => {
    render(<Markdown source="[[note]] #tag" />);

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("note").className).toContain("md__wikilink");
    expect(screen.getByText("#tag").className).toContain("md__tag");
  });

  it("writes a ticked task back by its source line, and is read-only without a handler", async () => {
    const user = userEvent.setup();
    const onToggleTask = vi.fn();
    const source = "---\ntags: [a]\n---\n- [ ] first\n- [x] second";
    const { rerender } = render(<Markdown source={source} onToggleTask={onToggleTask} />);

    await user.click(screen.getByRole("checkbox", { name: "Mark as done" }));
    expect(onToggleTask).toHaveBeenCalledWith(3, true);

    rerender(<Markdown source={source} />);
    expect(screen.getByRole("checkbox", { name: "Mark as done" })).toHaveProperty("disabled", true);
  });

  it("shows frontmatter as a properties panel when asked, with tags as chips", () => {
    render(<Markdown source={"---\nstatus: accepted\ntags: [a, b]\n---\nBody"} properties />);

    const panel = screen.getByLabelText("Properties");
    expect(panel.textContent).toContain("status");
    expect(panel.textContent).toContain("accepted");
    expect(panel.querySelectorAll(".md__tag")).toHaveLength(2);
  });

  it("renders a callout with its family and folds a collapsed one", () => {
    const { container } = render(<Markdown source={"> [!tip]- Title\n> Body\n\n> [!danger]\n> Careful"} />);

    const folded = container.querySelector("details.md__callout--tip");
    expect(folded).not.toBeNull();
    expect(folded).toHaveProperty("open", false);
    expect(container.querySelector(".md__callout--danger .md__callout-title")?.textContent).toBe("Danger");
  });

  it("never turns note text into markup", () => {
    const { container } = render(<Markdown source={'<script>alert(1)</script> <img src=x onerror="x">'} />);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  it("only links to http, https and mailto addresses", () => {
    render(<Markdown source="[ok](https://example.test) [bad](javascript:alert(1))" />);

    expect(screen.getByRole("link", { name: "ok" })).toHaveProperty("href", "https://example.test/");
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
  });
});
