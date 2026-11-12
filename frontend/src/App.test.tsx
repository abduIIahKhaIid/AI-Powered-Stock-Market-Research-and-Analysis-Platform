import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

type Sent = { message: string; mode: string; conversation_id: string | null };

function sse(events: [string, unknown][]): string {
  return events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

const HEALTH = {
  status: "ok",
  version: "0.1.0",
  environment: "test",
  services: { api: "ok", postgres: "ok", redis: "ok", mcp_server: "ok" },
};

const ANSWER_EVENTS: [string, unknown][] = [
  ["conversation", { conversation_id: "c".repeat(32), mode: "simple" }],
  ["status", { state: "thinking", step: 1 }],
  ["tool_call", { id: "t1", name: "get_quote", arguments: { symbol: "AAPL" }, step: 1 }],
  [
    "tool_result",
    {
      id: "t1",
      name: "get_quote",
      ok: true,
      error: null,
      source: "Yahoo Finance (yfinance)",
      as_of: "2026-11-11",
      latency_ms: 230,
      preview: { symbol: "AAPL", price: 231.5 },
      step: 1,
    },
  ],
  ["status", { state: "thinking", step: 2 }],
  ["token", { text: "Apple last closed at ", step: 2 }],
  ["token", { text: "**231.5 USD**.", step: 2 }],
  [
    "sources",
    { sources: [{ source: "Yahoo Finance (yfinance)", as_of: "2026-11-11", tool: "get_quote" }] },
  ],
  [
    "done",
    {
      conversation_id: "c".repeat(32),
      answer: "Apple last closed at **231.5 USD**.",
      disclaimer: "This is educational information, not financial advice.",
      tools: [],
      usage: {
        prompt_tokens: 10,
        completion_tokens: 5,
        cost_usd: 0,
        llm_calls: 2,
        tool_calls: 1,
        models: ["ollama/qwen3:8b"],
        used_fallback: false,
      },
    },
  ],
];

/** Fake API: /api/health answers JSON, /api/chat streams the given events. */
function mockApi(chatReplies: (string | Response)[]) {
  const sent: Sent[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/health")) return Response.json(HEALTH);
    if (url.includes("/api/analyses")) return Response.json([]);
    sent.push(JSON.parse(String(init?.body)) as Sent);
    const reply = chatReplies.shift() ?? "";
    if (reply instanceof Response) return reply;
    return new Response(reply, { headers: { "Content-Type": "text/event-stream" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return sent;
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("Chat screen", () => {
  it("shows starter prompts, the mode toggle and API status on an empty chat", async () => {
    mockApi([]);
    render(<App />);

    expect(screen.getByRole("heading", { name: /Ask about any NASDAQ stock/ })).toBeInTheDocument();
    const starters = within(screen.getByRole("list", { name: "Starter prompts" }));
    expect(starters.getAllByRole("button")).toHaveLength(4);
    expect(screen.getByRole("radio", { name: "Simple" })).toHaveAttribute("aria-checked", "true");
    expect(await screen.findByText("All services up")).toBeInTheDocument();
  });

  it("streams an answer with the tool timeline, sources and disclaimer", async () => {
    const sent = mockApi([sse(ANSWER_EVENTS)]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Apple's latest stock price/ }));

    expect(await screen.findByText("231.5 USD")).toBeInTheDocument();
    expect(sent[0]).toEqual({
      message: "What is Apple's latest stock price?",
      mode: "simple",
      conversation_id: null,
    });

    const timeline = screen.getByRole("region", { name: "Tool activity" });
    fireEvent.click(within(timeline).getByRole("button", { name: /Used 1 data step/ }));
    expect(within(timeline).getByText("Latest quote")).toBeInTheDocument();
    expect(within(timeline).getByText("AAPL")).toBeInTheDocument();
    expect(within(timeline).getByText(/Yahoo Finance \(yfinance\) · as of/)).toBeInTheDocument();

    const sources = screen.getByRole("region", { name: "Sources" });
    expect(within(sources).getByText("Yahoo Finance (yfinance)")).toBeInTheDocument();
    expect(
      screen.getByText("This is educational information, not financial advice."),
    ).toBeInTheDocument();

    // The conversation is listed in the sidebar and saved in the browser.
    const sidebar = screen.getByRole("complementary", { name: "Conversations" });
    expect(within(sidebar).getByText("What is Apple's latest stock price?")).toBeInTheDocument();
    await waitFor(() =>
      expect(window.localStorage.getItem("stock-research.conversations.v1")).toContain("231.5 USD"),
    );
  });

  it("sends the chosen mode and the conversation id with follow-up questions", async () => {
    const sent = mockApi([sse(ANSWER_EVENTS), sse(ANSWER_EVENTS)]);
    render(<App />);

    fireEvent.click(screen.getByRole("radio", { name: "Detailed" }));
    const input = screen.getByLabelText("Ask a question");
    fireEvent.change(input, { target: { value: "AAPL price?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("231.5 USD");

    fireEvent.change(input, { target: { value: "And a week ago?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sent).toHaveLength(2));

    expect(sent[0]).toMatchObject({ mode: "detailed", conversation_id: null });
    expect(sent[1]).toMatchObject({
      message: "And a week ago?",
      mode: "detailed",
      conversation_id: "c".repeat(32),
    });
  });

  it("shows error events from the stream", async () => {
    mockApi([
      sse([
        ["conversation", { conversation_id: "d".repeat(32), mode: "simple" }],
        ["error", { code: "llm_unavailable", message: "The language model could not be reached." }],
      ]),
    ]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Amazon ka share price/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The language model could not be reached.",
    );
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("explains an HTTP error before the stream starts", async () => {
    mockApi([Response.json({ detail: "LLM is not configured: no model" }, { status: 503 })]);
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /NVIDIA's share price/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("LLM is not configured: no model");
  });

  it("starts a new chat and reopens a saved one", async () => {
    mockApi([sse(ANSWER_EVENTS)]);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Apple's latest stock price/ }));
    await screen.findByText("231.5 USD");

    fireEvent.click(screen.getByRole("button", { name: "+ New chat" }));
    expect(screen.getByRole("heading", { name: /Ask about any NASDAQ stock/ })).toBeInTheDocument();

    const sidebar = within(screen.getByRole("complementary", { name: "Conversations" }));
    fireEvent.click(sidebar.getByRole("button", { name: /^What is Apple's latest stock price\?/ }));
    expect(screen.getByText("231.5 USD")).toBeInTheDocument();

    fireEvent.click(sidebar.getByRole("button", { name: /Delete/ }));
    expect(screen.getByText("Your conversations will appear here.")).toBeInTheDocument();
  });
});
