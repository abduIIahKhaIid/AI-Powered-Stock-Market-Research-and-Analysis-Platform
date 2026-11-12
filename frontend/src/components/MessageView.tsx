import { formatAsOf, toolLabel } from "../chat/tools";
import type { AssistantMessage, ChatMessage, Source } from "../chat/types";
import Markdown from "./Markdown";
import ToolTimeline from "./ToolTimeline";

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <section className="sources" aria-label="Sources">
      <h3>Sources</h3>
      <ul>
        {sources.map((source) => (
          <li key={`${source.source}|${source.as_of ?? ""}|${source.tool}`}>
            <span className="source-name">{source.source}</span>
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

function Assistant({ message }: { message: AssistantMessage }) {
  const live = message.state === "streaming";
  return (
    <article className="message assistant" aria-busy={live}>
      {message.tools.length > 0 && <ToolTimeline tools={message.tools} live={live} />}

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

      {message.sources.length > 0 && <SourceList sources={message.sources} />}
      {message.disclaimer && <p className="disclaimer">{message.disclaimer}</p>}
      {message.state === "done" && (
        <p className="message-meta">
          {message.mode === "detailed" ? "Detailed" : "Simple"}
          {message.usage && message.usage.tool_calls > 0 && ` · ${message.usage.tool_calls} tool calls`}
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
