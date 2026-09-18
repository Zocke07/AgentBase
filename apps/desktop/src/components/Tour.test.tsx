import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TOUR_STEPS } from "../lib/tour";

import { Tour } from "./Tour";

/**
 * The first-run tour: it walks its steps in order, switches to the section
 * each step points into, can be skipped at any point and ends on the demo.
 * jsdom draws nothing, so the spotlight is checked by the target it finds
 * rather than by its geometry.
 */

function setup(open = true) {
  const onSection = vi.fn();
  const onClose = vi.fn();
  const onDemo = vi.fn(() => Promise.resolve());
  const view = render(
    <>
      <button type="button" data-tour="rail-runs">
        Runs
      </button>
      <div hidden>
        <textarea data-tour="goal" />
      </div>
      <Tour open={open} section="home" onSection={onSection} onClose={onClose} onDemo={onDemo} />
    </>,
  );
  return { ...view, onSection, onClose, onDemo };
}

describe("Tour", () => {
  it("renders nothing while closed", () => {
    setup(false);
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("walks the steps in order, switching to each step's section, and finishes", async () => {
    const { onSection, onClose } = setup();

    const card = screen.getByTestId("tour-card");
    expect(card.textContent).toContain(`1 of ${String(TOUR_STEPS.length)}`);
    expect(card.textContent).toContain(TOUR_STEPS[0]?.title ?? "");

    for (let index = 1; index < TOUR_STEPS.length; index += 1) {
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      expect(screen.getByTestId("tour-card").textContent).toContain(TOUR_STEPS[index]?.title ?? "");
    }
    // Every section a step names was asked for.
    for (const step of TOUR_STEPS) {
      if (step.section !== null && step.section !== "home") expect(onSection).toHaveBeenCalledWith(step.section);
    }

    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("can be skipped from any step, with Escape as well as the button", async () => {
    const { onClose } = setup();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("goes back a step with the button and the arrow keys", async () => {
    setup();

    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByTestId("tour-card").textContent).toContain("2 of");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByTestId("tour-card").textContent).toContain("1 of");
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByTestId("tour-card").textContent).toContain("1 of");
  });

  it("starts the demo run from the last step and closes once it has", async () => {
    const { onDemo, onClose } = setup();

    for (let index = 1; index < TOUR_STEPS.length; index += 1) {
      await userEvent.keyboard("{ArrowRight}");
    }
    await userEvent.click(screen.getByRole("button", { name: "Try a demo run" }));
    expect(onDemo).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the demo's failure rather than closing", async () => {
    const onClose = vi.fn();
    const failing = vi.fn(() => Promise.reject(new Error("sidecar refused")));
    render(<Tour open section="home" onSection={vi.fn()} onClose={onClose} onDemo={failing} />);

    for (let index = 1; index < TOUR_STEPS.length; index += 1) {
      await userEvent.keyboard("{ArrowRight}");
    }
    await userEvent.click(screen.getByRole("button", { name: "Try a demo run" }));
    expect((await screen.findByRole("alert")).textContent).toContain("sidecar refused");
    expect(onClose).not.toHaveBeenCalled();
  });
});
