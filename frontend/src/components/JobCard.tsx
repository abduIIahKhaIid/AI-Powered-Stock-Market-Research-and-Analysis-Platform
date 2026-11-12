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
    <section className={`job-card ${job.status}`} aria-label={`${job.title} progress`}>
      <div className="job-head">
        <span className="job-title">{job.title}</span>
        <span className="job-status">
          {STATUS[job.status]}
          {active && job.status === "running" ? ` · ${percent}%` : ""}
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
          >
            {cancelling ? "Cancelling…" : "Cancel job"}
          </button>
        )}
      </div>
      {cancelError && (
        <p className="job-error" role="alert">
          {cancelError}
        </p>
      )}
    </section>
  );
}
