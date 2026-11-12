import { describe, expect, it, vi } from "vitest";
import { ChatHttpError, SseParser, streamChat } from "./sse";
import type { ChatEvent } from "./types";

describe("SseParser", () => {
  it("parses events split across chunks", () => {
    const parser = new SseParser();
    expect(parser.feed('event: token\ndata: {"te')).toEqual([]);
    expect(parser.feed('xt":"Hi"}\n')).toEqual([]);
    expect(parser.feed("\n")).toEqual([{ event: "token", data: '{"text":"Hi"}' }]);
  });

  it("ignores keep-alive comments and handles CRLF split between chunks", () => {
    const parser = new SseParser();
    const events = [
      ...parser.feed(": keep-alive\r\n\r\nevent: status\r"),
      ...parser.feed('\ndata: {"step":1}\r\n\r\n'),
    ];
    expect(events).toEqual([{ event: "status", data: '{"step":1}' }]);
  });

  it("joins multi-line data and defaults the event name", () => {
    const parser = new SseParser();
    expect(parser.feed("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("flushes a final event without a trailing blank line", () => {
    const parser = new SseParser();
    parser.feed('event: done\ndata: {"answer":"x"}');
    expect(parser.end()).toEqual([{ event: "done", data: '{"answer":"x"}' }]);
  });
});

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("streamChat", () => {
  it("posts the question and emits parsed events", async () => {
    const fetchMock = vi.fn(async () =>
      streamResponse([
        'event: conversation\ndata: {"conversation_id":"abc","mode":"simple"}\n\n',
        'event: token\ndata: {"text":"Hel',
        'lo","step":1}\n\n: keep-alive\n\n',
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events: ChatEvent[] = [];

    await streamChat({ message: "Hi", mode: "detailed", conversation_id: null }, (event) =>
      events.push(event),
    );

    expect(events.map((event) => event.type)).toEqual(["conversation", "token"]);
    expect(events[1]).toEqual({ type: "token", data: { text: "Hello", step: 1 } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/chat");
    expect(JSON.parse(String(init.body))).toEqual({
      message: "Hi",
      mode: "detailed",
      conversation_id: null,
    });
  });

  it("raises the API detail on an HTTP error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ detail: "LLM is not configured: missing model" }, { status: 503 }),
      ),
    );

    const call = streamChat({ message: "Hi", mode: "simple", conversation_id: null }, () => {});
    await expect(call).rejects.toBeInstanceOf(ChatHttpError);
    await expect(call).rejects.toThrow("LLM is not configured: missing model");
  });
});
