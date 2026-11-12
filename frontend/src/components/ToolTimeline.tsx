import { useState } from "react";
import { describeArguments, describePreview, formatAsOf, toolLabel } from "../chat/tools";
import type { ToolStep } from "../chat/types";

interface Props {
  tools: ToolStep[];
  live: boolean;
}

const STATUS_TEXT = { running: "Running", ok: "Done", error: "Failed", cancelled: "Cancelled" };
const STATUS_ICON = { running: "", ok: "✓", error: "!", cancelled: "–" };

function StatusIcon({ status }: { status: ToolStep["status"] }) {
  return (
    <span className={`tool-icon ${status}`} aria-label={STATUS_TEXT[status]} role="img">
      {STATUS_ICON[status]}
    </span>
  );
}

export default function ToolTimeline({ tools, live }: Props) {
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const open = expanded ?? live;
  const finished = tools.filter((tool) => tool.status !== "running").length;
  const failed = tools.filter((tool) => tool.status === "error").length;
  const cancelled = tools.filter((tool) => tool.status === "cancelled").length;
  const summary = live
    ? `Working with data · ${finished}/${tools.length}`
    : `Used ${tools.length} data ${tools.length === 1 ? "step" : "steps"}` +
      (failed ? ` · ${failed} failed` : "") +
      (cancelled ? ` · ${cancelled} cancelled` : "");

  return (
    <section className="timeline" aria-label="Tool activity">
      <button
        type="button"
        className="timeline-toggle"
        aria-expanded={open}
        onClick={() => setExpanded(!open)}
      >
        <span className={`chevron ${open ? "open" : ""}`} aria-hidden="true">
          ›
        </span>
        {summary}
      </button>
      {open && (
        <ol className="timeline-list">
          {tools.map((tool) => {
            const args = describeArguments(tool.arguments);
            const preview = tool.status === "ok" ? describePreview(tool.preview) : "";
            const meta = [
              tool.source,
              tool.asOf ? `as of ${formatAsOf(tool.asOf)}` : "",
              typeof tool.latencyMs === "number" ? `${Math.round(tool.latencyMs)} ms` : "",
            ].filter(Boolean);
            return (
              <li key={tool.id} className={`timeline-item ${tool.status}`}>
                {tool.note && <p className="timeline-note">{tool.note}</p>}
                <div className="timeline-row">
                  <StatusIcon status={tool.status} />
                  <div className="timeline-body">
                    <p className="timeline-title">
                      <strong>{toolLabel(tool.name)}</strong>
                      {args && <span className="timeline-args">{args}</span>}
                    </p>
                    {tool.status === "error" && tool.error && (
                      <p className="timeline-error">{tool.error}</p>
                    )}
                    {preview && <p className="timeline-preview">{preview}</p>}
                    {meta.length > 0 && <p className="timeline-meta">{meta.join(" · ")}</p>}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
