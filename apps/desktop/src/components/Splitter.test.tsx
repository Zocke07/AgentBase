import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Splitter } from "./Splitter";

describe("Splitter", () => {
  it("drags a size from where it was, clamped to the bounds", () => {
    const onChange = vi.fn();
    render(
      <Splitter axis="x" side="end" value={null} measure={() => 300} min={200} max={() => 500} onChange={onChange} label="Resize the run list" />,
    );
    const handle = screen.getByRole("separator", { name: "Resize the run list" });

    fireEvent.pointerDown(handle, { clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 140, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith(340);

    fireEvent.pointerMove(handle, { clientX: 900, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith(500);

    fireEvent.pointerUp(handle, { clientX: 900, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 100, pointerId: 1 });
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("grows the other way from a handle on the panel's start edge", () => {
    const onChange = vi.fn();
    render(
      <Splitter axis="x" side="start" value={336} measure={() => 336} min={240} max={() => 800} onChange={onChange} label="Resize the agent detail" />,
    );
    const handle = screen.getByRole("separator", { name: "Resize the agent detail" });

    fireEvent.pointerDown(handle, { clientX: 500, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 450, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith(386);
  });

  it("steps with the arrow keys and resets to the stylesheet's size", () => {
    const onChange = vi.fn();
    render(
      <Splitter axis="y" side="end" value={320} measure={() => 320} min={160} max={() => 900} onChange={onChange} label="Resize the canvas" />,
    );
    const handle = screen.getByRole("separator", { name: "Resize the canvas" });

    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith(344);
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith(296);
    fireEvent.keyDown(handle, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith(null);
    fireEvent.doubleClick(handle);
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(handle.getAttribute("aria-orientation")).toBe("horizontal");
  });
});
