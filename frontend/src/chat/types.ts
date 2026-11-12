/** Shapes shared by the chat client, the event reducer and the components. */

export type Mode = "simple" | "detailed";

export interface Source {
  source: string;
  as_of: string | null;
  tool: string;
  /** Link to the underlying document (for example an SEC filing), when the tool gives one. */
  link?: string | null;
}

export interface Candle {
  /** "2026-11-11" for daily bars, an ISO timestamp for intraday bars. */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Price chart sent by the agent after get_price_history, or by GET /api/prices (SCRUM-36). */
export interface ChartSpec {
  kind: "price";
  symbol: string;
  name?: string | null;
  period: string;
  interval: string;
  adjusted: boolean;
  candles: Candle[];
  source?: string | null;
  as_of?: string | null;
  /** Indicators the model asked for (compute_indicators); the chart switches them on. */
  indicators?: string[];
}

/** Result of checking every figure in the answer against the tool data (SCRUM-27). */
export interface Grounding {
  status: "verified" | "corrected" | "removed" | "no_figures";
  checked: number;
  attempts?: number;
  flagged?: string[];
  removed?: string[];
  note?: string | null;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  llm_calls: number;
  tool_calls: number;
  models: string[];
  used_fallback: boolean;
}

/** Events streamed by POST /chat (see backend/stock_api/chat.py). */
export type ChatEvent =
  | { type: "conversation"; data: { conversation_id: string; mode: Mode } }
  | { type: "status"; data: { state: string; step: number } }
  | { type: "token"; data: { text: string; step: number } }
  | {
      type: "tool_call";
      data: { id: string; name: string; arguments: Record<string, unknown>; step: number };
    }
  | {
      type: "tool_result";
      data: {
        id: string;
        name: string;
        ok: boolean;
        error: string | null;
        source: string | null;
        as_of: string | null;
        latency_ms: number | null;
        preview: unknown;
        step: number;
      };
    }
  | { type: "sources"; data: { sources: Source[] } }
  | { type: "chart"; data: ChartSpec }
  | {
      type: "grounding";
      data: {
        state: "fixing" | "removed";
        attempt?: number;
        unverified?: string[];
        removed?: string[];
      };
    }
  | {
      type: "done";
      data: {
        conversation_id: string;
        answer: string;
        disclaimer: string;
        usage: Usage;
        assumptions?: string[];
        grounding?: Grounding;
      };
    }
  | { type: "error"; data: { code: string; message: string } };

export type ToolStatus = "running" | "ok" | "error" | "cancelled";

/** One entry in the tool activity timeline. */
export interface ToolStep {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  step: number;
  status: ToolStatus;
  error?: string | null;
  source?: string | null;
  asOf?: string | null;
  latencyMs?: number | null;
  preview?: unknown;
  /** Text the model wrote before deciding to call tools in this step. */
  note?: string;
}

export type AssistantState = "streaming" | "done" | "error" | "stopped";

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
  mode: Mode;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  mode: Mode;
  state: AssistantState;
  text: string;
  /** The model step the streamed text belongs to. */
  textStep: number;
  statusText?: string;
  tools: ToolStep[];
  sources: Source[];
  disclaimer?: string;
  assumptions?: string[];
  grounding?: Grounding;
  charts?: ChartSpec[];
  usage?: Usage;
  error?: { code: string; message: string };
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface Conversation {
  id: string;
  /** conversation_id issued by the API; sent back for follow-up questions. */
  serverId: string | null;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}
