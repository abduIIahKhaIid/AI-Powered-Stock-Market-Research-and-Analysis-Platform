/** Turns the streamed chat events into the state of one assistant message. */

import { toolLabel } from "./tools";
import type {
  AssistantMessage,
  ChatEvent,
  JobDoneData,
  JobItem,
  JobProgressData,
  Mode,
  ToolStep,
} from "./types";

export function newAssistantMessage(id: string, mode: Mode): AssistantMessage {
  return {
    id,
    role: "assistant",
    mode,
    state: "streaming",
    text: "",
    textStep: 0,
    statusText: "Connecting…",
    tools: [],
    sources: [],
  };
}

function updateTool(
  tools: ToolStep[],
  id: string,
  name: string,
  change: Partial<ToolStep>,
): ToolStep[] {
  let index = tools.findIndex((tool) => tool.id === id);
  if (index === -1) index = tools.findIndex((t) => t.name === name && t.status === "running");
  if (index === -1) return tools;
  return tools.map((tool, i) => (i === index ? { ...tool, ...change } : tool));
}

export function applyEvent(message: AssistantMessage, event: ChatEvent): AssistantMessage {
  switch (event.type) {
    case "status":
      if (event.data.state === "fixing") {
        return { ...message, statusText: "Correcting figures that did not match the data…" };
      }
      return {
        ...message,
        statusText: message.tools.length ? "Reading the results…" : "Thinking…",
      };

    case "grounding":
      if (event.data.state === "fixing") {
        return { ...message, statusText: "Checking the figures against the data…" };
      }
      return message;

    case "token": {
      const { text, step } = event.data;
      if (step !== message.textStep) return { ...message, text, textStep: step };
      return { ...message, text: message.text + text };
    }

    case "tool_call": {
      const { id, name, arguments: args, step } = event.data;
      // Text streamed in this step was the model thinking out loud before calling a tool,
      // not the answer: keep it with the tool in the timeline.
      const streamed = message.textStep === step ? message.text.trim() : "";
      // A small model may write the tool call itself as JSON text; that is not a note.
      const preamble = /^(```|\{|<tool_call>)/.test(streamed) ? "" : streamed;
      const tool: ToolStep = {
        id,
        name,
        arguments: args ?? {},
        step,
        status: "running",
        ...(preamble ? { note: preamble } : {}),
      };
      return {
        ...message,
        text: streamed ? "" : message.text,
        tools: [...message.tools, tool],
        statusText: `${toolLabel(name)}…`,
      };
    }

    case "tool_result": {
      const data = event.data;
      return {
        ...message,
        tools: updateTool(message.tools, data.id, data.name, {
          status: data.ok ? "ok" : "error",
          error: data.error,
          source: data.source,
          asOf: data.as_of,
          latencyMs: data.latency_ms,
          preview: data.preview,
        }),
        statusText: "Reading the results…",
      };
    }

    case "approval_required": {
      const data = event.data;
      const item = {
        id: data.approval_id,
        tool: data.tool,
        arguments: data.arguments ?? {},
        reason: data.reason,
        estimate: data.estimate,
        status: "pending" as const,
      };
      return {
        ...message,
        approvals: [...(message.approvals ?? []), item],
        statusText: "Waiting for your approval…",
      };
    }

    case "approval_result":
      return {
        ...message,
        approvals: (message.approvals ?? []).map((item) =>
          item.id === event.data.approval_id ? { ...item, status: event.data.status } : item,
        ),
        statusText: event.data.status === "approved" ? "Running the approved action…" : "Thinking…",
      };

    case "chart": {
      const chart = event.data;
      const others = (message.charts ?? []).filter((c) => c.symbol !== chart.symbol);
      return { ...message, charts: [...others, chart] };
    }

    case "job_started": {
      const { job_id, kind, title } = event.data;
      if (message.jobs?.some((job) => job.id === job_id)) return message;
      const job: JobItem = {
        id: job_id,
        kind,
        title: title || kind,
        status: "queued",
        progress: 0,
        stage: "Waiting for a worker",
      };
      return { ...message, jobs: [...(message.jobs ?? []), job] };
    }

    case "sources":
      return { ...message, sources: event.data.sources ?? [] };

    case "done":
      return {
        ...message,
        state: "done",
        text: event.data.answer,
        disclaimer: event.data.disclaimer,
        assumptions: event.data.assumptions ?? [],
        grounding: event.data.grounding,
        usage: event.data.usage,
        statusText: undefined,
        tools: message.tools.map((tool) =>
          tool.status === "running" ? { ...tool, status: "error", error: "No result" } : tool,
        ),
      };

    case "error":
      return {
        ...message,
        state: "error",
        error: { code: event.data.code, message: event.data.message },
        statusText: undefined,
      };

    default:
      return message;
  }
}

/** Close a message whose stream ended or was cancelled before a done or error event. */
export function finishMessage(
  message: AssistantMessage,
  outcome: "stopped" | { code: string; message: string },
): AssistantMessage {
  if (message.state !== "streaming") return message;
  const tools = message.tools.map((tool) =>
    tool.status === "running" ? { ...tool, status: "cancelled" as const } : tool,
  );
  if (outcome === "stopped") return { ...message, state: "stopped", statusText: undefined, tools };
  return { ...message, state: "error", error: outcome, statusText: undefined, tools };
}

export const ACTIVE_JOB = new Set(["queued", "running"]);

/** Jobs whose final summary still has to arrive; their progress streams stay open. */
export function jobNeedsWatching(job: JobItem): boolean {
  return ACTIVE_JOB.has(job.status) || !job.reported;
}

export function applyJobProgress(job: JobItem, data: JobProgressData): JobItem {
  return {
    ...job,
    title: data.title ?? job.title,
    status: data.status,
    progress: data.progress,
    stage: data.stage,
    error: data.error,
  };
}

/** The assistant message that reports a finished job in the chat. */
export function jobReportMessage(id: string, mode: Mode, done: JobDoneData): AssistantMessage {
  return {
    id,
    role: "assistant",
    mode,
    state: "done",
    text: done.report,
    textStep: 0,
    tools: [],
    sources: [],
    disclaimer: done.status === "succeeded" ? done.disclaimer : undefined,
    reportFor: done.id,
  };
}
