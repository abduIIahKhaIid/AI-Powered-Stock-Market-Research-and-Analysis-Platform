/**
 * CSV export behind an approval (SCRUM-37): the same kind of card as other sensitive actions,
 * then the file is built in the browser.
 */
import { DownloadIcon } from "lucide-react";
import { useId, useState } from "react";
import { downloadCsv, type Cell } from "../charts/csv";
import { ApprovalActions, ApprovalBox } from "./ApprovalCard";
import { Chip } from "./ui/chip";

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
      <div className="basis-full pt-1">
        <ApprovalBox
          titleId={`${id}-title`}
          facts={[
            ["Action", `Export ${label} as CSV`],
            [
              "Why it asks",
              "Exports data to a file you can share; the data sources' terms still apply.",
            ],
            ["Time and cost", `Instant, built in your browser (${rows.length - 1} rows). No cost.`],
          ]}
        >
          <ApprovalActions
            label={`export ${label} as CSV`}
            onApprove={() => {
              download(filename, rows);
              setState("exported");
            }}
            onDeny={() => setState("denied")}
          />
        </ApprovalBox>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Chip onClick={() => setState("asking")}>
        <DownloadIcon aria-hidden="true" />
        Export CSV
      </Chip>
      {state === "exported" && (
        <span className="text-xs text-up" role="status">
          Exported {filename}.
        </span>
      )}
      {state === "denied" && (
        <span className="text-xs text-muted-foreground" role="status">
          Not exported.
        </span>
      )}
    </div>
  );
}
