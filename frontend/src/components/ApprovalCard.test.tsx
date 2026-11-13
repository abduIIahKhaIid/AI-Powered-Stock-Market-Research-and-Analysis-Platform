import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApprovalItem } from "../chat/types";
import ApprovalCard from "./ApprovalCard";

const item: ApprovalItem = {
  id: "a".repeat(32),
  tool: "run_python_analysis",
  arguments: { code: "print(6 * 7)" },
  reason: "Runs model-written Python code in the sandbox.",
  estimate: "Up to 30 s in the isolated sandbox. No cost.",
  status: "pending",
  expiresAt: 1_000_000 + 125_000,
};

afterEach(() => vi.useRealTimers());

describe("ApprovalCard", () => {
  it("shows the action, the reason, the time and cost, and sends the decision", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalCard item={item} sendDecision={send} now={() => 1_000_000} />);
    const card = screen.getByRole("region", { name: "Approval needed" });
    expect(card).toHaveAccessibleDescription("Runs model-written Python code in the sandbox.");
    expect(card).toHaveTextContent("ActionRun python analysis");
    expect(card).toHaveTextContent("Time and costUp to 30 s in the isolated sandbox. No cost.");
    expect(card).toHaveTextContent("2:05 left");
    expect(screen.getByRole("status")).toHaveTextContent("Approval needed: Run python analysis.");
    fireEvent.click(screen.getByRole("button", { name: "Approve: Run python analysis" }));
    expect(send).toHaveBeenCalledWith(item.id, "approve");
    expect(screen.getByRole("button", { name: "Deny: Run python analysis" })).toBeDisabled();
  });

  it("is usable from the keyboard", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalCard item={item} sendDecision={send} />);
    const deny = screen.getByRole("button", { name: /^Deny/ });
    deny.focus();
    expect(deny).toHaveFocus();
    // Native buttons: Enter and Space both activate them; the click is what React sees.
    fireEvent.click(deny);
    expect(send).toHaveBeenCalledWith(item.id, "deny");
  });

  it("counts down to the end of the wait", () => {
    vi.useFakeTimers();
    let clock = 1_000_000 + 120_000;
    render(<ApprovalCard item={item} now={() => clock} />);
    expect(screen.getByText("0:05 left")).toBeInTheDocument();
    clock += 6_000;
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("Time is up")).toBeInTheDocument();
  });

  it("shows an error and lets the user try again", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("This request is already expired."));
    render(<ApprovalCard item={item} sendDecision={send} />);
    fireEvent.click(screen.getByRole("button", { name: /^Deny/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already expired");
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeEnabled();
  });

  it("says when there is no estimate", () => {
    render(<ApprovalCard item={{ ...item, estimate: null }} />);
    expect(screen.getByText("No estimate for this action.")).toBeInTheDocument();
  });

  it("collapses to one line once decided", () => {
    render(<ApprovalCard item={{ ...item, status: "denied" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Denied");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
