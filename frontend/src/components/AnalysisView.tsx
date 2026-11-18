import { DownloadIcon, FileBarChart2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { downloadFile, getResult } from "../jobs/api";
import { formatBytes, formatNumber, isScanResult, scanColumns } from "../jobs/scan";
import type { AnalysisResult, SavedAnalysis, ScanResult } from "../jobs/types";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";

interface Props {
  analysis: SavedAnalysis;
  onClose: () => void;
}

function ScanTable({ scan }: { scan: ScanResult }) {
  const columns = scanColumns(scan.rows);
  return (
    <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
      <table className="w-full text-sm [&_thead]:bg-muted/60 [&_thead]:text-xs [&_thead]:text-muted-foreground [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-medium [&_td]:px-3 [&_td]:py-2 [&_tbody_tr]:border-t [&_tbody_tr]:border-border">
        <caption className="sr-only">
          Latest indicator values per symbol, period {scan.period}
        </caption>
        <thead>
          <tr>
            <th scope="col">Symbol</th>
            <th scope="col">Last close</th>
            {columns.map((column) => (
              <th scope="col" key={`${column.indicator}.${column.series}`}>
                {column.label}
              </th>
            ))}
            <th scope="col">Signals</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(scan.rows).map(([symbol, row]) => (
            <tr key={symbol}>
              <th scope="row">{symbol}</th>
              {row.error ? (
                <td colSpan={columns.length + 2} className="text-down">
                  {row.error}
                </td>
              ) : (
                <>
                  <td className="text-right font-mono tabular-nums">
                    {formatNumber(row.last_close)}
                    {row.last_bar && (
                      <span className="block text-[10px] text-muted-foreground">
                        {row.last_bar.slice(0, 10)}
                      </span>
                    )}
                  </td>
                  {columns.map((column) => (
                    <td
                      className="text-right font-mono tabular-nums"
                      key={`${column.indicator}.${column.series}`}
                    >
                      {formatNumber(row.latest?.[column.indicator]?.[column.series])}
                    </td>
                  ))}
                  <td>{row.signals?.length ? row.signals.join("; ") : "–"}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Row = Record<string, string | number | null>;

/** Results with a list of flat rows, such as a scenario sweep. */
function rowsOf(value: unknown): Row[] | null {
  if (typeof value !== "object" || value === null) return null;
  const rows = (value as { rows?: unknown }).rows;
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const flat = rows.every(
    (row) =>
      typeof row === "object" &&
      row !== null &&
      Object.values(row).every((cell) => cell === null || typeof cell !== "object"),
  );
  return flat ? (rows as Row[]) : null;
}

function RowsTable({ rows }: { rows: Row[] }) {
  const columns = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-lg border border-border scrollbar-thin">
      <table className="w-full text-sm [&_thead]:bg-muted/60 [&_thead]:text-xs [&_thead]:text-muted-foreground [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-medium [&_td]:px-3 [&_td]:py-2 [&_tbody_tr]:border-t [&_tbody_tr]:border-border">
        <thead>
          <tr>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {column.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => {
                const cell = row[column];
                return typeof cell === "number" ? (
                  <td className="text-right font-mono tabular-nums" key={column}>
                    {formatNumber(cell)}
                  </td>
                ) : (
                  <td key={column}>{cell ?? "–"}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Reopens a saved analysis: its result, its files and where the data came from. */
export default function AnalysisView({ analysis, onClose }: Props) {
  const [data, setData] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getResult(analysis.id, controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "The result could not be loaded.");
        }
      });
    return () => controller.abort();
  }, [analysis.id]);

  const scan = data && isScanResult(data.result) ? data.result : null;
  const rows = data && !scan ? rowsOf(data.result) : null;
  const finished = new Date(analysis.finished_at ?? analysis.created_at).toLocaleString();

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent closeLabel="Close analysis" className="w-[min(94vw,56rem)]">
        <header className="flex items-start gap-3 border-b border-border px-5 py-4 pr-12">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
            <FileBarChart2Icon className="size-4.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <DialogTitle className="text-base font-semibold">{analysis.title}</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              {analysis.summary ? `${analysis.summary}. ` : ""}Finished {finished}
            </DialogDescription>
          </div>
        </header>

        {analysis.files.length > 0 && (
          <ul className="flex flex-wrap gap-2 px-5 pt-3">
            {analysis.files.map((file) => (
              <li key={file.name}>
                <button
                  type="button"
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-primary hover:bg-muted"
                  onClick={() => {
                    setDownloadError(null);
                    downloadFile(analysis.id, file.name).catch((problem: unknown) =>
                      setDownloadError(
                        problem instanceof Error ? problem.message : "The download failed.",
                      ),
                    );
                  }}
                >
                  <DownloadIcon className="size-3.5" aria-hidden="true" />
                  Download {file.name}
                </button>{" "}
                <span className="text-xs text-muted-foreground">({formatBytes(file.bytes)})</span>
              </li>
            ))}
          </ul>
        )}
        {downloadError && (
          <p className="mx-5 mt-3 rounded-md bg-down/10 px-3 py-2 text-xs text-down" role="alert">
            {downloadError}
          </p>
        )}

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4 scrollbar-thin">
          {error ? (
            <p className="rounded-md bg-down/10 px-3 py-2 text-sm text-down" role="alert">
              {error}
            </p>
          ) : !data ? (
            <div className="space-y-2" role="status">
              <span className="sr-only">Loading the saved result…</span>
              {[0, 1, 2, 3].map((n) => (
                <div key={n} className="h-8 animate-pulse rounded-md bg-muted" />
              ))}
            </div>
          ) : scan ? (
            <ScanTable scan={scan} />
          ) : rows ? (
            <RowsTable rows={rows} />
          ) : (
            <pre className="overflow-auto rounded-lg bg-muted p-3 font-mono text-xs">
              {JSON.stringify(data.result, null, 2)}
            </pre>
          )}
        </div>

        <footer className="space-y-0.5 border-t border-border px-5 py-3 text-xs text-muted-foreground">
          {scan && scan.sources.length > 0 && (
            <p>
              Source:{" "}
              {scan.sources
                .map((s) => (s.as_of ? `${s.source}, as of ${s.as_of.slice(0, 10)}` : s.source))
                .join("; ")}
            </p>
          )}
          <p>Educational information only, not financial advice.</p>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
