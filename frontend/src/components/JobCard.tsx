import {
  CheckCircle2Icon,
  CircleSlashIcon,
  CogIcon,
  RotateCwIcon,
  XCircleIcon,
} from "lucide-react";
import { m } from "motion/react";
import { useState } from "react";
import { cancelJob } from "../chat/jobs";
import type { JobItem } from "../chat/types";
import { cn } from "../lib/utils";
import { useAnimate } from "../settings/context";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

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
  const animate = useAnimate();
  const active = job.status === "queued" || job.status === "running";
  const percent = Math.max(0, Math.min(100, Math.round(job.progress)));
  // A queued job with attempts behind it is waiting for its next try (SCRUM-34).
  const retrying = active && job.stage.startsWith("Retrying");
  const attempt = job.attempts ?? 0;
  const statusText = retrying ? "Retrying" : STATUS[job.status];
  const tone = retrying
    ? "warning"
    : job.status === "succeeded"
      ? "up"
      : job.status === "failed"
        ? "down"
        : job.status === "cancelled"
          ? "outline"
          : "default";
  const Icon = retrying
    ? RotateCwIcon
    : job.status === "succeeded"
      ? CheckCircle2Icon
      : job.status === "failed"
        ? XCircleIcon
        : job.status === "cancelled"
          ? CircleSlashIcon
          : CogIcon;

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
      aria-label={`${job.title} progress`}
      data-state={retrying ? "retrying" : job.status}
      className="animate-fade-up rounded-xl border border-border bg-card p-3.5 shadow-xs"
    >
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "grid size-8 place-items-center rounded-lg",
            tone === "up" && "bg-up/12 text-up",
            tone === "down" && "bg-down/12 text-down",
            tone === "warning" && "bg-warning/15 text-amber-600 dark:text-warning",
            tone === "outline" && "bg-muted text-muted-foreground",
            tone === "default" && "bg-primary/10 text-primary",
          )}
          aria-hidden="true"
        >
          <Icon
            className={cn("size-4", active && !retrying && "animate-spin [animation-duration:3s]")}
          />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{job.title}</p>
          <p
            className={cn("truncate text-xs text-muted-foreground", active && "text-shimmer")}
            aria-live="polite"
          >
            {job.status === "failed" && job.error ? job.error : job.stage}
          </p>
        </div>
        <Badge variant={tone}>
          {statusText}
          {job.status === "running" ? ` · ${percent}%` : ""}
        </Badge>
      </div>

      <div
        role="progressbar"
        aria-label={`${job.title} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${percent}%, ${job.stage}`}
        className="relative mt-3 h-2 overflow-hidden rounded-full bg-muted"
      >
        <m.span
          className={cn(
            "absolute inset-y-0 left-0 rounded-full",
            job.status === "failed"
              ? "bg-down"
              : job.status === "succeeded"
                ? "bg-up"
                : "bg-primary",
          )}
          initial={false}
          animate={{ width: `${percent}%` }}
          transition={animate ? { type: "spring", stiffness: 120, damping: 22 } : { duration: 0 }}
        />
        {active && (
          <span className="absolute inset-y-0 left-0 w-1/3 animate-indeterminate bg-gradient-to-r from-transparent via-white/40 to-transparent" />
        )}
      </div>

      {(active || cancelError || ((retrying || attempt > 1) && job.maxAttempts)) && (
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
          {(retrying || attempt > 1) && job.maxAttempts ? (
            <p className="text-xs text-amber-700 dark:text-warning">
              {retrying
                ? `Attempt ${attempt} of ${job.maxAttempts} failed; trying again.`
                : `Attempt ${attempt} of ${job.maxAttempts}.`}
              {retrying && job.error ? ` Last error: ${job.error}` : ""}
            </p>
          ) : (
            <span />
          )}
          {active && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs hover:text-down"
              onClick={() => void cancel()}
              disabled={cancelling}
              aria-label={cancelling ? `Cancelling ${job.title}` : `Cancel ${job.title}`}
            >
              {cancelling ? "Cancelling…" : "Cancel job"}
            </Button>
          )}
        </div>
      )}
      {cancelError && (
        <p className="mt-1 text-xs text-down" role="alert">
          {cancelError}
        </p>
      )}
    </section>
  );
}
