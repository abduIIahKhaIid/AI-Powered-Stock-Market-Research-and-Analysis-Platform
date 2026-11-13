import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  applyEvent,
  applyJobProgress,
  jobNeedsWatching,
  newAssistantMessage,
} from "../chat/reducer";
import type { Conversation, JobItem } from "../chat/types";
import JobCard from "./JobCard";

const JOB_ID = "b".repeat(32);
const CONVERSATION = "c".repeat(32);

function sse(events: [string, unknown][]): string {
  return events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function progress(status: string, value: number, stage: string) {
  return {
    id: JOB_ID,
    kind: "indicator_scan",
    title: "Indicator scan",
    status,
    progress: value,
    stage,
    attempts: 1,
    max_attempts: 3,
    error: null,
    retry_at: null,
  };
}

const DONE = {
  id: JOB_ID,
  kind: "indicator_scan",
  title: "Indicator scan",
  status: "succeeded",
  summary: "rsi_14 for AAPL, MSFT, NVDA (6mo)",
  report:
    "**Indicator scan finished** for AAPL, MSFT, NVDA (period 6mo).\n- **AAPL**: last close 231.46",
  error: null,
  disclaimer: "This is educational information, not financial advice.",
};

const CHAT: [string, unknown][] = [
  ["conversation", { conversation_id: CONVERSATION, mode: "simple" }],
  ["tool_call", { id: "t1", name: "start_job_indicator_scan", arguments: {}, step: 1 }],
  [
    "job_started",
    {
      job_id: JOB_ID,
      kind: "indicator_scan",
      title: "Indicator scan",
      conversation_id: CONVERSATION,
    },
  ],
  ["token", { text: "Scan shuru ho gaya hai.", step: 2 }],
  [
    "done",
    {
      conversation_id: CONVERSATION,
      answer: "Scan shuru ho gaya hai.",
      disclaimer: "Not financial advice.",
      usage: {
        prompt_tokens: 1,
        completion_tokens: 1,
        cost_usd: 0,
        llm_calls: 2,
        tool_calls: 1,
        models: [],
        used_fallback: false,
      },
    },
  ],
];

function stream(text: string) {
  return new Response(text, { headers: { "Content-Type": "text/event-stream" } });
}

function mockApi(jobEvents: () => Response) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/api/chat")) return stream(sse(CHAT));
      if (url.endsWith(`/api/jobs/${JOB_ID}/events`)) return jobEvents();
      if (url.endsWith(`/api/jobs/${JOB_ID}/cancel`)) return Response.json({ status: "cancelled" });
      if (url.includes("/api/analyses")) return Response.json([]);
      return Response.json({ status: "ok", services: { api: "ok" } });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Background job progress", () => {
  it("shows the job's progress and posts its summary when it finishes", async () => {
    const calls = mockApi(() =>
      stream(
        sse([
          ["job_progress", progress("running", 50, "Computing indicators for MSFT (2 of 3)")],
          ["job_progress", progress("succeeded", 100, "Done")],
          ["job_done", DONE],
        ]),
      ),
    );
    render(<App />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Scan AAPL, MSFT, NVDA" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/Indicator scan finished/)).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Indicator scan progress" });
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(within(card).getByText("Finished")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /^Cancel/ })).not.toBeInTheDocument();
    expect(
      screen.getByText("This is educational information, not financial advice."),
    ).toBeInTheDocument();
    // The composer is free again while the job runs in the background.
    expect(screen.getByRole("textbox")).not.toBeDisabled();
    expect(calls.filter((c) => c.includes("/events"))).toHaveLength(1);

    // After a reload the job is already reported, so it is not followed again.
    const saved = JSON.parse(
      window.localStorage.getItem("stock-research.conversations.v1") ?? "[]",
    ) as Conversation[];
    await waitFor(() => expect(saved.length).toBe(1));
  });

  it("follows a job that was still running when the page was closed", async () => {
    const job: JobItem = {
      id: JOB_ID,
      kind: "indicator_scan",
      title: "Indicator scan",
      status: "running",
      progress: 30,
      stage: "Computing indicators for AAPL",
    };
    const conversation: Conversation = {
      id: "local1",
      serverId: CONVERSATION,
      title: "Scan",
      createdAt: 1,
      updatedAt: 1,
      messages: [
        { ...newAssistantMessage("m1", "simple"), state: "done", text: "Started.", jobs: [job] },
      ],
    };
    window.localStorage.setItem("stock-research.conversations.v1", JSON.stringify([conversation]));
    mockApi(() =>
      stream(
        sse([
          ["job_progress", progress("succeeded", 100, "Done")],
          ["job_done", DONE],
        ]),
      ),
    );
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /^Scan/ }));
    expect(await screen.findByText(/Indicator scan finished/)).toBeInTheDocument();
  });

  it("cancels a running job", async () => {
    const calls = mockApi(() => stream(""));
    const job: JobItem = {
      id: JOB_ID,
      kind: "indicator_scan",
      title: "Indicator scan",
      status: "running",
      progress: 42.4,
      stage: "Computing indicators for MSFT",
    };
    render(<JobCard job={job} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(bar).toHaveAttribute("aria-valuetext", "42%, Computing indicators for MSFT");
    expect(screen.getByText("Running · 42%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel Indicator scan" }));
    await waitFor(() => expect(calls).toContain(`POST /api/jobs/${JOB_ID}/cancel`));
    expect(screen.getByRole("button", { name: "Cancelling Indicator scan" })).toBeDisabled();
  });

  it("tracks job events in the message state", () => {
    let message = newAssistantMessage("m", "simple");
    const started = {
      type: "job_started" as const,
      data: {
        job_id: JOB_ID,
        kind: "indicator_scan",
        title: "Indicator scan",
        conversation_id: "c",
      },
    };
    message = applyEvent(applyEvent(message, started), started);
    expect(message.jobs).toHaveLength(1);
    const job = message.jobs![0];
    expect(jobNeedsWatching(job)).toBe(true);
    const done = applyJobProgress(job, {
      ...progress("failed", 60, "Failed"),
      error: "boom",
    } as never);
    expect([done.status, done.error, jobNeedsWatching(done)]).toEqual(["failed", "boom", true]);
    expect(jobNeedsWatching({ ...done, reported: true })).toBe(false);
  });

  it("shows when a job is waiting to try again", () => {
    const job: JobItem = {
      id: JOB_ID,
      kind: "indicator_scan",
      title: "Indicator scan",
      status: "queued",
      progress: 40,
      stage: "Retrying 2 of 3 in 5 s",
      attempts: 1,
      maxAttempts: 3,
      error: "TransientJobError: 429 Too Many Requests",
    };
    render(<JobCard job={job} />);
    const card = screen.getByRole("region", { name: "Indicator scan progress" });
    expect(card).toHaveClass("retrying");
    expect(within(card).getByText("Retrying")).toBeInTheDocument();
    expect(card).toHaveTextContent(
      "Attempt 1 of 3 failed; trying again. Last error: TransientJobError: 429 Too Many Requests",
    );
    expect(within(card).getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      "40%, Retrying 2 of 3 in 5 s",
    );
  });

  it("copies the attempt count from progress events", () => {
    const job: JobItem = {
      id: JOB_ID,
      kind: "indicator_scan",
      title: "Indicator scan",
      status: "running",
      progress: 0,
      stage: "",
    };
    const next = applyJobProgress(job, progress("running", 10, "Attempt 2 of 3") as never);
    expect([next.attempts, next.maxAttempts]).toEqual([1, 3]);
  });
});
