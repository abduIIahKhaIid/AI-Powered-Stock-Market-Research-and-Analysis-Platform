import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { applyEvent, newAssistantMessage } from "../chat/reducer";
import type { AssistantMessage } from "../chat/types";
import MessageView from "./MessageView";

afterEach(() => vi.unstubAllGlobals());

function richMessage(projection: boolean): AssistantMessage {
  return {
    ...newAssistantMessage("m1", "simple"),
    state: "done",
    text: "Base case value per share is 121.40 USD.",
    projection,
    tools: [
      { id: "t1", name: "run_scenario", arguments: { symbol: "AAPL" }, step: 1, status: "ok" },
    ],
    approvals: [
      {
        id: "a".repeat(32),
        tool: "start_job_scenario_sweep",
        arguments: { symbols: ["AAPL"] },
        reason: "Starts a background job that may take a while.",
        estimate: "8 scenarios, about 8–32 s. No cost.",
        status: "pending",
      },
    ],
    jobs: [
      {
        id: "b".repeat(32),
        kind: "scenario_sweep",
        title: "Scenario sweep",
        status: "running",
        progress: 25,
        stage: "Scenario 2 of 8",
      },
    ],
    sources: [{ source: "SEC EDGAR", as_of: "2026-11-13", tool: "run_scenario" }],
    disclaimer: "This is educational information, not financial advice.",
  };
}

describe("Accessibility and the projection banner", () => {
  it("shows the projection banner on projection answers only", () => {
    const { unmount } = render(<MessageView message={richMessage(true)} />);
    const banner = screen.getByRole("complementary", { name: "Projection disclaimer" });
    expect(banner).toHaveTextContent("Projection, not a prediction.");
    expect(banner).toHaveTextContent("not financial advice");
    unmount();
    render(<MessageView message={richMessage(false)} />);
    expect(screen.queryByRole("complementary", { name: "Projection disclaimer" })).toBeNull();
  });

  it("gives every button and progress bar an accessible name", () => {
    render(<MessageView message={richMessage(true)} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    for (const button of buttons) expect(button).toHaveAccessibleName();
    expect(screen.getByRole("button", { name: "Approve: Start job scenario sweep" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel Scenario sweep" })).toBeEnabled();
    expect(screen.getByRole("progressbar")).toHaveAccessibleName("Scenario sweep progress");
  });

  it("marks answers with a scenario chart as projections", () => {
    let message = newAssistantMessage("m", "simple");
    message = applyEvent(message, {
      type: "chart",
      data: {
        kind: "scenario",
        symbol: "AAPL",
        metric: "revenue",
        unit: "USD",
        base_year: 2024,
        base_value: 1,
        series: [],
        table: [],
      },
    });
    message = applyEvent(message, {
      type: "done",
      data: {
        conversation_id: "c",
        answer: "ok",
        disclaimer: "d",
        usage: {
          prompt_tokens: 0,
          completion_tokens: 0,
          cost_usd: 0,
          llm_calls: 1,
          tool_calls: 1,
          models: [],
          used_fallback: false,
        },
      },
    });
    expect(message.projection).toBe(true);
  });

  it("offers a skip link to the message box", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).includes("/api/analyses")
          ? Response.json([])
          : Response.json({ status: "ok", services: { api: "ok" } }),
      ),
    );
    render(<App />);
    const skip = screen.getByRole("link", { name: "Skip to the message box" });
    expect(skip).toHaveAttribute("href", "#chat-input");
    expect(document.getElementById("chat-input")).toHaveAccessibleName("Ask a question");
    for (const button of screen.getAllByRole("button")) expect(button).toHaveAccessibleName();
  });
});
