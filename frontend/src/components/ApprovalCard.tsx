/**
 * Asks the user before a sensitive action runs (SCRUM-26, SCRUM-38): what will run, why it
 * needs approval, how long it takes and what it costs, with Approve and Deny.
 */
import { useEffect, useId, useState } from "react";
import { toolLabel } from "../chat/tools";
import type { ApprovalItem } from "../chat/types";

interface Props {
  item: ApprovalItem;
  /** Injected in tests; defaults to POST /api/approvals/{id}. */
  sendDecision?: (id: string, decision: "approve" | "deny") => Promise<void>;
  now?: () => number;
}

async function postDecision(id: string, decision: "approve" | "deny") {
  const response = await fetch(`/api/approvals/${id}`, {
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

export default function ApprovalCard({ item, sendDecision = postDecision, now = Date.now }: Props) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const left = useCountdown(item.status === "pending" ? item.expiresAt : undefined, now);
  const id = useId();
  const action = toolLabel(item.tool);

  if (item.status !== "pending") {
    return (
      <p className={`approval-done ${item.status}`} role="status">
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

  return (
    <section
      className="approval-card"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-reason`}
    >
      <p className="visually-hidden" role="status">
        Approval needed: {action}.
      </p>
      <h3 id={`${id}-title`}>Approval needed</h3>
      <dl className="approval-facts">
        <dt>Action</dt>
        <dd>{action}</dd>
        <dt>Why it asks</dt>
        <dd id={`${id}-reason`}>{item.reason}</dd>
        <dt>Time and cost</dt>
        <dd>{item.estimate || "No estimate for this action."}</dd>
        {left !== null && (
          <>
            <dt>Waits for you</dt>
            <dd>
              {left > 0 ? (
                <span aria-label={`${remaining(left)} minutes left`}>{remaining(left)} left</span>
              ) : (
                "Time is up"
              )}
            </dd>
          </>
        )}
      </dl>
      {Object.keys(item.arguments).length > 0 && (
        <details>
          <summary>Show the details</summary>
          <pre>{JSON.stringify(item.arguments, null, 2)}</pre>
        </details>
      )}
      {error && (
        <p className="chart-error" role="alert">
          {error}
        </p>
      )}
      <div className="approval-actions">
        <button
          type="button"
          className="approve"
          disabled={sending}
          aria-label={`Approve: ${action}`}
          onClick={() => answer("approve")}
        >
          Approve
        </button>
        <button
          type="button"
          className="deny"
          disabled={sending}
          aria-label={`Deny: ${action}`}
          onClick={() => answer("deny")}
        >
          Deny
        </button>
      </div>
    </section>
  );
}
