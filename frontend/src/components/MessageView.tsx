import { lazy, Suspense } from "react";
import { formatAsOf, toolLabel } from "../chat/tools";
import type { AssistantMessage, ChatMessage, Grounding, Source } from "../chat/types";
import ApprovalCard from "./ApprovalCard";
import JobCard from "./JobCard";
import Markdown from "./Markdown";
import ToolTimeline from "./ToolTimeline";

// The chart libraries are large; load them only when an answer has a chart.
const PriceChart = lazy(() => import("./PriceChart"));
const ScenarioChart = lazy(() => import("./ScenarioChart"));

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <section className="sources" aria-label="Sources">
      <h3>Sources</h3>
      <ul>
        {sources.map((source) => (
          <li key={`${source.source}|${source.as_of ?? ""}|${source.tool}`}>
            {source.link ? (
              <a
                className="source-name"
                href={source.link}
                target="_blank"
                rel="noopener noreferrer"
              >
                {source.source}
              </a>
            ) : (
              <span className="source-name">{source.source}</span>
            )}
            {source.as_of && (
              <span className="source-meta"> · as of {formatAsOf(source.as_of)}</span>
            )}
            <span className="source-meta"> · {toolLabel(source.tool)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AssumptionList({ items }: { items: string[] }) {
  return (
    <section className="sources assumptions" aria-label="Assumptions">
      <h3>Assumptions</h3>
      <ul>
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
  switch (grounding.status) {
    case "verified":
      return <p className="grounding ok">Checked: {figures} match the source data.</p>;
    case "corrected":
      return (
        <p className="grounding ok">
          Checked: {figures} match the source data after the assistant corrected{" "}
          {grounding.flagged?.join(", ") || "a figure"}.
        </p>
      );
    case "removed":
      return (
        <p className="grounding warn" role="note">
          {grounding.note ??
            "Some figures could not be matched to the source data and were removed."}
        </p>
      );
    default:
      return null;
  }
}

function Assistant({ message }: { message: AssistantMessage }) {
  const live = message.state === "streaming";
  return (
    <article
      className={message.reportFor ? "message assistant job-report" : "message assistant"}
      aria-busy={live}
    >
      {message.tools.length > 0 && <ToolTimeline tools={message.tools} live={live} />}
      {message.approvals?.map((item) => (
        <ApprovalCard key={item.id} item={item} />
      ))}

      {message.text ? (
        <div className={live ? "answer streaming" : "answer"}>
          <Markdown text={message.text} />
        </div>
      ) : (
        live && (
          <p className="thinking" role="status">
            <span className="dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            {message.statusText ?? "Thinking…"}
          </p>
        )
      )}

      {message.state === "error" && message.error && (
        <div className="message-error" role="alert">
          {message.error.message}
        </div>
      )}
      {message.state === "stopped" && <p className="muted small">Stopped before finishing.</p>}

      {message.jobs?.map((job) => (
        <JobCard key={job.id} job={job} />
      ))}

      {message.charts && message.charts.length > 0 && (
        <Suspense fallback={<p className="muted small">Loading chart…</p>}>
          {message.charts.map((chart) =>
            chart.kind === "scenario" ? (
              <ScenarioChart key={`scenario-${chart.symbol}`} spec={chart} />
            ) : (
              <PriceChart key={`price-${chart.symbol}`} spec={chart} />
            ),
          )}
        </Suspense>
      )}
      {message.grounding && message.state === "done" && (
        <GroundingNote grounding={message.grounding} />
      )}
      {message.sources.length > 0 && <SourceList sources={message.sources} />}
      {message.assumptions && message.assumptions.length > 0 && (
        <AssumptionList items={message.assumptions} />
      )}
      {message.disclaimer && <p className="disclaimer">{message.disclaimer}</p>}
      {message.state === "done" && (
        <p className="message-meta">
          {message.mode === "detailed" ? "Detailed" : "Simple"}
          {message.usage &&
            message.usage.tool_calls > 0 &&
            ` · ${message.usage.tool_calls} tool calls`}
          {message.usage?.models.length ? ` · ${message.usage.models.join(", ")}` : ""}
          {message.usage?.used_fallback ? " · fallback model" : ""}
        </p>
      )}
    </article>
  );
}

export default function MessageView({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <article className="message user">
        <p>{message.text}</p>
      </article>
    );
  }
  return <Assistant message={message} />;
}
