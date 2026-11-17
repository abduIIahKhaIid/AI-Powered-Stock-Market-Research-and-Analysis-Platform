/**
 * CSV export behind an approval (SCRUM-37): the same kind of card as other sensitive actions,
 * then the file is built in the browser.
 */
import { useId, useState } from "react";
import { downloadCsv, type Cell } from "../charts/csv";

interface Props {
  /** What is exported, e.g. "the comparison of AAPL, MSFT". */
  label: string;
  filename: string;
  rows: Cell[][];
  download?: (filename: string, rows: Cell[][]) => void;
}

type State = "idle" | "asking" | "exported" | "denied";

export default function ExportCsv({ label, filename, rows, download = downloadCsv }: Props) {
  const [state, setState] = useState<State>("idle");
  const id = useId();

  if (state === "asking") {
    return (
      <section className="approval-card export-approval" aria-labelledby={`${id}-title`}>
        <h3 id={`${id}-title`}>Approval needed</h3>
        <dl className="approval-facts">
          <dt>Action</dt>
          <dd>Export {label} as CSV</dd>
          <dt>Why it asks</dt>
          <dd>Exports data to a file you can share; the data sources' terms still apply.</dd>
          <dt>Time and cost</dt>
          <dd>Instant, built in your browser ({rows.length - 1} rows). No cost.</dd>
        </dl>
        <div className="approval-actions">
          <button
            type="button"
            className="approve"
            aria-label={`Approve: export ${label} as CSV`}
            onClick={() => {
              download(filename, rows);
              setState("exported");
            }}
          >
            Approve
          </button>
          <button
            type="button"
            className="deny"
            aria-label={`Deny: export ${label} as CSV`}
            onClick={() => setState("denied")}
          >
            Deny
          </button>
        </div>
      </section>
    );
  }

  return (
    <div className="export-row">
      <button type="button" className="chip" onClick={() => setState("asking")}>
        Export CSV
      </button>
      {state === "exported" && (
        <span className="muted small" role="status">
          Exported {filename}.
        </span>
      )}
      {state === "denied" && (
        <span className="muted small" role="status">
          Not exported.
        </span>
      )}
    </div>
  );
}
