import { useEffect, useRef, useState } from "react";
import { fileUrl, getResult } from "../jobs/api";
import { formatBytes, formatNumber, isScanResult, scanColumns } from "../jobs/scan";
import type { AnalysisResult, SavedAnalysis, ScanResult } from "../jobs/types";

interface Props {
  analysis: SavedAnalysis;
  onClose: () => void;
}

function ScanTable({ scan }: { scan: ScanResult }) {
  const columns = scanColumns(scan.rows);
  return (
    <div className="table-wrap">
      <table className="scan-table">
        <caption className="visually-hidden">
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
                <td colSpan={columns.length + 2} className="scan-error">
                  {row.error}
                </td>
              ) : (
                <>
                  <td className="num">
                    {formatNumber(row.last_close)}
                    {row.last_bar && <span className="scan-bar">{row.last_bar.slice(0, 10)}</span>}
                  </td>
                  {columns.map((column) => (
                    <td className="num" key={`${column.indicator}.${column.series}`}>
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

/** Reopens a saved analysis: its result, its files and where the data came from. */
export default function AnalysisView({ analysis, onClose }: Props) {
  const [data, setData] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

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

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  const scan = data && isScanResult(data.result) ? data.result : null;
  const finished = new Date(analysis.finished_at ?? analysis.created_at).toLocaleString();

  return (
    <div className="analysis-layer">
      <div className="backdrop analysis-backdrop" onClick={onClose} aria-hidden="true" />
      <div
        className="analysis"
        role="dialog"
        aria-modal="true"
        aria-labelledby="analysis-title"
        aria-describedby="analysis-meta"
      >
        <header className="analysis-head">
          <div>
            <h2 id="analysis-title">{analysis.title}</h2>
            <p id="analysis-meta" className="muted small">
              {analysis.summary ? `${analysis.summary}. ` : ""}Finished {finished}
            </p>
          </div>
          <button ref={closeRef} type="button" className="icon-button" onClick={onClose}>
            <span aria-hidden="true">×</span>
            <span className="visually-hidden">Close analysis</span>
          </button>
        </header>

        {analysis.files.length > 0 && (
          <ul className="analysis-files">
            {analysis.files.map((file) => (
              <li key={file.name}>
                <a href={fileUrl(analysis.id, file.name)} download={file.name}>
                  Download {file.name}
                </a>{" "}
                <span className="muted small">({formatBytes(file.bytes)})</span>
              </li>
            ))}
          </ul>
        )}

        <div className="analysis-body">
          {error ? (
            <p className="analysis-error" role="alert">
              {error}
            </p>
          ) : !data ? (
            <p className="muted" role="status">
              Loading the saved result…
            </p>
          ) : scan ? (
            <ScanTable scan={scan} />
          ) : (
            <pre className="analysis-json">{JSON.stringify(data.result, null, 2)}</pre>
          )}
        </div>

        <footer className="analysis-foot muted small">
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
      </div>
    </div>
  );
}
