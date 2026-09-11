import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

/**
 * The boundary exists so that one bad payload is a message on screen and not
 * a blank window. React logs a caught render error to the console as well;
 * that is silenced here so a passing test does not read like a failing one.
 */

function Explodes({ when }: { when: boolean }) {
  if (when) throw new Error("payload had no seq");
  return <p>rendered fine</p>;
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("shows what threw instead of a blank page", () => {
    render(
      <ErrorBoundary label="the run view">
        <Explodes when />
      </ErrorBoundary>,
    );

    const fallback = screen.getByTestId("error-boundary");
    expect(fallback.textContent).toContain("the run view");
    expect(fallback.textContent).toContain("payload had no seq");
  });

  it("renders its children when nothing throws", () => {
    render(
      <ErrorBoundary label="the run view">
        <Explodes when={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("rendered fine")).toBeDefined();
    expect(screen.queryByTestId("error-boundary")).toBeNull();
  });

  it("remounts the subtree when asked to try again", async () => {
    /* A remount, not a re-render: the child's state starts over, so a subtree
       that threw because of what it held gets a clean start. */
    const user = userEvent.setup();
    let explode = true;
    function Sometimes() {
      return <Explodes when={explode} />;
    }
    render(
      <ErrorBoundary label="the run view">
        <Sometimes />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary")).toBeDefined();

    explode = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.getByText("rendered fine")).toBeDefined();
  });
});
