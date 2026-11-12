import { describe, expect, it } from "vitest";
import { applyEvent, finishMessage, newAssistantMessage } from "./reducer";
import { describeArguments, describePreview, toolLabel } from "./tools";
import type { AssistantMessage, ChatEvent } from "./types";

function run(events: ChatEvent[]): AssistantMessage {
  return events.reduce(applyEvent, newAssistantMessage("a1", "simple"));
}

const toolCall: ChatEvent = {
  type: "tool_call",
  data: { id: "c1", name: "get_quote", arguments: { symbol: "NVDA" }, step: 1 },
};
const toolResult: ChatEvent = {
  type: "tool_result",
  data: {
    id: "c1",
    name: "get_quote",
    ok: true,
    error: null,
    source: "Yahoo Finance (yfinance)",
    as_of: "2026-11-11",
    latency_ms: 412,
    preview: { symbol: "NVDA", price: 181.2 },
    step: 1,
  },
};

describe("applyEvent", () => {
  it("streams tokens and moves pre-tool text into the timeline", () => {
    const message = run([
      { type: "status", data: { state: "thinking", step: 1 } },
      { type: "token", data: { text: "Let me check ", step: 1 } },
      { type: "token", data: { text: "the price.", step: 1 } },
      toolCall,
      toolResult,
      { type: "token", data: { text: "NVDA closed at 181.2.", step: 2 } },
    ]);

    expect(message.text).toBe("NVDA closed at 181.2.");
    expect(message.tools).toHaveLength(1);
    expect(message.tools[0]).toMatchObject({
      note: "Let me check the price.",
      status: "ok",
      source: "Yahoo Finance (yfinance)",
      asOf: "2026-11-11",
      latencyMs: 412,
    });
    expect(message.state).toBe("streaming");
  });

  it("uses the final answer and disclaimer from the done event", () => {
    const message = run([
      { type: "token", data: { text: "partial", step: 1 } },
      { type: "sources", data: { sources: [{ source: "SEC", as_of: null, tool: "x" }] } },
      {
        type: "done",
        data: {
          conversation_id: "c",
          answer: "Full answer",
          disclaimer: "Not financial advice.",
          usage: {
            prompt_tokens: 1,
            completion_tokens: 1,
            cost_usd: 0,
            llm_calls: 1,
            tool_calls: 0,
            models: ["ollama/qwen3:8b"],
            used_fallback: false,
          },
        },
      },
    ]);
    expect(message).toMatchObject({
      state: "done",
      text: "Full answer",
      disclaimer: "Not financial advice.",
    });
    expect(message.sources).toHaveLength(1);
  });

  it("records error events and failed tools", () => {
    const failed = run([
      toolCall,
      { ...toolResult, data: { ...toolResult.data, ok: false, error: "Not NASDAQ-listed" } },
      { type: "error", data: { code: "llm_unavailable", message: "Model offline" } },
    ] as ChatEvent[]);
    expect(failed.tools[0]).toMatchObject({ status: "error", error: "Not NASDAQ-listed" });
    expect(failed).toMatchObject({ state: "error", error: { code: "llm_unavailable" } });
  });

  it("closes a message that was stopped mid-stream", () => {
    const stopped = finishMessage(run([toolCall]), "stopped");
    expect(stopped.state).toBe("stopped");
    expect(stopped.tools[0].status).toBe("cancelled");
    // A finished message is left alone.
    const done = run([{ type: "error", data: { code: "x", message: "y" } }]);
    expect(finishMessage(done, "stopped")).toBe(done);
  });
});

describe("tool helpers", () => {
  it("labels and summarises tools", () => {
    expect(toolLabel("get_price_history")).toBe("Price history");
    expect(toolLabel("get_financial_statements")).toBe("Get financial statements");
    expect(describeArguments({ symbol: "AAPL", period: "1mo", extra: { a: 1 } })).toBe(
      "AAPL · 1mo",
    );
    expect(describePreview({ symbol: "AAPL", counts: { candles: 21 } })).toBe(
      "symbol: AAPL · 21 candles",
    );
    expect(describePreview({ count: 2, first: [{ symbol: "AAPL" }, { symbol: "AAPD" }] })).toBe(
      "2 results: AAPL, AAPD",
    );
  });
});

describe("grounding events", () => {
  it("shows a checking status while figures are corrected, then stores the report", () => {
    const fixing = run([
      toolCall,
      toolResult,
      { type: "token", data: { text: "NVDA rose 9.9%.", step: 2 } },
      { type: "grounding", data: { state: "fixing", attempt: 1, unverified: ["9.9%"] } },
    ]);
    expect(fixing.statusText).toBe("Checking the figures against the data…");

    const done = applyEvent(
      applyEvent(fixing, { type: "token", data: { text: "NVDA rose 2.0%.", step: 3 } }),
      {
        type: "done",
        data: {
          conversation_id: "c",
          answer: "NVDA rose 2.0%.",
          disclaimer: "Educational only.",
          assumptions: ["Growth 5% a year"],
          grounding: { status: "corrected", checked: 1, attempts: 1, flagged: ["9.9%"] },
          usage: {
            prompt_tokens: 1,
            completion_tokens: 1,
            cost_usd: 0,
            llm_calls: 3,
            tool_calls: 1,
            models: ["m"],
            used_fallback: false,
          },
        },
      },
    );
    expect(done.text).toBe("NVDA rose 2.0%.");
    expect(done.assumptions).toEqual(["Growth 5% a year"]);
    expect(done.grounding?.status).toBe("corrected");
  });
});

describe("chart events", () => {
  it("keeps one chart per symbol, the latest one", () => {
    const chart = {
      kind: "price" as const,
      symbol: "AAPL",
      period: "1mo",
      interval: "1d",
      adjusted: false,
      candles: [],
    };
    const message = run([
      { type: "chart", data: chart },
      { type: "chart", data: { ...chart, symbol: "MSFT" } },
      { type: "chart", data: { ...chart, period: "6mo" } },
    ]);
    expect(message.charts?.map((c) => `${c.symbol}:${c.period}`)).toEqual(["MSFT:1mo", "AAPL:6mo"]);
  });
});
