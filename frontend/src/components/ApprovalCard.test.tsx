import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApprovalItem } from "../chat/types";
import ApprovalCard from "./ApprovalCard";

const item: ApprovalItem = {
  id: "a".repeat(32),
  tool: "run_python_analysis",
  arguments: { code: "print(6 * 7)" },
  reason: "Runs model-written Python code in the sandbox.",
  estimate: "about 30 seconds",
  status: "pending",
};

describe("ApprovalCard", () => {
  it("shows the reason and sends the decision", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalCard item={item} sendDecision={send} />);
    expect(screen.getByText(/Runs model-written Python/)).toBeInTheDocument();
    expect(screen.getByText("Estimate: about 30 seconds")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run it" }));
    expect(send).toHaveBeenCalledWith(item.id, "approve");
    expect(screen.getByRole("button", { name: "Don't run" })).toBeDisabled();
  });

  it("shows an error and lets the user try again", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("This request is already expired."));
    render(<ApprovalCard item={item} sendDecision={send} />);
    fireEvent.click(screen.getByRole("button", { name: "Don't run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already expired");
    expect(screen.getByRole("button", { name: "Run it" })).toBeEnabled();
  });

  it("collapses to one line once decided", () => {
    render(<ApprovalCard item={{ ...item, status: "denied" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Not run");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
