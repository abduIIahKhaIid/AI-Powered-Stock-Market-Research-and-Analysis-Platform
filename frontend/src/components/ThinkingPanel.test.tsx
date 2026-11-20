import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { applyEvent, newAssistantMessage } from "../chat/reducer";
import type { AssistantMessage, ChatEvent } from "../chat/types";
import ThinkingPanel from "./ThinkingPanel";

function run(events: ChatEvent[]): AssistantMessage {
  return events.reduce(applyEvent, newAssistantMessage("a1", "simple"));
}

const working: ChatEvent[] = [
  { type: "status", data: { state: "thinking", step: 1 } },
  { type: "thinking", data: { text: "The user wants the latest ", step: 1 } },
  { type: "thinking", data: { text: "price, so get the quote.", step: 1 } },
  {
    type: "tool_call",
    data: { id: "c1", name: "get_quote", arguments: { symbol: "NVDA" }, step: 1 },
  },
];

const finished: ChatEvent[] = [
  ...working,
  {
    type: "tool_result",
    data: {
      id: "c1",
      name: "get_quote",
      ok: true,
      error: null,
      source: "Yahoo Finance (yfinance)",
      as_of: "2026-11-11",
      latency_ms: 300,
      preview: { symbol: "NVDA", price: 181.2 },
      step: 1,
    },
  },
  { type: "token", data: { text: "NVDA closed at 181.2 USD.", step: 2 } },
];

describe("reasoning in the reducer", () => {
  it("joins thinking text per model step and records how long the assistant thought", () => {
    const message = run([
      ...finished,
      { type: "thinking", data: { text: "Second step.", step: 2 } },
    ]);
    expect(message.thinking).toEqual([
      { step: 1, text: "The user wants the latest price, so get the quote." },
      { step: 2, text: "Second step." },
    ]);
    expect(message.answerStartedAt).toBeTypeOf("number");
    const done = applyEvent(message, {
      type: "done",
      data: {
        conversation_id: "c",
        answer: "NVDA closed at 181.2 USD.",
        disclaimer: "d",
        usage: {
          prompt_tokens: 0,
          completion_tokens: 0,
          cost_usd: 0,
          llm_calls: 2,
          tool_calls: 1,
          models: [],
          used_fallback: false,
        },
      },
    });
    expect(done.thoughtMs).toBeGreaterThanOrEqual(0);
  });

  it("clears the answer start when streamed text turns out to be a note before a tool", () => {
    const message = run([
      { type: "token", data: { text: "Let me check.", step: 1 } },
      {
        type: "tool_call",
        data: { id: "c1", name: "get_quote", arguments: { symbol: "NVDA" }, step: 1 },
      },
    ]);
    expect(message.answerStartedAt).toBeUndefined();
    expect(message.tools[0].note).toBe("Let me check.");
  });
});

describe("ThinkingPanel", () => {
  it("is open while the assistant works, with its reasoning and the running tool", () => {
    render(<ThinkingPanel message={run(working)} chainOfThought="full" />);
    const panel = screen.getByRole("region", { name: "Thinking" });
    expect(within(panel).getByRole("button", { expanded: true })).toHaveTextContent(
      "Latest quote…",
    );
    expect(panel).toHaveTextContent("The user wants the latest price, so get the quote.");
    expect(within(panel).getByRole("img", { name: "Running" })).toBeInTheDocument();
  });

  it("folds into a summary once the answer streams, and opens again on click", () => {
    render(<ThinkingPanel message={run(finished)} chainOfThought="full" />);
    const toggle = screen.getByRole("button", { name: /Thought for \d+s\s*·\s*used 1 tool/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/The user wants/)).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/The user wants the latest price/)).toBeInTheDocument();

    // A tool step opens to its input and output.
    fireEvent.click(screen.getByRole("button", { name: /Used Latest quote \(NVDA\)/ }));
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
  });

  it("shows only tool steps in the tools-only mode, and only a status line when hidden", () => {
    const { unmount } = render(<ThinkingPanel message={run(working)} chainOfThought="tool_call" />);
    expect(screen.queryByText(/The user wants/)).toBeNull();
    expect(screen.getByText("Latest quote")).toBeInTheDocument();
    unmount();

    render(<ThinkingPanel message={run(working)} chainOfThought="hidden" />);
    expect(screen.queryByRole("region", { name: "Thinking" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Latest quote…");
  });
});
