/** "Sources" and "Assumptions" chips under a chart or table; each opens its list (SCRUM-37). */
import { useId, useState } from "react";
import type { DetailSource } from "../chat/types";

interface Props {
  sources?: DetailSource[];
  assumptions?: string[];
}

type Panel = "sources" | "assumptions";

export default function DetailChips({ sources = [], assumptions = [] }: Props) {
  const [open, setOpen] = useState<Panel | null>(null);
  const id = useId();
  const toggle = (panel: Panel) => setOpen((current) => (current === panel ? null : panel));

  return (
    <div className="detail-chips">
      <div className="detail-chip-row">
        <button
          type="button"
          className="chip"
          aria-expanded={open === "sources"}
          aria-controls={`${id}-sources`}
          disabled={sources.length === 0}
          onClick={() => toggle("sources")}
        >
          Sources ({sources.length})
        </button>
        <button
          type="button"
          className="chip"
          aria-expanded={open === "assumptions"}
          aria-controls={`${id}-assumptions`}
          disabled={assumptions.length === 0}
          onClick={() => toggle("assumptions")}
        >
          Assumptions ({assumptions.length})
        </button>
      </div>
      {open === "sources" && (
        <ul id={`${id}-sources`} className="detail-panel" aria-label="Sources">
          {sources.map((source) => (
            <li key={`${source.label}|${source.link ?? ""}`}>
              {source.link ? (
                <a href={source.link} target="_blank" rel="noopener noreferrer">
                  {source.label}
                </a>
              ) : (
                source.label
              )}
            </li>
          ))}
        </ul>
      )}
      {open === "assumptions" && (
        <ul id={`${id}-assumptions`} className="detail-panel" aria-label="Assumptions">
          {assumptions.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
