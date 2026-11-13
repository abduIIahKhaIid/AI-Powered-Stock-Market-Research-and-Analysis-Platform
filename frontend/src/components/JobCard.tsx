import { useState } from "react";
import { cancelJob } from "../chat/jobs";
import type { JobItem } from "../chat/types";

const STATUS: Record<JobItem["status"], string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Progress of a background job started from this answer; the chat stays usable meanwhile. */
export default function JobCard({ job }: { job: JobItem }) {
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const active = job.status === "queued" || job.status === "running";
  const percent = Math.max(0, Math.min(100, Math.round(job.progress)));
  // A queued job with attempts behind it is waiting for its next try (SCRUM-34).
  const retrying = active && job.stage.startsWith("Retrying");
  const attempt = job.attempts ?? 0;
  const statusText = retrying ? "Retrying" : STATUS[job.status];

  async function cancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelJob(job.id);
    } catch {
      setCancelError("The job could not be cancelled. Try again.");
      setCancelling(false);
    }
  }

  return (
    <section
      className={`job-card ${retrying ? "retrying" : job.status}`}
      aria-label={`${job.title} progress`}
    >
      <div className="job-head">
        <span className="job-title">{job.title}</span>
        <span className="job-status">
          {statusText}
          {job.status === "running" ? ` · ${percent}%` : ""}
        </span>
      </div>
      <div
        className="job-bar"
        role="progressbar"
        aria-label={`${job.title} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent}%, ${job.stage}`}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="job-foot">
        <p className="job-stage" aria-live="polite">
          {job.status === "failed" && job.error ? job.error : job.stage}
        </p>
        {active && (
          <button
            type="button"
            className="job-cancel"
            onClick={() => void cancel()}
            disabled={cancelling}
            aria-label={cancelling ? `Cancelling ${job.title}` : `Cancel ${job.title}`}
          >
            {cancelling ? "Cancelling…" : "Cancel job"}
          </button>
        )}
      </div>
      {(retrying || attempt > 1) && job.maxAttempts && (
        <p className="job-retry">
          {retrying
            ? `Attempt ${attempt} of ${job.maxAttempts} failed; trying again.`
            : `Attempt ${attempt} of ${job.maxAttempts}.`}
          {retrying && job.error ? ` Last error: ${job.error}` : ""}
        </p>
      )}
      {cancelError && (
        <p className="job-error" role="alert">
          {cancelError}
        </p>
      )}
    </section>
  );
}
