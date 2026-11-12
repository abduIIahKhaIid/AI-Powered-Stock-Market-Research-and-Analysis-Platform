import { useEffect, useState } from "react";
import { listAnalyses } from "../jobs/api";
import type { SavedAnalysis } from "../jobs/types";

interface Props {
  onOpen: (analysis: SavedAnalysis) => void;
}

function finishedOn(analysis: SavedAnalysis): string {
  const date = new Date(analysis.finished_at ?? analysis.created_at);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Finished background analyses, kept on the server so they survive a restart. */
export default function SavedAnalyses({ onOpen }: Props) {
  const [items, setItems] = useState<SavedAnalysis[] | null>(null);
  const [failed, setFailed] = useState(false);

  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listAnalyses(controller.signal).then(
      (analyses) => {
        setItems(analyses);
        setFailed(false);
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [reloads]);

  if (items === null && !failed) return null;

  return (
    <section className="saved" aria-labelledby="saved-heading">
      <div className="saved-head">
        <h2 id="saved-heading">Saved analyses</h2>
        <button
          type="button"
          className="icon-button saved-refresh"
          onClick={() => setReloads((n) => n + 1)}
          aria-label="Refresh saved analyses"
        >
          ↻
        </button>
      </div>
      {failed ? (
        <p className="muted small saved-note">Saved analyses could not be loaded.</p>
      ) : items && items.length === 0 ? (
        <p className="muted small saved-note">Finished scans are kept here.</p>
      ) : (
        <ul>
          {items?.map((analysis) => (
            <li key={analysis.id}>
              <button type="button" className="saved-item" onClick={() => onOpen(analysis)}>
                <span className="saved-title">
                  {analysis.title}
                  <span className="saved-date">{finishedOn(analysis)}</span>
                </span>
                {analysis.summary && <span className="saved-summary">{analysis.summary}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
