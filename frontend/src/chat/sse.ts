/**
 * Client for POST /chat. EventSource only supports GET, so the stream is read with fetch
 * and parsed here following the Server-Sent Events format.
 */

import type { ChatEvent, Mode } from "./types";

export interface RawSseEvent {
  event: string;
  data: string;
}

/** Incremental SSE parser: feed it text chunks, get back complete events. */
export class SseParser {
  private buffer = "";
  private eventName = "";
  private dataLines: string[] = [];

  feed(chunk: string): RawSseEvent[] {
    let text = this.buffer + chunk;
    // A chunk may end between the \r and \n of one line break; keep the \r for later.
    let held = "";
    if (text.endsWith("\r")) {
      held = "\r";
      text = text.slice(0, -1);
    }
    const lines = text.split(/\r\n|\r|\n/);
    this.buffer = (lines.pop() ?? "") + held;

    const events: RawSseEvent[] = [];
    for (const line of lines) {
      const event = this.processLine(line);
      if (event) events.push(event);
    }
    return events;
  }

  /** Flush whatever is left when the stream ends. */
  end(): RawSseEvent[] {
    const events = this.feed("\n\n");
    this.buffer = "";
    return events;
  }

  private processLine(line: string): RawSseEvent | null {
    if (line === "") {
      if (this.dataLines.length === 0) {
        this.eventName = "";
        return null;
      }
      const event = { event: this.eventName || "message", data: this.dataLines.join("\n") };
      this.eventName = "";
      this.dataLines = [];
      return event;
    }
    if (line.startsWith(":")) return null; // comment, e.g. the server's keep-alive

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.eventName = value;
    else if (field === "data") this.dataLines.push(value);
    return null;
  }
}

export interface ChatRequest {
  message: string;
  mode: Mode;
  conversation_id: string | null;
}

/** The API answered with an HTTP error before streaming started. */
export class ChatHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ChatHttpError";
    this.status = status;
  }
}

async function errorDetail(response: Response): Promise<string> {
  const fallback = `The server answered with HTTP ${response.status}.`;
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as { msg?: unknown })?.msg)
        .filter((msg): msg is string => typeof msg === "string");
      if (messages.length) return messages.join("; ");
    }
  } catch {
    // Not JSON: keep the generic message.
  }
  return fallback;
}

export const CHAT_ENDPOINT = "/api/chat";

/** Send one question and call `onEvent` for every event until the stream ends. */
export async function streamChat(
  request: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(CHAT_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw new ChatHttpError(response.status, await errorDetail(response));
  if (!response.body) throw new Error("The server returned an empty response.");

  const parser = new SseParser();
  const decoder = new TextDecoder();
  const emit = (raw: RawSseEvent) => {
    let data: unknown;
    try {
      data = JSON.parse(raw.data);
    } catch {
      return; // Ignore malformed events instead of breaking the whole answer.
    }
    onEvent({ type: raw.event, data } as ChatEvent);
  };

  const reader = response.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.feed(decoder.decode(value, { stream: true })).forEach(emit);
  }
  parser.feed(decoder.decode()).forEach(emit);
  parser.end().forEach(emit);
}
