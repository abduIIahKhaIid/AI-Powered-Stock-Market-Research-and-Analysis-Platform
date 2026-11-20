import {
  AlertTriangleIcon,
  CheckIcon,
  CopyIcon,
  ExternalLinkIcon,
  InfoIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrendingUpIcon,
} from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { formatAsOf, toolLabel } from "../chat/tools";
import type { AssistantMessage, ChatMessage, Feedback, Grounding, Source } from "../chat/types";
import { cn } from "../lib/utils";
import { useSettings } from "../settings/context";
import ApprovalCard from "./ApprovalCard";
import ChartBoundary from "./ChartBoundary";
import JobCard from "./JobCard";
import Markdown from "./Markdown";
import ThinkingPanel from "./ThinkingPanel";
import { Button } from "./ui/button";
import { Tooltip } from "./ui/tooltip";

// The chart libraries are large; load them only when an answer has a chart.
const PriceChart = lazy(() => import("./PriceChart"));
const ScenarioChart = lazy(() => import("./ScenarioChart"));
const FundamentalsChart = lazy(() => import("./FundamentalsChart"));
const ComparisonTable = lazy(() => import("./ComparisonTable"));

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <section aria-label="Sources" className="animate-fade-up">
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        Sources
      </h3>
      <ul className="flex flex-wrap gap-1.5">
        {sources.map((source, index) => (
          <li
            key={`${source.source}|${source.as_of ?? ""}|${source.tool}`}
            className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-card py-1 pr-2.5 pl-1 text-xs shadow-xs"
          >
            <span
              className="grid size-5 shrink-0 place-items-center rounded-md bg-muted font-mono text-[10px] font-semibold text-muted-foreground"
              aria-hidden="true"
            >
              {index + 1}
            </span>
            {source.link ? (
              <a
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                href={source.link}
                target="_blank"
                rel="noopener noreferrer"
              >
                {source.source}
                <ExternalLinkIcon className="size-3" aria-hidden="true" />
              </a>
            ) : (
              <span className="font-medium text-foreground">{source.source}</span>
            )}
            {source.as_of && (
              <span className="text-muted-foreground"> · as of {formatAsOf(source.as_of)}</span>
            )}
            <span className="text-muted-foreground"> · {toolLabel(source.tool)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Shown on every projection and what-if answer (SCRUM-38). */
function ProjectionBanner() {
  return (
    <aside
      aria-label="Projection disclaimer"
      className="flex animate-fade-up gap-3 rounded-xl border border-warning/50 bg-warning/[0.08] px-4 py-3 text-sm"
    >
      <AlertTriangleIcon
        className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-warning"
        aria-hidden="true"
      />
      <p>
        <strong>Projection, not a prediction.</strong> These figures follow from the assumptions
        listed with this answer. They are educational information, not financial advice.
      </p>
    </aside>
  );
}

function AssumptionList({ items }: { items: string[] }) {
  return (
    <section aria-label="Assumptions" className="animate-fade-up">
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        Assumptions
      </h3>
      <ul className="list-disc space-y-0.5 pl-5 text-sm text-foreground/90">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

/** One line saying whether the figures in the answer matched the source data. */
export function GroundingNote({ grounding }: { grounding: Grounding }) {
  const count = grounding.checked;
  const figures = `${count} figure${count === 1 ? "" : "s"}`;
  const ok = "inline-flex items-center gap-1.5 text-xs text-up";
  switch (grounding.status) {
    case "verified":
      return (
        <p className={ok}>
          <ShieldCheckIcon className="size-3.5" aria-hidden="true" />
          <span>Checked: {figures} match the source data.</span>
        </p>
      );
    case "corrected":
      return (
        <p className={ok}>
          <ShieldCheckIcon className="size-3.5" aria-hidden="true" />
          <span>
            Checked: {figures} match the source data after the assistant corrected{" "}
            {grounding.flagged?.join(", ") || "a figure"}.
          </span>
        </p>
      );
    case "removed":
      return (
        <p
          className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-amber-800 dark:text-warning"
          role="note"
        >
          {grounding.note ??
            "Some figures could not be matched to the source data and were removed."}
        </p>
      );
    default:
      return null;
  }
}

function Avatar() {
  return (
    <span
      className="grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-500 text-white shadow-sm"
      aria-hidden="true"
    >
      <TrendingUpIcon className="size-4" strokeWidth={2.5} />
    </span>
  );
}

function clock(timestamp?: number): string {
  if (!timestamp) return "";
  return new Date(timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

interface ActionsProps {
  message: AssistantMessage;
  onRate?: (id: string, feedback: Feedback) => void;
  onRetry?: () => void;
}

/** Copy, thumbs up / down and retry, under a finished answer (as in Chainlit). */
function MessageActions({ message, onRate, onRetry }: ActionsProps) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked: nothing to do.
    }
  }
  const rated = (value: Feedback) => message.feedback === value;
  return (
    <div className="flex items-center gap-0.5 opacity-70 transition-opacity group-hover/message:opacity-100 focus-within:opacity-100">
      {message.text && (
        <Tooltip content={copied ? "Copied" : "Copy"}>
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={copied ? "Copied" : "Copy answer"}
            onClick={() => void copy()}
          >
            {copied ? <CheckIcon className="text-up" /> : <CopyIcon />}
          </Button>
        </Tooltip>
      )}
      {onRate && message.state === "done" && (
        <>
          <Tooltip content="Helpful">
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label="Helpful"
              aria-pressed={rated("up")}
              className={cn(rated("up") && "text-up")}
              onClick={() => onRate(message.id, "up")}
            >
              <ThumbsUpIcon className={cn(rated("up") && "fill-current")} />
            </Button>
          </Tooltip>
          <Tooltip content="Not helpful">
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label="Not helpful"
              aria-pressed={rated("down")}
              className={cn(rated("down") && "text-down")}
              onClick={() => onRate(message.id, "down")}
            >
              <ThumbsDownIcon className={cn(rated("down") && "fill-current")} />
            </Button>
          </Tooltip>
        </>
      )}
      {onRetry && (
        <Tooltip content="Ask again">
          <Button size="icon-xs" variant="ghost" aria-label="Ask again" onClick={onRetry}>
            <RefreshCwIcon />
          </Button>
        </Tooltip>
      )}
    </div>
  );
}

function Charts({ message }: { message: AssistantMessage }) {
  if (!message.charts?.length) return null;
  return (
    <Suspense
      fallback={
        <div
          className="h-64 animate-pulse rounded-2xl border border-border bg-muted/50"
          role="status"
        >
          <span className="sr-only">Loading chart…</span>
        </div>
      }
    >
      {message.charts.map((chart) => {
        const key = `${chart.kind}-${chart.symbol}`;
        switch (chart.kind) {
          case "scenario":
            return (
              <ChartBoundary key={key} name="scenario chart">
                <ScenarioChart spec={chart} />
              </ChartBoundary>
            );
          case "fundamentals":
            return (
              <ChartBoundary key={key} name="fundamentals chart">
                <FundamentalsChart spec={chart} />
              </ChartBoundary>
            );
          case "comparison":
            return (
              <ChartBoundary key={key} name="comparison table">
                <ComparisonTable spec={chart} />
              </ChartBoundary>
            );
          case "price":
            return (
              <ChartBoundary key={key} name="price chart">
                <PriceChart spec={chart} />
              </ChartBoundary>
            );
          default:
            return null;
        }
      })}
    </Suspense>
  );
}

function Assistant({ message, onRate, onRetry }: ActionsProps) {
  const { chainOfThought } = useSettings();
  const live = message.state === "streaming";
  const finished = message.state !== "streaming";
  return (
    <article
      className="group/message flex animate-fade-up gap-3"
      aria-busy={live}
      aria-label={message.reportFor ? "Background job report" : "Assistant message"}
    >
      <Avatar />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex h-8 items-center gap-2 text-sm">
          <span className="font-semibold">Stock Research</span>
          {message.reportFor && (
            <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
              Background job
            </span>
          )}
          <span className="text-xs text-muted-foreground">{clock(message.startedAt)}</span>
        </div>

        {message.projection && <ProjectionBanner />}
        <ThinkingPanel message={message} chainOfThought={chainOfThought} />
        {message.approvals?.map((item) => (
          <ApprovalCard key={item.id} item={item} />
        ))}

        {message.text && <Markdown text={message.text} streaming={live} />}

        {message.state === "error" && message.error && (
          <div
            className="flex items-start gap-2 rounded-xl border border-down/30 bg-down/[0.07] px-4 py-3 text-sm text-down"
            role="alert"
          >
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {message.error.message}
          </div>
        )}
        {message.state === "stopped" && (
          <p className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <InfoIcon className="size-3.5" aria-hidden="true" />
            Stopped before finishing.
          </p>
        )}

        {message.jobs?.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
        <Charts message={message} />

        {message.grounding && message.state === "done" && (
          <GroundingNote grounding={message.grounding} />
        )}
        {message.sources.length > 0 && <SourceList sources={message.sources} />}
        {message.assumptions && message.assumptions.length > 0 && (
          <AssumptionList items={message.assumptions} />
        )}
        {message.disclaimer && (
          <p className="text-xs text-muted-foreground italic">{message.disclaimer}</p>
        )}
        {finished && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <MessageActions message={message} onRate={onRate} onRetry={onRetry} />
            {message.state === "done" && (
              <p className="text-[11px] text-muted-foreground">
                {message.mode === "detailed" ? "Detailed" : "Simple"}
                {message.usage &&
                  message.usage.tool_calls > 0 &&
                  ` · ${message.usage.tool_calls} tool call${message.usage.tool_calls === 1 ? "" : "s"}`}
                {message.usage?.models.length ? ` · ${message.usage.models.join(", ")}` : ""}
                {message.usage?.used_fallback ? " · fallback model" : ""}
              </p>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

interface Props {
  message: ChatMessage;
  onRate?: (id: string, feedback: Feedback) => void;
  /** Given for the last answer only: asks its question again. */
  onRetry?: () => void;
}

export default function MessageView({ message, onRate, onRetry }: Props) {
  if (message.role === "user") {
    return (
      <article className="flex animate-fade-up justify-end" aria-label="Your message">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-primary-foreground shadow-sm">
          {message.text}
        </p>
      </article>
    );
  }
  return <Assistant message={message} onRate={onRate} onRetry={onRetry} />;
}
