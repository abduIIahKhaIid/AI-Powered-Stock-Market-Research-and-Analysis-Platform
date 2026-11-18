/**
 * The assistant's work before the answer, in one collapsible panel (like the "Thinking" block
 * in Claude's chat and Chainlit's steps): the model's reasoning, notes it wrote before calling
 * tools, and every tool call with its input and output.
 *
 * It opens by itself while the assistant works and folds away once the answer starts, leaving
 * a one-line summary ("Thought for 6s · used 2 tools"). Opening or closing it by hand wins.
 */
import {
  BrainIcon,
  CheckIcon,
  ChevronRightIcon,
  CircleSlashIcon,
  DatabaseIcon,
  Loader2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { describeArguments, describePreview, formatAsOf, toolLabel } from "../chat/tools";
import type { AssistantMessage, ToolStep } from "../chat/types";
import { cn } from "../lib/utils";
import type { ChainOfThought } from "../settings/context";
import { Badge } from "./ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";

/** Re-renders every second while `active`, for the live timer. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function seconds(ms: number): string {
  const total = Math.max(1, Math.round(ms / 1000));
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}

const STATUS_TEXT = { running: "Running", ok: "Done", error: "Failed", cancelled: "Cancelled" };

function StatusIcon({ status }: { status: ToolStep["status"] }) {
  const common = "size-3.5";
  return (
    <span
      role="img"
      aria-label={STATUS_TEXT[status]}
      className={cn(
        "relative z-10 grid size-5 shrink-0 place-items-center rounded-full ring-4 ring-background",
        status === "running" && "bg-primary/12 text-primary",
        status === "ok" && "bg-up/15 text-up",
        status === "error" && "bg-down/15 text-down",
        status === "cancelled" && "bg-muted text-muted-foreground",
      )}
    >
      {status === "running" && <Loader2Icon className={cn(common, "animate-spin")} />}
      {status === "ok" && <CheckIcon className={common} strokeWidth={3} />}
      {status === "error" && <TriangleAlertIcon className={common} />}
      {status === "cancelled" && <CircleSlashIcon className={common} />}
    </span>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-56 overflow-auto rounded-md border border-border bg-muted/60 p-2.5 font-mono text-[11.5px] leading-relaxed text-foreground scrollbar-thin">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** One tool call, Chainlit-style: "Used Latest quote", expandable to its input and output. */
function ToolItem({ tool }: { tool: ToolStep }) {
  const [open, setOpen] = useState(false);
  const args = describeArguments(tool.arguments);
  const preview = tool.status === "ok" ? describePreview(tool.preview) : "";
  const meta = [
    tool.source,
    tool.asOf ? `as of ${formatAsOf(tool.asOf)}` : "",
    typeof tool.latencyMs === "number" ? `${Math.round(tool.latencyMs)} ms` : "",
  ].filter(Boolean);
  const verb = tool.status === "running" ? "Using" : "Used";

  return (
    <li className="relative flex animate-fade-up gap-3 pb-3 last:pb-0">
      <StatusIcon status={tool.status} />
      <Collapsible open={open} onOpenChange={setOpen} className="min-w-0 flex-1">
        <CollapsibleTrigger
          className="group flex w-full cursor-pointer items-center gap-1.5 rounded-md text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label={`${verb} ${toolLabel(tool.name)}${args ? ` (${args})` : ""}: show input and output`}
        >
          <span
            className={cn("text-muted-foreground", tool.status === "running" && "text-shimmer")}
          >
            {verb}
          </span>
          <strong className="font-medium text-foreground">{toolLabel(tool.name)}</strong>
          {args && (
            <span className="truncate rounded bg-muted px-1.5 py-px font-mono text-xs text-muted-foreground">
              {args}
            </span>
          )}
          <ChevronRightIcon
            className="ml-auto size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90"
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        {tool.status === "error" && tool.error && (
          <p className="mt-1 text-xs text-down">{tool.error}</p>
        )}
        {preview && <p className="mt-0.5 truncate text-xs text-muted-foreground">{preview}</p>}
        {meta.length > 0 && (
          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground/80">
            <DatabaseIcon className="size-3" aria-hidden="true" />
            {meta.join(" · ")}
          </p>
        )}
        <CollapsibleContent>
          <div className="mt-2 grid gap-2">
            <div>
              <p className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                Input
              </p>
              <Json value={tool.arguments} />
            </div>
            {tool.preview !== undefined && tool.preview !== null && (
              <div>
                <p className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                  Output
                </p>
                <Json value={tool.preview} />
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

function Thought({ text }: { text: string }) {
  return (
    <li className="relative flex animate-fade-up gap-3 pb-3 last:pb-0">
      <span className="relative z-10 mt-1.5 grid size-5 shrink-0 place-items-center">
        <span className="size-1.5 rounded-full bg-muted-foreground/50 ring-4 ring-background" />
      </span>
      <p className="min-w-0 flex-1 text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
        {text.trim()}
      </p>
    </li>
  );
}

type Entry = { kind: "thought"; key: string; text: string } | { kind: "tool"; tool: ToolStep };

/** Reasoning, notes and tools in the order they happened: by model step. */
function entries(message: AssistantMessage, showThoughts: boolean): Entry[] {
  const steps = new Set<number>([
    ...(message.thinking ?? []).map((block) => block.step),
    ...message.tools.map((tool) => tool.step),
  ]);
  const out: Entry[] = [];
  for (const step of [...steps].sort((a, b) => a - b)) {
    if (showThoughts) {
      (message.thinking ?? [])
        .filter((block) => block.step === step && block.text.trim())
        .forEach((block, i) =>
          out.push({ kind: "thought", key: `t${step}-${i}`, text: block.text }),
        );
    }
    for (const tool of message.tools.filter((item) => item.step === step)) {
      if (showThoughts && tool.note)
        out.push({ kind: "thought", key: `n${tool.id}`, text: tool.note });
      out.push({ kind: "tool", tool });
    }
  }
  return out;
}

interface Props {
  message: AssistantMessage;
  chainOfThought: ChainOfThought;
}

export default function ThinkingPanel({ message, chainOfThought }: Props) {
  const live = message.state === "streaming";
  // Working on the answer: nothing of the answer itself has streamed yet.
  const working = live && !message.text;
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? working;
  const now = useNow(live);
  const bodyRef = useRef<HTMLDivElement>(null);

  const list = entries(message, chainOfThought === "full");
  const thoughtCount = list.filter((entry) => entry.kind === "thought").length;

  // Keep the newest reasoning in view while it streams.
  const lastLength = list.length + (message.thinking?.at(-1)?.text.length ?? 0);
  useEffect(() => {
    const body = bodyRef.current;
    if (body && working) body.scrollTop = body.scrollHeight;
  }, [lastLength, working]);

  if (chainOfThought === "hidden") {
    if (!working) return null;
    return (
      <p className="flex items-center gap-2 text-sm" role="status">
        <Loader2Icon className="size-4 animate-spin text-primary" aria-hidden="true" />
        <span className="text-shimmer">{message.statusText ?? "Thinking…"}</span>
      </p>
    );
  }
  if (!working && list.length === 0) return null;

  const tools = message.tools.length;
  const failed = message.tools.filter((tool) => tool.status === "error").length;
  const cancelled = message.tools.filter((tool) => tool.status === "cancelled").length;
  const elapsed =
    message.thoughtMs ??
    (message.startedAt ? (message.answerStartedAt ?? now) - message.startedAt : 0);
  const toolText = tools
    ? `used ${tools} ${tools === 1 ? "tool" : "tools"}` +
      (failed ? ` · ${failed} failed` : "") +
      (cancelled ? ` · ${cancelled} cancelled` : "")
    : "";

  return (
    <section aria-label="Thinking" className="w-full">
      <Collapsible open={open} onOpenChange={setManual}>
        <CollapsibleTrigger className="group inline-flex max-w-full cursor-pointer items-center gap-2 rounded-lg py-1 pr-2 text-sm text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50">
          <span
            className={cn(
              "grid size-6 place-items-center rounded-md",
              working ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
            )}
            aria-hidden="true"
          >
            <BrainIcon className={cn("size-3.5", working && "animate-pulse")} />
          </span>
          {working ? (
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate font-medium text-shimmer">
                {message.statusText ?? "Thinking…"}
              </span>
              {elapsed >= 1000 && (
                <span className="font-mono text-xs tabular-nums">{seconds(elapsed)}</span>
              )}
            </span>
          ) : (
            <span className="truncate">
              <span className="font-medium">Thought for {seconds(elapsed)}</span>
              {toolText && <span> · {toolText}</span>}
            </span>
          )}
          <ChevronRightIcon
            className="size-4 shrink-0 transition-transform duration-200 group-data-[state=open]:rotate-90"
            aria-hidden="true"
          />
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div
            ref={bodyRef}
            className={cn("mt-1.5 pl-0.5", working && "max-h-80 overflow-y-auto scrollbar-thin")}
          >
            {list.length === 0 ? (
              <p className="pb-2 pl-1 text-[13px] text-muted-foreground">Reading your question…</p>
            ) : (
              // The rail runs behind the step icons, which are ringed with the page color.
              <ol
                className="relative pt-0.5 before:absolute before:top-3 before:bottom-3 before:left-[9.5px] before:w-px before:bg-border"
                aria-label="Steps"
              >
                {list.map((entry) =>
                  entry.kind === "thought" ? (
                    <Thought key={entry.key} text={entry.text} />
                  ) : (
                    <ToolItem key={entry.tool.id} tool={entry.tool} />
                  ),
                )}
              </ol>
            )}
            {!working && (tools > 0 || thoughtCount > 0) && (
              <div className="flex flex-wrap gap-1.5 pt-1 pb-1 pl-8">
                {tools > 0 && <Badge variant="secondary">{tools} data calls</Badge>}
                {thoughtCount > 0 && <Badge variant="outline">{thoughtCount} notes</Badge>}
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </section>
  );
}
