import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ApprovalRecord } from "../state/reducer";

import { ApprovalDialog } from "./ApprovalDialog";

/**
 * The approval dialog.
 *
 * Two of CLAUDE.md's four warnings for this phase land here: the prompt must be
 * the one the log recorded rather than one the client composed, and the same
 * question can legitimately be asked more than once in a run.
 */

const pending: ApprovalRecord = {
  id: "ap-1",
  agent: "escaper",
  tool: "write_file",
  risk: "medium",
  prompt: 'Agent "escaper" wants to overwrite notes.txt (36 characters) — Allow / Deny',
  status: "pending",
  automatic: false,
  seq: 12,
};

const denied: ApprovalRecord = { ...pending, id: "ap-0", status: "denied", seq: 4 };

function dialog(approvals: ApprovalRecord[], onResolve = vi.fn().mockResolvedValue(undefined)) {
  render(<ApprovalDialog approvals={approvals} onResolve={onResolve} readOnly={false} />);
  return { onResolve };
}

describe("what it shows", () => {
  it("renders the sentence the backend put in the event", () => {
    /* Not composed from the arguments here. A dialog that built its own wording
       could describe a different call from the one about to run, and would put
       the UI's account of the run at odds with the log's. */
    dialog([pending]);

    expect(screen.getByTestId("approval-prompt").textContent).toBe(pending.prompt);
  });

  it("shows the risk level being decided", () => {
    dialog([pending]);

    expect(screen.getByTestId("approval-risk").textContent).toContain("medium");
  });

  it("names the agent that asked", () => {
    dialog([pending]);

    expect(screen.getByTestId("approval-dialog").textContent).toContain("escaper");
  });

  it("shows nothing at all when no approval is outstanding", () => {
    dialog([denied]);

    expect(screen.queryByTestId("approval-dialog")).toBeNull();
  });

  it("says a denial stops the call and not the run", () => {
    /* Watched live in Phase 6: the supervisor spawned a second worker and asked
       again. A user who does not know that reads a repeat question as a bug. */
    dialog([pending]);

    expect(screen.getByTestId("approval-dialog").textContent).toContain(
      "Denying stops this call, not the run",
    );
  });
});

describe("the history", () => {
  it("shows earlier decisions beside the current question", () => {
    dialog([denied, pending]);

    expect(screen.getByTestId("approval-history").textContent).toContain("denied");
  });

  it("says how many questions are still queued behind this one", () => {
    dialog([pending, { ...pending, id: "ap-2", seq: 14 }]);

    expect(screen.getByTestId("approval-dialog").textContent).toContain("1 more waiting");
  });

  it("marks a decision that a policy made rather than a person", () => {
    dialog([{ ...denied, status: "approved", automatic: true }, pending]);

    expect(screen.getByTestId("approval-history").textContent).toContain("by policy");
  });
});

describe("answering", () => {
  it("allows the outstanding call", async () => {
    const user = userEvent.setup();
    const { onResolve } = dialog([pending]);

    await user.click(screen.getByRole("button", { name: "Allow" }));

    expect(onResolve).toHaveBeenCalledWith("ap-1", true);
  });

  it("denies the outstanding call", async () => {
    const user = userEvent.setup();
    const { onResolve } = dialog([pending]);

    await user.click(screen.getByRole("button", { name: "Deny" }));

    expect(onResolve).toHaveBeenCalledWith("ap-1", false);
  });

  it("shows the reason when somebody else already answered", async () => {
    /* `POST /approvals/{id}` answers 409 for a settled approval, precisely so
       two windows showing the same dialog can explain the second click as
       "somebody already answered this" rather than as a broken request. */
    const user = userEvent.setup();
    const onResolve = vi
      .fn()
      .mockRejectedValue(new Error("approval ap-1 is already approved"));
    dialog([pending], onResolve);

    await user.click(screen.getByRole("button", { name: "Allow" }));

    expect(screen.getByRole("alert").textContent).toContain("already approved");
  });

  it("offers no buttons on a finished run", () => {
    render(<ApprovalDialog approvals={[pending]} onResolve={vi.fn()} readOnly />);

    expect(screen.queryByRole("button", { name: "Allow" })).toBeNull();
    expect(screen.getByTestId("approval-dialog").textContent).toContain("already finished");
  });
});
