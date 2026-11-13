import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MenuButton, type MenuItem } from "./Menu";
import { Popover } from "./Popover";
import { Sheet } from "./Sheet";
import { IconButton, Segmented, Switch } from "./controls";

function PopoverHarness({ onClosed }: { onClosed?: (reason: string) => void }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={() => {
          setOpen((was) => !was);
        }}
      >
        Details
      </button>
      <button type="button">Elsewhere</button>
      <Popover
        open={open}
        onClose={(reason) => {
          onClosed?.(reason);
          setOpen(false);
        }}
        anchor={button}
        role="dialog"
        label="Details"
        focus="first"
      >
        <button type="button">Inside</button>
      </Popover>
    </>
  );
}

describe("Popover", () => {
  it("renders nothing until it is open, then moves focus into the panel", async () => {
    const user = userEvent.setup();
    render(<PopoverHarness />);
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Details" }));
    const panel = screen.getByRole("dialog", { name: "Details" });
    expect(panel.className).toContain("popover");
    expect(document.activeElement).toBe(within(panel).getByRole("button", { name: "Inside" }));
  });

  it("is outside the tree it was opened from, so nothing can clip it", async () => {
    const user = userEvent.setup();
    const { container } = render(<PopoverHarness />);
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(container.contains(screen.getByRole("dialog"))).toBe(false);
    expect(document.body.contains(screen.getByRole("dialog"))).toBe(true);
  });

  it("closes on Escape and gives focus back to its anchor", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<PopoverHarness onClosed={onClosed} />);
    await user.click(screen.getByRole("button", { name: "Details" }));

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onClosed).toHaveBeenCalledWith("escape");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Details" }));
  });

  it("closes on a press outside, and leaves focus where the press put it", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<PopoverHarness onClosed={onClosed} />);
    await user.click(screen.getByRole("button", { name: "Details" }));

    await user.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onClosed).toHaveBeenCalledWith("outside");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Elsewhere" }));
  });

  it("does not treat a press on its anchor or inside it as outside", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<PopoverHarness onClosed={onClosed} />);
    await user.click(screen.getByRole("button", { name: "Details" }));
    await user.click(screen.getByRole("button", { name: "Inside" }));
    expect(onClosed).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeDefined();

    // The anchor toggles it itself.
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(onClosed).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Popover, at the edges", () => {
  it("closes when Tab leaves its last control, and gives focus back to its anchor", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    render(<PopoverHarness onClosed={onClosed} />);
    const anchor = screen.getByRole("button", { name: "Details" });
    await user.click(anchor);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Inside" }));

    // The panel is at the end of the document: Tab must not wander off it.
    await user.tab();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onClosed).toHaveBeenCalledWith("tab");
    expect(document.activeElement).toBe(anchor);
  });

  it("closes the same way when Shift+Tab leaves its first control", async () => {
    const user = userEvent.setup();
    render(<PopoverHarness />);
    const anchor = screen.getByRole("button", { name: "Details" });
    await user.click(anchor);
    await user.tab({ shift: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(anchor);
  });

  it("takes focus itself when the element it was told to focus cannot", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      const button = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button
            ref={button}
            type="button"
            onClick={() => {
              setOpen(true);
            }}
          >
            Open
          </button>
          <Popover
            open={open}
            onClose={() => {
              setOpen(false);
            }}
            anchor={button}
            role="dialog"
            label="Panel"
            focus={(panel) => panel.querySelector<HTMLElement>("[data-nowhere]")}
          >
            {/* Not focusable: a plain span. */}
            <span data-nowhere>Text</span>
          </Popover>
        </>
      );
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(document.activeElement).toBe(screen.getByRole("dialog", { name: "Panel" }));
  });

  it("closes when the section it was opened from is hidden under it", async () => {
    const user = userEvent.setup();
    const onClosed = vi.fn();
    const { container } = render(
      <section>
        <PopoverHarness onClosed={onClosed} />
      </section>,
    );
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByRole("dialog")).toBeDefined();

    // Every section stays mounted behind `hidden`; the panel is outside it.
    const section = container.querySelector("section");
    if (section === null) throw new Error("no section");
    section.hidden = true;
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(onClosed).toHaveBeenCalledWith("outside");
  });
});

function menuItems(spy: (id: string) => void): MenuItem[] {
  return [
    { id: "rename", label: "Rename", onSelect: () => { spy("rename"); } },
    { id: "move", label: "Move to folder", shortcut: "Ctrl+M", onSelect: () => { spy("move"); } },
    { id: "merge", label: "Merge", disabled: true, onSelect: () => { spy("merge"); } },
    { id: "line", separator: true },
    { id: "delete", label: "Delete", danger: true, onSelect: () => { spy("delete"); } },
  ];
}

describe("Menu", () => {
  it("opens from its button with focus on the first row, and names itself", async () => {
    const user = userEvent.setup();
    render(<MenuButton label="Note actions" items={menuItems(vi.fn())} />);
    const button = screen.getByRole("button", { name: "Note actions" });
    expect(button.getAttribute("aria-haspopup")).toBe("menu");
    expect(button.getAttribute("aria-expanded")).toBe("false");

    await user.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("menu", { name: "Note actions" });
    expect(within(menu).getAllByRole("menuitem")).toHaveLength(4);
    expect(within(menu).getAllByRole("separator")).toHaveLength(1);
    expect(document.activeElement).toBe(within(menu).getByRole("menuitem", { name: "Rename" }));
  });

  it("moves through its rows with the arrow keys, Home and End, wrapping at the ends", async () => {
    const user = userEvent.setup();
    render(<MenuButton label="Note actions" items={menuItems(vi.fn())} />);
    await user.click(screen.getByRole("button", { name: "Note actions" }));
    const focused = () => document.activeElement?.textContent;

    await user.keyboard("{ArrowDown}");
    expect(focused()).toContain("Move to folder");
    await user.keyboard("{End}");
    expect(focused()).toBe("Delete");
    await user.keyboard("{ArrowDown}");
    expect(focused()).toBe("Rename");
    await user.keyboard("{ArrowUp}");
    expect(focused()).toBe("Delete");
    await user.keyboard("{Home}");
    expect(focused()).toBe("Rename");
  });

  it("jumps to a row by its first letters", async () => {
    const user = userEvent.setup();
    render(<MenuButton label="Note actions" items={menuItems(vi.fn())} />);
    await user.click(screen.getByRole("button", { name: "Note actions" }));

    await user.keyboard("d");
    expect(document.activeElement?.textContent).toBe("Delete");
  });

  it("reads letters typed together as one search", async () => {
    const user = userEvent.setup();
    render(<MenuButton label="Note actions" items={menuItems(vi.fn())} />);
    await user.click(screen.getByRole("button", { name: "Note actions" }));

    // "m" alone is Move to folder; "me" passes it for Merge.
    await user.keyboard("me");
    expect(document.activeElement?.textContent).toBe("Merge");
  });

  it("chooses with Enter, closes, and gives focus back to its button", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    render(<MenuButton label="Note actions" items={menuItems(chosen)} />);
    const button = screen.getByRole("button", { name: "Note actions" });
    await user.click(button);

    await user.keyboard("{ArrowDown}{Enter}");
    expect(chosen).toHaveBeenCalledExactlyOnceWith("move");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("announces a disabled row and does nothing when it is chosen", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    render(<MenuButton label="Note actions" items={menuItems(chosen)} />);
    await user.click(screen.getByRole("button", { name: "Note actions" }));

    const merge = screen.getByRole("menuitem", { name: "Merge" });
    expect(merge.getAttribute("aria-disabled")).toBe("true");
    await user.click(merge);
    expect(chosen).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeDefined();
  });

  it("closes on Escape and on Tab without choosing", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    render(<MenuButton label="Note actions" items={menuItems(chosen)} />);
    const button = screen.getByRole("button", { name: "Note actions" });

    await user.click(button);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menu")).toBeDefined();
    await user.keyboard("{Tab}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(button);
    expect(chosen).not.toHaveBeenCalled();
  });

  it("ticks the chosen row of a set of choices and starts on it", async () => {
    const user = userEvent.setup();
    const items: MenuItem[] = [
      { id: "name", label: "Name", checked: false, onSelect: vi.fn() },
      { id: "date", label: "Date", checked: true, onSelect: vi.fn() },
    ];
    render(<MenuButton label="Sort by" items={items} />);
    await user.click(screen.getByRole("button", { name: "Sort by" }));

    const date = screen.getByRole("menuitemradio", { name: "Date" });
    expect(date.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("menuitemradio", { name: "Name" }).getAttribute("aria-checked")).toBe("false");
    expect(document.activeElement).toBe(date);
  });
});

function SheetHarness({ blocking = false }: { blocking?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        Open
      </button>
      <Sheet
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title="Delete this run?"
        blocking={blocking}
        footer={
          <button
            type="button"
            onClick={() => {
              setOpen(false);
            }}
          >
            Keep it
          </button>
        }
      >
        <input aria-label="Reason" />
      </Sheet>
    </>
  );
}

describe("Sheet", () => {
  it("is a modal dialog named by its title, with focus inside", async () => {
    const user = userEvent.setup();
    render(<SheetHarness />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    const sheet = screen.getByRole("dialog", { name: "Delete this run?" });
    expect(sheet.getAttribute("aria-modal")).toBe("true");
    expect(sheet.contains(document.activeElement)).toBe(true);
  });

  it("keeps Tab inside itself, in both directions", async () => {
    const user = userEvent.setup();
    render(<SheetHarness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    const sheet = screen.getByRole("dialog");
    const stops = [
      within(sheet).getByRole("button", { name: "Close" }),
      within(sheet).getByLabelText("Reason"),
      within(sheet).getByRole("button", { name: "Keep it" }),
    ];

    expect(document.activeElement).toBe(stops[0]);
    await user.tab();
    await user.tab();
    expect(document.activeElement).toBe(stops[2]);
    await user.tab();
    expect(document.activeElement).toBe(stops[0]);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(stops[2]);
  });

  it("closes on Escape and on its close button, and returns focus to where it was", async () => {
    const user = userEvent.setup();
    render(<SheetHarness />);
    const opener = screen.getByRole("button", { name: "Open" });

    await user.click(opener);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);

    await user.click(opener);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("closes on a press on the dimmed area, not on a press inside", async () => {
    const user = userEvent.setup();
    render(<SheetHarness />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    await user.click(screen.getByLabelText("Reason"));
    expect(screen.getByRole("dialog")).toBeDefined();
    const scrim = screen.getByRole("dialog").parentElement;
    if (scrim === null) throw new Error("the sheet has no scrim");
    await user.click(scrim);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays open while it is blocking: no Escape, no press outside, no close button", async () => {
    const user = userEvent.setup();
    render(<SheetHarness blocking />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    await user.keyboard("{Escape}");
    const scrim = screen.getByRole("dialog").parentElement;
    if (scrim === null) throw new Error("the sheet has no scrim");
    await user.click(scrim);
    expect(screen.getByRole("dialog")).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes when the section it was opened from is hidden under it", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <section>
        <SheetHarness />
      </section>,
    );
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("dialog")).toBeDefined();

    const section = container.querySelector("section");
    if (section === null) throw new Error("no section");
    section.hidden = true;
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("leaves Escape to a menu opened from inside it", async () => {
    const user = userEvent.setup();
    function Nested() {
      const [open, setOpen] = useState(true);
      return (
        <Sheet
          open={open}
          onClose={() => {
            setOpen(false);
          }}
          title="Note"
        >
          <MenuButton label="More" items={[{ id: "a", label: "Archive", onSelect: vi.fn() }]} />
        </Sheet>
      );
    }
    render(<Nested />);
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menu")).toBeDefined();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Note" })).toBeDefined();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("the small controls", () => {
  it("names an icon button, and says when it is pressed", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<IconButton icon="search" label="Open a note" title="Open a note (Ctrl+O)" pressed onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Open a note" });
    expect(button.getAttribute("title")).toBe("Open a note (Ctrl+O)");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    await user.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("flips a switch by click and by keyboard, and reports its state", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [on, setOn] = useState(false);
      return <Switch checked={on} onChange={setOn} label="Reduce transparency" />;
    }
    render(<Harness />);
    const control = screen.getByRole("switch", { name: "Reduce transparency" });
    expect(control.getAttribute("aria-checked")).toBe("false");
    await user.click(control);
    expect(control.getAttribute("aria-checked")).toBe("true");
    control.focus();
    await user.keyboard(" ");
    expect(control.getAttribute("aria-checked")).toBe("false");
  });

  it("offers one choice among segments, moved by the arrow keys", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [value, setValue] = useState<"system" | "light" | "dark">("light");
      return (
        <Segmented
          label="Theme"
          value={value}
          onChange={setValue}
          options={[
            { value: "system", label: "Follow the system" },
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      );
    }
    render(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "Theme" });
    const checked = () => within(group).getByRole("radio", { checked: true }).textContent;
    expect(checked()).toBe("Light");
    // Tab reaches the chosen segment only.
    expect(within(group).getAllByRole("radio").map((radio) => radio.tabIndex)).toEqual([-1, 0, -1]);

    await user.click(within(group).getByRole("radio", { name: "Dark" }));
    expect(checked()).toBe("Dark");
    await user.keyboard("{ArrowRight}");
    expect(checked()).toBe("Follow the system");
    expect(document.activeElement?.textContent).toBe("Follow the system");
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(checked()).toBe("Light");
    await user.keyboard("{Home}");
    expect(checked()).toBe("Follow the system");
  });
});
