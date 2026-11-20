/**
 * Asks the user before a sensitive action runs (SCRUM-26, SCRUM-38): what will run, why it
 * needs approval, how long it takes and what it costs, with Approve and Deny.
 */
import { CheckIcon, ChevronRightIcon, ShieldAlertIcon, TimerIcon, XIcon } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";
import { apiFetch } from "../auth/session";
import { toolLabel } from "../chat/tools";
import type { ApprovalItem } from "../chat/types";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./ui/collapsible";

interface Props {
  item: ApprovalItem;
  /** Injected in tests; defaults to POST /api/approvals/{id}. */
  sendDecision?: (id: string, decision: "approve" | "deny") => Promise<void>;
  now?: () => number;
}

async function postDecision(id: string, decision: "approve" | "deny") {
  const response = await apiFetch(`/api/approvals/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Could not send your answer (HTTP ${response.status}).`);
  }
}

const DONE_TEXT = {
  approved: "Approved. The action is running.",
  denied: "Denied. The assistant will answer without it.",
  expired: "Not run: no answer was given in time.",
};

function remaining(ms: number): string {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function useCountdown(expiresAt: number | undefined, now: () => number): number | null {
  const [left, setLeft] = useState(() => (expiresAt ? expiresAt - now() : null));
  useEffect(() => {
    if (!expiresAt) return;
    const timer = window.setInterval(() => setLeft(expiresAt - now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt, now]);
  return left;
}

interface BoxProps {
  titleId: string;
  describedBy?: string;
  facts: [string, ReactNode, string?][];
  children: ReactNode;
  className?: string;
}

/** The shared look of every approval: an amber card with the facts and two buttons. */
export function ApprovalBox({ titleId, describedBy, facts, children, className }: BoxProps) {
  return (
    <section
      aria-labelledby={titleId}
      aria-describedby={describedBy}
      className={cn(
        "animate-fade-up overflow-hidden rounded-xl border border-warning/50 bg-warning/[0.07] shadow-xs",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-warning/30 px-4 py-2.5">
        <ShieldAlertIcon className="size-4 text-amber-600 dark:text-warning" aria-hidden="true" />
        <h3 id={titleId} className="text-sm font-semibold">
          Approval needed
        </h3>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 px-4 py-3 text-sm">
        {facts.map(([term, detail, id]) => (
          <div key={term} className="contents">
            <dt className="text-muted-foreground">{term}</dt>
            <dd id={id} className="text-foreground">
              {detail}
            </dd>
          </div>
        ))}
      </dl>
      {children}
    </section>
  );
}

export function ApprovalActions({
  label,
  disabled,
  onApprove,
  onDeny,
}: {
  label: string;
  disabled?: boolean;
  onApprove: () => void;
  onDeny: () => void;
}) {
  return (
    <div className="flex gap-2 px-4 pb-3">
      <Button
        size="sm"
        variant="success"
        disabled={disabled}
        aria-label={`Approve: ${label}`}
        onClick={onApprove}
      >
        <CheckIcon aria-hidden="true" />
        Approve
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        aria-label={`Deny: ${label}`}
        onClick={onDeny}
      >
        <XIcon aria-hidden="true" />
        Deny
      </Button>
    </div>
  );
}

export default function ApprovalCard({ item, sendDecision = postDecision, now = Date.now }: Props) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const left = useCountdown(item.status === "pending" ? item.expiresAt : undefined, now);
  const id = useId();
  const action = toolLabel(item.tool);

  if (item.status !== "pending") {
    const approved = item.status === "approved";
    return (
      <p
        role="status"
        className={cn(
          "inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs",
          approved
            ? "border-up/30 bg-up/10 text-up"
            : "border-border bg-muted text-muted-foreground",
        )}
      >
        {approved ? <CheckIcon className="size-3.5" /> : <XIcon className="size-3.5" />}
        {action}: {DONE_TEXT[item.status]}
      </p>
    );
  }

  async function answer(decision: "approve" | "deny") {
    setSending(true);
    setError(null);
    try {
      await sendDecision(item.id, decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send your answer.");
      setSending(false);
    }
  }

  const facts: [string, ReactNode, string?][] = [
    ["Action", action],
    ["Why it asks", item.reason, `${id}-reason`],
    ["Time and cost", item.estimate || "No estimate for this action."],
  ];
  if (left !== null) {
    facts.push([
      "Waits for you",
      left > 0 ? (
        <span
          className="inline-flex items-center gap-1 font-mono tabular-nums"
          aria-label={`${remaining(left)} minutes left`}
        >
          <TimerIcon className="size-3.5" aria-hidden="true" />
          {remaining(left)} left
        </span>
      ) : (
        "Time is up"
      ),
    ]);
  }

  return (
    <ApprovalBox titleId={`${id}-title`} describedBy={`${id}-reason`} facts={facts}>
      <p className="sr-only" role="status">
        Approval needed: {action}.
      </p>
      {Object.keys(item.arguments).length > 0 && (
        <Collapsible className="px-4 pb-3">
          <CollapsibleTrigger className="group inline-flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronRightIcon
              className="size-3.5 transition-transform group-data-[state=open]:rotate-90"
              aria-hidden="true"
            />
            Show the details
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-border bg-card p-2.5 font-mono text-[11.5px] scrollbar-thin">
              {JSON.stringify(item.arguments, null, 2)}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}
      {error && (
        <p className="mx-4 mb-3 rounded-md bg-down/10 px-3 py-2 text-xs text-down" role="alert">
          {error}
        </p>
      )}
      <ApprovalActions
        label={action}
        disabled={sending}
        onApprove={() => void answer("approve")}
        onDeny={() => void answer("deny")}
      />
    </ApprovalBox>
  );
}
