import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ApprovalRecord } from "../state/reducer";

import { ApprovalPanel } from "./ApprovalPanel";

/**
 * The approval panel.
 *
 * Two of CLAUDE.md's four warnings for this phase land here: the prompt must be
 * the one the log recorded rather than one the client composed, and the same
 * question can legitimately be asked more than once in a run. A third arrived
 * later: whether a question can be *answered* is about where the viewer is
 * standing, not about the log, and getting that wrong trapped a user behind a
 * backdrop on a finished run.
 */

const pending: ApprovalRecord = {
  id: "ap-1",
  agent: "escaper",
  tool: "write_file",
  risk: "medium",
  prompt: 'Agent "escaper" wants to overwrite notes.txt (36 characters): Allow / Deny',
  status: "pending",
  automatic: false,
  precedent: false,
  policy: false,
  scope: "call",
  seq: 12,
};

const denied: ApprovalRecord = { ...pending, id: "ap-0", status: "denied", seq: 4 };

function panel(
  approvals: ApprovalRecord[],
  onResolve = vi.fn().mockResolvedValue(undefined),
  readOnly: "finished" | "replay" | null = null,
) {
  render(<ApprovalPanel approvals={approvals} onResolve={onResolve} readOnly={readOnly} />);
  return { onResolve };
}

describe("what it shows", () => {
  it("renders the sentence the backend put in the event", () => {
    /* Not composed from the arguments here. A panel that built its own wording
       could describe a different call from the one about to run, and would put
       the UI's account of the run at odds with the log's. */
    panel([pending]);

    expect(screen.getByTestId("approval-prompt").textContent).toBe(pending.prompt);
  });

  it("shows the risk level being decided", () => {
    panel([pending]);

    expect(screen.getByTestId("approval-risk").textContent).toContain("medium");
  });

  it("names the agent that asked", () => {
    panel([pending]);

    expect(screen.getByTestId("approval-panel").textContent).toContain("escaper");
  });

  it("shows nothing at all when no approval is outstanding", () => {
    panel([denied]);

    expect(screen.queryByTestId("approval-panel")).toBeNull();
  });

  it("does not ask about a call the policy already allowed", () => {
    /* The gate writes `approval.requested {automatic: true}` and then, as a
       separate event, its resolution. Between the two the record is pending in
       the log and nobody is waiting on anybody. */
    panel([{ ...pending, automatic: true }]);

    expect(screen.queryByTestId("approval-panel")).toBeNull();
  });

  it("is not a modal: nothing covers the rest of the page", () => {
    /* The first version had a fixed backdrop over the whole window. Dragging
       the replay slider into an approval span of a finished run then left the
       slider, the run list and the tabs all behind it. */
    const { container } = render(
      <ApprovalPanel approvals={[pending]} onResolve={vi.fn()} readOnly={null} />,
    );

    expect(container.querySelector(".modal-backdrop")).toBeNull();
    expect(screen.getByTestId("approval-panel").getAttribute("aria-modal")).toBeNull();
  });

  it("says a denial stops the call and not the run", () => {
    /* Watched live in Phase 6: the supervisor spawned a second worker and asked
       again. A user who does not know that reads a repeat question as a bug. */
    panel([pending]);

    expect(screen.getByTestId("approval-panel").textContent).toContain(
      "Denying stops this call, not the run",
    );
  });
});

describe("the history", () => {
  it("shows earlier decisions beside the current question", () => {
    panel([denied, pending]);

    expect(screen.getByTestId("approval-history").textContent).toContain("denied");
  });

  it("says how many questions are still queued behind this one", () => {
    panel([pending, { ...pending, id: "ap-2", seq: 14 }]);

    expect(screen.getByTestId("approval-panel").textContent).toContain("1 more waiting");
  });

  it("marks a decision that a policy made rather than a person", () => {
    panel([{ ...denied, status: "approved", automatic: true }, pending]);

    expect(screen.getByTestId("approval-history").textContent).toContain("by policy");
  });

  it("marks a repeat the person's earlier answer settled, not a policy", () => {
    panel([denied, { ...denied, id: "ap-1b", seq: 9, automatic: true, precedent: true }, pending]);

    const history = screen.getByTestId("approval-history").textContent;
    expect(history).toContain("by your earlier answer");
    expect(history).not.toContain("by policy");
  });

  it("marks a refusal the policy made, and a yes given for the run", () => {
    panel([
      { ...denied, id: "ap-p", seq: 3, automatic: true, policy: true },
      { ...denied, id: "ap-r", seq: 5, status: "approved", scope: "run" },
      pending,
    ]);

    const history = screen.getByTestId("approval-history").textContent;
    expect(history).toContain("by policy");
    expect(history).toContain("for the rest of the run");
  });
});

describe("answering", () => {
  it("allows the outstanding call", async () => {
    const user = userEvent.setup();
    const { onResolve } = panel([pending]);

    await user.click(screen.getByRole("button", { name: "Allow" }));

    expect(onResolve).toHaveBeenCalledWith("ap-1", true, "call");
  });

  it("denies the outstanding call", async () => {
    const user = userEvent.setup();
    const { onResolve } = panel([pending]);

    await user.click(screen.getByRole("button", { name: "Deny" }));

    expect(onResolve).toHaveBeenCalledWith("ap-1", false, "call");
  });

  it("can allow the tool for the rest of the run", async () => {
    const user = userEvent.setup();
    const { onResolve } = panel([pending]);

    await user.click(screen.getByRole("button", { name: "Allow for this run" }));

    expect(onResolve).toHaveBeenCalledWith("ap-1", true, "run");
    expect(screen.getByText(/every later write_file call in this run/).textContent).toContain("Settings");
  });

  it("focuses Deny when a question appears", () => {
    /* The safer answer gets the focus, so a keyboard user is not left in the
       goal box behind the question and Enter does not silently allow. */
    panel([pending]);

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Deny" }));
  });

  it("shows the reason when somebody else already answered", async () => {
    /* `POST /approvals/{id}` answers 409 for a settled approval, precisely so
       two windows showing the same question can explain the second click as
       "somebody already answered this" rather than as a broken request. */
    const user = userEvent.setup();
    const onResolve = vi
      .fn()
      .mockRejectedValue(new Error("approval ap-1 is already approved"));
    panel([pending], onResolve);

    await user.click(screen.getByRole("button", { name: "Allow" }));

    expect(screen.getByRole("alert").textContent).toContain("already approved");
  });

  it("offers no buttons on a finished run", () => {
    panel([pending], vi.fn(), "finished");

    expect(screen.queryByRole("button", { name: "Allow" })).toBeNull();
    expect(screen.getByTestId("approval-panel").textContent).toContain("already finished");
  });

  it("offers no buttons when the viewer has scrubbed back from the head", () => {
    /* At this position the question is pending *in the fold*, and the run may
       even still be live, but the answer is given at the head, and this is
       not the head. The old dialog rendered live buttons here and a click got
       a 409. */
    panel([pending], vi.fn(), "replay");

    expect(screen.queryByRole("button", { name: "Allow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deny" })).toBeNull();
    expect(screen.getByTestId("approval-panel").textContent).toContain("earlier point");
  });
});
