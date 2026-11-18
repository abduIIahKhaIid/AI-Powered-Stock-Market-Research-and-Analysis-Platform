import { FileBarChart2Icon, RefreshCwIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { listAnalyses } from "../jobs/api";
import type { SavedAnalysis } from "../jobs/types";
import { Button } from "./ui/button";

interface Props {
  onOpen: (analysis: SavedAnalysis) => void;
  /** Changes when a background job finishes, so the list reloads. */
  refreshKey?: number;
}

function finishedOn(analysis: SavedAnalysis): string {
  const date = new Date(analysis.finished_at ?? analysis.created_at);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Finished background analyses, kept on the server so they survive a restart. */
export default function SavedAnalyses({ onOpen, refreshKey = 0 }: Props) {
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
  }, [reloads, refreshKey]);

  if (items === null && !failed) return null;

  return (
    <section aria-labelledby="saved-heading" className="border-t border-border px-2 pt-2 pb-1">
      <div className="flex items-center justify-between px-1">
        <h2
          id="saved-heading"
          className="px-2 text-[11px] font-semibold tracking-wide text-muted-foreground/80 uppercase"
        >
          Saved analyses
        </h2>
        <Button
          size="icon-xs"
          variant="ghost"
          onClick={() => setReloads((n) => n + 1)}
          aria-label="Refresh saved analyses"
        >
          <RefreshCwIcon className="size-3.5" />
        </Button>
      </div>
      {failed ? (
        <p className="px-3 py-2 text-xs text-muted-foreground">
          Saved analyses could not be loaded.
        </p>
      ) : items && items.length === 0 ? (
        <p className="px-3 py-2 text-xs text-muted-foreground">Finished scans are kept here.</p>
      ) : (
        <ul className="max-h-44 overflow-y-auto scrollbar-thin">
          {items?.map((analysis) => (
            <li key={analysis.id}>
              <button
                type="button"
                onClick={() => onOpen(analysis)}
                className="flex w-full cursor-pointer items-start gap-2 rounded-lg px-3 py-1.5 text-left hover:bg-muted"
              >
                <FileBarChart2Icon
                  className="mt-0.5 size-3.5 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate">{analysis.title}</span>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {finishedOn(analysis)}
                    </span>
                  </span>
                  {analysis.summary && (
                    <span className="block truncate text-xs text-muted-foreground">
                      {analysis.summary}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
