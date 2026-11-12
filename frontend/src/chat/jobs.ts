/** Live progress of background jobs (SCRUM-33): GET /api/jobs/{id}/events, read with fetch. */

import { type RawSseEvent, SseParser } from "./sse";
import type { JobDoneData, JobProgressData } from "./types";

export interface JobHandlers {
  onProgress: (data: JobProgressData) => void;
  onDone: (data: JobDoneData) => void;
}

/** Reads the job's event stream; resolves true when the final job_done event arrived. */
export async function readJobEvents(
  jobId: string,
  handlers: JobHandlers,
  signal: AbortSignal,
): Promise<boolean> {
  const response = await fetch(`/api/jobs/${jobId}/events`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (response.status === 404) {
    handlers.onDone({
      id: jobId,
      kind: "",
      title: "Background job",
      status: "failed",
      summary: null,
      report: "This background job is no longer known to the server.",
      error: "not found",
    });
    return true;
  }
  if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  let finished = false;
  const handle = (events: RawSseEvent[]) => {
    for (const event of events) {
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        continue;
      }
      if (event.event === "job_progress") handlers.onProgress(data as JobProgressData);
      if (event.event === "job_done") {
        finished = true;
        handlers.onDone(data as JobDoneData);
      }
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    handle(parser.feed(decoder.decode(value, { stream: true })));
  }
  handle(parser.feed(decoder.decode()));
  handle(parser.end());
  return finished;
}

const RETRY_MS = 3000;

/** Follows a job until its job_done event, reconnecting if the stream drops. */
export function watchJob(jobId: string, handlers: JobHandlers, retryMs = RETRY_MS): () => void {
  const controller = new AbortController();
  let timer: number | undefined;

  const connect = () => {
    readJobEvents(jobId, handlers, controller.signal)
      .then((finished) => {
        if (!finished && !controller.signal.aborted) timer = window.setTimeout(connect, retryMs);
      })
      .catch(() => {
        if (!controller.signal.aborted) timer = window.setTimeout(connect, retryMs);
      });
  };
  connect();

  return () => {
    controller.abort();
    window.clearTimeout(timer);
  };
}

export async function cancelJob(jobId: string): Promise<void> {
  const response = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  // 409: the job already finished, which is fine.
  if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`);
}
