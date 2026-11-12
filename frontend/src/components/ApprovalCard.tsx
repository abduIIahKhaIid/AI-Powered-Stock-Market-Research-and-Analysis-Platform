/** Asks the user before a sensitive action runs (SCRUM-26); see the Miro wireframe frame 6. */
import { useState } from "react";
import { toolLabel } from "../chat/tools";
import type { ApprovalItem } from "../chat/types";

interface Props {
  item: ApprovalItem;
  /** Injected in tests; defaults to POST /api/approvals/{id}. */
  sendDecision?: (id: string, decision: "approve" | "deny") => Promise<void>;
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
  denied: "Not run. The assistant will answer without it.",
  expired: "Not run: no answer was given in time.",
};

export default function ApprovalCard({ item, sendDecision = postDecision }: Props) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (item.status !== "pending") {
    return (
      <p className={`approval-done ${item.status}`} role="status">
        {toolLabel(item.tool)}: {DONE_TEXT[item.status]}
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
    <section className="approval-card" aria-label="Approval needed">
      <h3>Allow this action?</h3>
      <p>
        <strong>{toolLabel(item.tool)}</strong>: {item.reason}
      </p>
      {item.estimate && <p className="muted small">Estimate: {item.estimate}</p>}
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
          onClick={() => answer("approve")}
        >
          Run it
        </button>
        <button type="button" className="deny" disabled={sending} onClick={() => answer("deny")}>
          Don't run
        </button>
      </div>
    </section>
  );
}
